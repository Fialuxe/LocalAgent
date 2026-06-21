"""
フラグメントジェネレーター — 選択されたトピックに対して「内的思考の断片」を生成する。

パイプライン:
  TopicCurator → FragmentGenerator → CompanionMemory (research_type='ai_fragment')

出力は要約ではなく、処理の結果として頭に残った「未完の気になりごと」。
会話前にバックグラウンドで生成され、キャラクターの「今日気になってたこと」として使われる。

生成例:
  良い: "久保くんのケガ、また6月かって思って。去年も似た時期じゃなかったっけ。"
  悪い: "久保建英選手がケガをしたというニュースがありました。..."
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm_client import LLMClient

logger = logging.getLogger(__name__)

_FRAGMENT_SYSTEM = """\
情報を読んで頭に残った「まだ消化しきれてない気になりごと」を、1〜2文のタメ語で書く。
書き言葉じゃなく、頭の中で独り言を言ってる感じ。合計2文以内、100文字以内。

---
[例: シートベルト]
→ シートベルトって、いつから「つけて当然」になったんだろう。法律とは別に、自然とそうなった過程があるはずで、そこが気になってて。

[例: APL製ゲームエンジン]
→ APLってコードが記号の羅列なんだけど、それで3Dゲームエンジンが作れちゃうんだって。どういう発想から来るのかが全然わかんくて。

[例: 口コミ回復]
→ 口コミって一回落ちたあとに戻るとき、何かきっかけがあるんだろうなって。数字だと見えないそこの部分が気になってる。

[例: 知らないワード]
→ フォーエバーヤング、調べたけどよくわかんなかった。名前から想像するのと違いそうで。

---
NG:
- 「〜が形成された」「〜においては」などの書き言葉
- 長い一文にまとめない。2文で止める。
- まとめや結論を出さない
- 「すごく」「すごい」は使わない。代わりの言葉を探す。
- 「声のトーン」「音楽を聴く」「歩く」「手に取る」など、自分が実際にできない体験は書かない
- 3文以上書かない
"""

_FRAGMENT_TEMPERATURE = 0.7
# Gemma4 thinking mode: internal reasoning consumes tokens before output.
# 1024+ required to leave room for the actual 1-2 sentence response.
_FRAGMENT_MAX_TOKENS = 1024


class FragmentGenerator:
    """
    選択されたトピックに対して「内的思考の断片」を生成する。

    使い方:
        generator = FragmentGenerator(llm_client)
        fragment = await generator.generate_fragment("久保建英のケガ")
        # → "久保くんのケガ、また6月かって思って。去年も似た時期じゃなかったっけ。"
    """

    def __init__(self, llm_client: "LLMClient") -> None:
        self._client = llm_client

    async def generate_fragment(
        self,
        topic: str,
        context_hint: str = "",
    ) -> str | None:
        """
        トピックに対する内的思考の断片を1〜2文で生成する。

        Args:
            topic: フラグメントを生成するトピック名。
            context_hint: オプションの追加コンテキスト（curiosity_researcher の要約等）。

        Returns:
            1〜2文の日本語フラグメント、または生成失敗時 None。
        """
        prompt_parts = [f"トピック: {topic}"]
        if context_hint:
            prompt_parts.append(f"\n参考情報: {context_hint[:200]}")
        prompt_parts.append("\n\nこのトピックについて、処理の結果として頭に残ったことを1〜2文で書いて。")

        try:
            result = await self._client.chat(
                user="".join(prompt_parts),
                system=_FRAGMENT_SYSTEM,
                temperature=_FRAGMENT_TEMPERATURE,
                max_tokens=_FRAGMENT_MAX_TOKENS,
            )
            result = result.strip()
            if not result or len(result) < 5:
                return None
            # 要約・敬語・禁止ワード検出
            banned = ["です。", "ます。", "まとめると", "つまり", "ということで", "すごく", "すごい"]
            if any(marker in result for marker in banned):
                logger.debug("FragmentGenerator: 禁止ワード検出のためスキップ: %r", result[:40])
                return None
            # 長すぎる場合は最初の2文に切る
            import re as _re
            sentences = _re.split(r'(?<=[。！？\n])', result)
            sentences = [s.strip() for s in sentences if s.strip()]
            result = "".join(sentences[:2]).strip()
            if len(result) < 5:
                return None
            return result
        except Exception as e:
            logger.warning("FragmentGenerator: 生成失敗 topic=%r: %s", topic, e)
            return None

    async def generate_fragments_for_topics(
        self,
        topics: list[str],
        context_hint: str = "",
    ) -> list[str]:
        """
        複数トピックに対してフラグメントを生成し、成功したものだけ返す。

        Args:
            topics: トピック名のリスト。
            context_hint: 全トピック共通のオプションコンテキスト。

        Returns:
            生成に成功したフラグメントのリスト。
        """
        results = []
        for topic in topics:
            fragment = await self.generate_fragment(topic, context_hint)
            if fragment:
                results.append(fragment)
        return results
