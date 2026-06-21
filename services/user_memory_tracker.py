"""
ユーザーメモリトラッカー — ユーザー発言からトピックを抽出し記憶する。

Phase 3A（ユーザートリガー記憶）向けモジュール。

ユーザーが「来月京都行こうと思ってて」のように何かに言及したとき:
  1. トピックを抽出する
  2. CompanionMemory に research_type='user_mention' で保存する
  3. その場ではリサーチしない（スケジューラー経由の遅延リサーチに委ねる）

user_mention 記憶は ai_curiosity とは異なる動作をする:
  - ユーザーが言及したタイミングで保存される
  - リサーチはスケジューラーの次回実行時に遅延実行される
  - ユーザーが同じトピックに再び触れたときに surfaced される
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from . import keyword_extractor

if TYPE_CHECKING:
    from .companion_memory import CompanionMemory
    from .curiosity_researcher import CuriosityResearcher

logger = logging.getLogger(__name__)

# 除外するストップワード（助詞・補助動詞・超一般名詞・頻出高頻度語）
_STOPWORDS: frozenset[str] = frozenset({
    "こと", "もの", "とき", "ため", "ところ", "ひと",
    "人", "事", "物", "時", "今", "日", "年", "月",
    # 高頻度すぎてトピックとして意味を持たない名詞
    "経済", "社会", "技術", "問題", "情報", "話", "内容",
    "日本", "東京", "世界", "国", "地域",
    "AI", "IT", "DX",
})

# 1メッセージあたりに保存するトピック数の上限
_MAX_TOPICS_PER_MESSAGE = 3

# トピックとして扱う最小文字数
_MIN_TOPIC_LENGTH = 2


class UserMemoryTracker:
    """
    ユーザー発言からトピックを抽出し、CompanionMemory に user_mention として保存する。

    使い方:
        memory = CompanionMemory()
        await memory.initialize()

        tracker = UserMemoryTracker(memory)
        await tracker.process_user_message("来月京都行こうと思ってて")
        # → "京都" が user_mention として保存される（リサーチはしない）

        # スケジューラーから呼ぶ場合:
        researcher = CuriosityResearcher(llm_client)
        tracker = UserMemoryTracker(memory, curiosity_researcher=researcher)
        await tracker.research_pending_user_mentions()
    """

    def __init__(
        self,
        memory: "CompanionMemory",
        curiosity_researcher: "CuriosityResearcher | None" = None,
        allow_user_mention_research: bool = False,
    ) -> None:
        self._memory = memory
        self._researcher = curiosity_researcher
        # OFF by default: auto-researching user-mentioned topics is a privacy
        # violation — silently acting on things the user casually said crosses the
        # "never surface behavioral inferences" line. Enable only with explicit opt-in.
        self._allow_user_mention_research = allow_user_mention_research

    async def process_user_message(self, user_text: str) -> None:
        """
        ユーザーメッセージから名詞を抽出し、トピックを user_mention として保存する。

        - 2文字以上の名詞のみ対象
        - ストップワードは除外
        - 1メッセージにつき最大 3 トピックまで保存
        - リサーチは行わない（ホットパス: 50ms 以内に完了させる）
        """
        if not user_text or not user_text.strip():
            return

        nouns = keyword_extractor.extract_nouns(user_text)

        # フィルタリング: 最小文字数・ストップワード除外
        candidates = [
            n for n in nouns
            if len(n) >= _MIN_TOPIC_LENGTH and n not in _STOPWORDS
        ]

        if not candidates:
            logger.debug("UserMemoryTracker: no candidates found in message")
            return

        # 最大件数に絞る（extract_nouns は set を返すため順序が不定だが、
        # sorted で決定的にしてから先頭 N 件を取る）
        topics = sorted(candidates)[:_MAX_TOPICS_PER_MESSAGE]

        for topic in topics:
            keywords_str = keyword_extractor.nouns_to_keywords_string({topic})
            logger.debug("UserMemoryTracker: saving topic=%r", topic)
            await self._memory.save(
                topic=topic,
                keywords=keywords_str,
                research_type="user_mention",
            )

    async def research_pending_user_mentions(self) -> None:
        """
        status='pending' かつ researched_summary が未設定の user_mention 記憶を
        CuriosityResearcher でリサーチし、summary を保存する。

        デフォルトでは無効（allow_user_mention_research=True で明示的に有効化する必要がある）。
        ユーザーの発言をAIが自動的に背後でリサーチすることはプライバシー侵害にあたるため。
        """
        if not self._allow_user_mention_research:
            logger.debug(
                "UserMemoryTracker: user_mention auto-research is disabled (allow_user_mention_research=False)"
            )
            return

        if self._researcher is None:
            logger.debug(
                "UserMemoryTracker: curiosity_researcher is None, skipping research"
            )
            return

        pending = await self._memory.get_pending()
        user_mention_pending = [
            m for m in pending
            if m.get("research_type") == "user_mention"
            and not m.get("researched_summary")
        ]

        if not user_mention_pending:
            logger.debug("UserMemoryTracker: no pending user_mention entries to research")
            return

        for entry in user_mention_pending:
            topic = entry["topic"]
            memory_id = entry["id"]
            logger.debug("UserMemoryTracker: researching topic=%r (id=%d)", topic, memory_id)

            try:
                summary = await self._researcher.research_topic(topic)
            except Exception as exc:
                logger.warning(
                    "UserMemoryTracker: research failed for topic=%r: %s",
                    topic,
                    exc,
                )
                continue

            if summary:
                await self._memory.update_summary(memory_id, summary)
                logger.debug(
                    "UserMemoryTracker: summary saved for topic=%r (id=%d)",
                    topic,
                    memory_id,
                )
