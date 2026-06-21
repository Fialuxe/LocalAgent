"""
トピックキュレーター — 今日の集約データから「もっと知りたい」トピックを1〜2個選ぶ。

パイプライン:
  InfoAggregator.format_for_llm() → TopicCurator → list[str] → 好奇心リサーチへ

選択基準（LLMプロンプトに反映）:
  - 本当に意外性・新規性のあるもの（ありきたりな政治/経済ニュースは除く）
  - 「誰がやっているか」という具体的な角度があるもの（人物・製品・ムーブメント）
  - 文化/食/テック/社会トレンドを優先
  - 天気・株価・政治プロセス・国際紛争は選ばない
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM = (
    "与えられた今日の情報から、「なぜこうなっているのか調べてみたい」と思えるトピックを"
    "1〜2個だけ選んでください。\n"
    "選ばないもの: 天気・株価・政治プロセス・スポーツ選手の個人ニュース（ケガ・移籍等）・事件事故。\n"
    "優先するもの: テクノロジー・文化トレンド・社会の変化・口コミや評判の動き・面白い現象・"
    "ファッション・ビューティー・香水・グルメ・ライフスタイル・季節のトレンド。\n"
    "視点: 「なぜ今これが話題になっているのか」「誰が最初に広めたのか」という角度で選ぶ。\n"
    "トピック名だけを改行区切りで出力。"
)
_CURATOR_TEMPERATURE = 0.3
# Gemma4 thinking mode: needs 1024+ to output even a short topic list.
_CURATOR_MAX_TOKENS = 1024


class TopicCurator:
    """
    使い方:
        curator = TopicCurator(llm_client)
        topics = await curator.pick_interesting_topics(context_string)
        # → ["発酵食品", "生成AI規制"] のようなトピックリスト（0〜2件）
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._client = llm_client

    async def pick_interesting_topics(
        self,
        context_string: str,
        n: int = 2,
    ) -> list[str]:
        """
        今日の集約コンテキスト文字列を受け取り、さらに調べる価値がある
        トピック名を1〜2個返す。

        Args:
            context_string: InfoAggregator.format_for_llm() の出力。
            n: 返すトピックの最大数（デフォルト2）。

        Returns:
            短いトピックラベルのリスト（例: ["発酵食品", "生成AI規制"]）。
            興味深いものがなければ空リストを返す。
        """
        if not context_string.strip():
            logger.debug("TopicCurator: context_string が空のためスキップ")
            return []

        user_prompt = f"今日の情報:\n{context_string}\n\n気になるトピック（1〜2個）:"

        try:
            raw = await self._client.chat(
                user=user_prompt,
                system=_SYSTEM,
                temperature=_CURATOR_TEMPERATURE,
                max_tokens=_CURATOR_MAX_TOKENS,
            )
        except Exception as e:
            logger.warning("TopicCurator: LLM呼び出し失敗: %s", e)
            return []

        topics = [t for t in (line.strip() for line in raw.splitlines()) if 2 <= len(t) <= 30]
        result = topics[:n]
        logger.debug("TopicCurator: 選出トピック=%s", result)
        return result

    async def pick_interesting_topics_with_context(
        self,
        context_string: str,
        n: int = 2,
    ) -> list[dict]:
        """
        トピックと「なぜ気になるか」の一言を返す。
        FragmentGenerator がより具体的な内的思考を生成できるように。

        Returns:
            [{"topic": "久保建英のケガ", "why": "去年も同時期に発生"}] のような辞書リスト。
            解析失敗時は空リスト。
        """
        if not context_string.strip():
            return []

        system = (
            "与えられた今日の情報から、「誰がこれを詳しく発信しているのか気になる」と思えるトピックを"
            "1〜2個だけ選んでください。天気・株価・政治プロセスは選ばないこと。"
            "各行を「トピック名|なぜ気になるか（10〜20文字）」の形式で出力。"
        )
        user_prompt = f"今日の情報:\n{context_string}\n\n気になるトピック（1〜2個、パイプ区切り）:"

        try:
            raw = await self._client.chat(
                user=user_prompt,
                system=system,
                temperature=_CURATOR_TEMPERATURE,
                max_tokens=100,
            )
        except Exception as e:
            logger.warning("TopicCurator with_context: LLM呼び出し失敗: %s", e)
            return []

        results = []
        for line in raw.splitlines():
            line = line.strip()
            if "|" in line:
                parts = line.split("|", 1)
                topic = parts[0].strip()
                why = parts[1].strip() if len(parts) > 1 else ""
                if 2 <= len(topic) <= 30:
                    results.append({"topic": topic, "why": why})
            elif 2 <= len(line) <= 30:
                results.append({"topic": line, "why": ""})
        return results[:n]
