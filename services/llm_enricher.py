"""
LLMエンリッチャー — ニュース・トレンドをLLMで解釈・要約する。

パイプライン:
  生APIデータ → LLMEnricher → 解釈済みテキスト → Gemma（会話）

エンリッチャーはキャラクターLLMとは別の軽量な呼び出しで動作する:
  - 低温度（0.3）で事実に忠実
  - 短出力（max 120 tokens）で高速
  - 入力が変わらなければキャッシュを再利用

例:
  入力: ["AI規制法案が衆院を通過", "円安が進行", "桜前線北上"]
  出力: "今日の日本では、AIと経済政策の動きが特に注目されています。"
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from .cache import AsyncTTLCache
from .models import HackerNewsData, NewsData, TrendData

if TYPE_CHECKING:
    from .llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM = (
    "あなたは簡潔な情報アシスタントです。"
    "与えられたニュース・トレンドの本質的なテーマを抽出し、"
    "1〜2文の自然な日本語でまとめます。箇条書きは使いません。"
)
_ENRICHER_TEMPERATURE = 0.3
_ENRICHER_MAX_TOKENS  = 120


def _cache_key(prefix: str, items: list[str]) -> str:
    digest = hashlib.md5("|".join(items).encode()).hexdigest()[:8]
    return f"{prefix}:{digest}"


class LLMEnricher:
    """
    使い方:
        enricher = LLMEnricher(llm_client)
        agg = InfoAggregator(enricher=enricher)
        context = await agg.format_for_llm()
        # → 生データ + LLM解釈ブロックが両方含まれたコンテキスト文字列
    """

    def __init__(self, client: LLMClient, ttl: int = 1800) -> None:
        self._client = client
        self._ttl    = ttl
        self._cache  = AsyncTTLCache()

    # ── 個別エンリッチメント ──────────────────────────────────────────────────

    async def summarize_news(
        self,
        items: list[str],
        region_label: str = "日本",
    ) -> str | None:
        """ニュース・トレンドタイトルの一覧 → 「今日の主なテーマ」1〜2文。"""
        if not items:
            return None
        key = _cache_key(f"summary:{region_label}", items)
        if cached := await self._cache.get(key, self._ttl):
            return cached

        titles = "\n".join(f"- {t}" for t in items[:8])
        prompt = (
            f"{region_label}の今日の主なニュース・話題です:\n"
            f"<titles>\n{titles}\n</titles>\n\n"
            "上記タイトルから「今日の主なテーマ」を1〜2文の自然な日本語でまとめてください。"
        )
        return await self._call(key, prompt)

    async def cross_regional_insight(
        self,
        jp_topics: list[str],
        kr_topics: list[str],
    ) -> str | None:
        """JP + KR のトレンドを横断的に比較・解釈する。"""
        if not jp_topics or not kr_topics:
            return None
        key = _cache_key("cross", jp_topics[:5] + ["|"] + kr_topics[:5])
        if cached := await self._cache.get(key, self._ttl):
            return cached

        jp = "、".join(jp_topics[:5])
        kr = "、".join(kr_topics[:5])
        prompt = (
            f"日本で話題: {jp}\n"
            f"韓国で話題: {kr}\n\n"
            "両国のトレンドを踏まえ、共通点や特徴的な違いを1文で教えてください。"
        )
        return await self._call(key, prompt)

    async def summarize_tech_news(self, items: list[str]) -> str | None:
        """Hacker News のタイトル（英語）を日本語で要約する。"""
        if not items:
            return None
        key = _cache_key("hn", items)
        if cached := await self._cache.get(key, self._ttl):
            return cached

        titles = "\n".join(f"- {t}" for t in items[:5])
        prompt = (
            f"以下はHacker Newsの今日の注目記事（英語）です:\n"
            f"<titles>\n{titles}\n</titles>\n\n"
            "エンジニア目線で、今日のテック界の注目点を1文の日本語でまとめてください。"
        )
        return await self._call(key, prompt)

    # ── 一括エンリッチメント（aggregator から呼ばれる）────────────────────────

    async def enrich(self, provider_results: dict) -> str:
        """
        全プロバイダ結果を受け取り、LLM解釈済みの追加コンテキストブロックを返す。
        InfoAggregator.format_for_llm() が内部で呼ぶ。
        """
        jp_topics: list[str] = []
        kr_topics: list[str] = []
        hn_titles: list[str] = []

        for name, result in provider_results.items():
            if result.error or result.data is None:
                continue
            d = result.data

            if isinstance(d, TrendData):
                topics = [i.keyword for i in d.items]
                (jp_topics if d.region == "JP" else kr_topics).extend(topics)

            elif isinstance(d, NewsData):
                titles = [i.title for i in d.items]
                if d.region == "JP":
                    jp_topics.extend(titles)
                elif d.region == "KR":
                    kr_topics.extend(titles)

            elif isinstance(d, HackerNewsData):
                hn_titles.extend(i.title for i in d.items)

        import asyncio  # 並列でエンリッチメントを実行
        jp_sum, kr_sum, hn_sum, cross = await asyncio.gather(
            self.summarize_news(jp_topics, "日本"),
            self.summarize_news(kr_topics, "韓国"),
            self.summarize_tech_news(hn_titles),
            self.cross_regional_insight(jp_topics, kr_topics),
            return_exceptions=True,
        )

        lines: list[str] = []
        if isinstance(jp_sum, str):
            lines.append(f"🧠 日本の今日のテーマ: {jp_sum}")
        if isinstance(kr_sum, str):
            lines.append(f"🧠 韓国の今日のテーマ: {kr_sum}")
        if isinstance(hn_sum, str):
            lines.append(f"🧠 テック界の注目: {hn_sum}")
        if isinstance(cross, str):
            lines.append(f"🌏 日韓比較: {cross}")

        if lines:
            return "\n\n[AI解釈]\n" + "\n".join(lines)
        return ""

    # ── 内部 ────────────────────────────────────────────────────────────────

    async def _call(self, cache_key: str, prompt: str) -> str | None:
        try:
            result = await self._client.chat(
                user=prompt,
                system=_SYSTEM,
                temperature=_ENRICHER_TEMPERATURE,
                max_tokens=_ENRICHER_MAX_TOKENS,
            )
            result = result.strip()
            if not result:
                return None
            await self._cache.set(cache_key, result)
            return result
        except Exception as e:
            logger.warning("LLMEnricher call failed: %s", e)
            return None
