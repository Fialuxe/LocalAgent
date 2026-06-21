"""
会話マネージャー — メモリ統合付きの単一会話ターン処理。

パイプライン:
  ユーザーメッセージ
    → キーワード抽出（noun extraction or substring fallback）
    → researched メモリとのマッチング
    → システムメッセージにメモリブロックを自然に注入
    → LLM呼び出し
    → 注入したメモリを delivered にマーク

設計原則:
  - メモリ機能は補助的（失敗しても通常の会話に fallback）
  - LLM 呼び出し自体の失敗は呼び出し元に伝播させる
  - 注入するメモリは最大2件（コンテキスト圧迫を防ぐ）
  - 履歴は最大10ターン（5往復）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .companion_memory import CompanionMemory
    from .llm_client import LLMClient

logger = logging.getLogger(__name__)

# 1ターンに注入するメモリの最大件数
_MAX_INJECTED = 2

# 送信する履歴の最大エントリ数（user + assistant で合わせて10）
_MAX_HISTORY = 10

# メモリブロックのヘッダー
_MEMORY_HEADER = "[さっき気になって調べてたこと]"


def _extract_nouns(text: str) -> set[str]:
    """
    テキストから名詞候補を抽出する。

    keyword_extractor モジュールが存在すればそちらを使い、
    なければ空白区切りの単純分割にフォールバックする。

    Note: 日本語は空白が無いため、フォールバック時は空セットになることが多い。
    実際のマッチングは `_is_triggered` 内の部分文字列検索が主体。
    keyword_extractor.py が実装されたら、そちらで正確な名詞抽出が行われる。
    """
    try:
        # keyword_extractor が存在する場合はそちらを使う
        # 関数名は keyword_extractor.py 実装時に合わせて修正すること
        from .keyword_extractor import extract_nouns  # type: ignore[import]
        return set(extract_nouns(text))
    except ImportError:
        pass
    except Exception as e:
        logger.debug("keyword_extractor.extract_nouns failed: %s", e)

    # フォールバック: 空白区切り（英語トークン向け）
    return {token for token in text.split() if len(token) >= 2}


def _is_triggered(memory: dict, user_message: str, nouns: set[str]) -> bool:
    """
    メモリがユーザーメッセージに関連するかチェックする。

    マッチング戦略（いずれかを満たせば True）:
    1. topic がユーザーメッセージに含まれる
    2. keywords の各単語がユーザーメッセージに含まれる
    3. topic または keywords の単語が抽出済み nouns と重複する
    """
    topic: str = memory.get("topic", "")
    keywords_raw: str = memory.get("keywords", "")
    kw_set = set(keywords_raw.split()) | ({topic} if topic else set())

    # 部分文字列マッチ（日本語のメインパス）
    if topic and topic in user_message:
        return True
    for kw in kw_set:
        if kw and kw in user_message:
            return True

    # noun セットとの積集合（英語 / keyword_extractor 利用時のサブパス）
    if nouns & kw_set:
        return True

    return False


class ConversationManager:
    """
    LLMクライアントとコンパニオンメモリを組み合わせ、
    メモリ統合付きの会話ターンを処理するクラス。

    使い方:
        manager = ConversationManager(llm_client, memory, system_prompt)
        response = await manager.respond(user_message, context, history)
    """

    def __init__(
        self,
        llm_client: "LLMClient",
        memory: "CompanionMemory",
        system_prompt: str,
    ) -> None:
        self._llm_client = llm_client
        self._memory = memory
        self._system_prompt = system_prompt

    async def respond(
        self,
        user_message: str,
        context: str,
        history: list[dict],
    ) -> str:
        """
        メモリ統合付きで LLM 応答を生成する。

        1. ユーザーメッセージから名詞を抽出
        2. researched かつ未期限のメモリをマッチング（最大2件）
        3. トリガーされたメモリをシステムメッセージに注入
        4. LLM を呼び出す
        5. 注入したメモリを delivered にマーク

        Args:
            user_message: ユーザーの発言テキスト
            context:      InfoAggregator.format_for_llm() が返す文脈情報
            history:      過去の会話履歴 [{"role": "user"/"assistant", "content": str}, ...]

        Returns:
            LLM が生成した応答テキスト
        """
        triggered_memories: list[dict] = []

        try:
            # 1. 名詞抽出
            nouns = _extract_nouns(user_message)

            # 2. researched メモリとのマッチング
            researched = await self._memory.get_researched()
            for mem in researched:
                if _is_triggered(mem, user_message, nouns):
                    triggered_memories.append(mem)
                if len(triggered_memories) >= _MAX_INJECTED:
                    break

        except Exception as e:
            # メモリ取得失敗は会話には影響させない
            logger.warning("メモリ取得/マッチング失敗: %s", e)
            triggered_memories = []

        # 3. システムメッセージを構築（失敗しても基本プロンプトで継続）
        full_system = self._build_system(context, triggered_memories)

        # 4. 履歴スライス（最大 _MAX_HISTORY エントリ）
        history_slice = history[-_MAX_HISTORY:]

        # 5. LLM 呼び出し（失敗は伝播させる）
        response = await self._llm_client.chat(
            user=user_message,
            system=full_system,
            history=history_slice,
        )

        # 6. 注入したメモリを delivered にマーク（LLM 成功後のみ）
        for mem in triggered_memories:
            try:
                await self._memory.mark_delivered(mem["id"])
            except Exception as e:
                logger.warning("mark_delivered 失敗 (id=%s): %s", mem.get("id"), e)

        return response

    def _build_system(
        self,
        context: str,
        triggered_memories: list[dict],
    ) -> str:
        """
        システムメッセージ文字列を組み立てる。

        構成:
          1. self._system_prompt
          2. context ブロック（空でも区切りを入れる）
          3. メモリブロック（トリガーされた場合のみ）
        """
        parts: list[str] = [self._system_prompt]

        if context:
            parts.append(context)

        if triggered_memories:
            memory_lines: list[str] = [_MEMORY_HEADER]
            for mem in triggered_memories:
                topic: str = mem.get("topic", "")
                summary: str = mem.get("researched_summary", "") or ""
                if topic and summary:
                    memory_lines.append(f"{topic}: {summary}")
            # ヘッダー以外に行が追加された場合のみブロックを付加
            if len(memory_lines) > 1:
                parts.append("\n".join(memory_lines))

        return "\n\n".join(parts)

    def _build_messages(
        self,
        user_message: str,
        context: str,
        triggered_memories: list[dict],
        history: list[dict],
    ) -> list[dict]:
        """
        LLM に渡す messages リストを構築する。

        構成:
          - system: self._system_prompt + context + オプションのメモリブロック
          - history: 最後 _MAX_HISTORY ターン
          - user: 現在のメッセージ

        Note: respond() は chat() の引数分離スタイルを採用しているため
        このメソッドを直接は呼ばない。外部ツールや検査用に公開している。
        """
        full_system = self._build_system(context, triggered_memories)
        history_slice = history[-_MAX_HISTORY:]

        messages: list[dict] = []
        if full_system:
            messages.append({"role": "system", "content": full_system})
        messages.extend(history_slice)
        messages.append({"role": "user", "content": user_message})
        return messages
