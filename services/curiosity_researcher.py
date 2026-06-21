"""
好奇心リサーチャー — トレンドトピックに関連する発信者・専門家をウェブ検索し、LLMで要約する。

パイプライン:
  トピック → DuckDuckGo検索 → 生テキスト → LLM要約 → 発見報告文

出力はあくまで「見つけた事実の報告」であり、おすすめ・推薦表現は使わない。

例:
  良い: "〇〇さんっていう人がこの話よく取り上げてるらしくて、△△についても詳しそうだった"
  悪い: "〇〇さんがおすすめです" / "チャンネル見てみて"
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import urllib.parse
from typing import TYPE_CHECKING

from .cache import AsyncTTLCache

if TYPE_CHECKING:
    from .llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM = (
    "簡潔に、誰がこのトピックについて発信しているか事実だけ書く。"
    "推薦・おすすめの表現は使わない。"
    "「〇〇さんっていう人がよく取り上げてるらしくて」のような、"
    "自分が調べて見つけた、という口調で2〜3文の日本語にまとめる。"
)
_SUMMARIZER_TEMPERATURE = 0.3
# Gemma4 thinking mode: needs 512+ even for short summaries.
_SUMMARIZER_MAX_TOKENS = 512

_DDG_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_TITLE_RE = re.compile(r'<a class="result__a"[^>]*>(.+?)</a>', re.DOTALL)
_SNIPPET_RE = re.compile(r'<a class="result__snippet"[^>]*>(.+?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

_CACHE_TTL = 3600  # 1時間


def _strip_tags(html: str) -> str:
    """HTMLタグを除去してプレーンテキストに変換する。"""
    return _TAG_RE.sub("", html).strip()


def _cache_key(topic: str) -> str:
    digest = hashlib.md5(topic.encode()).hexdigest()[:8]
    return f"curiosity:{digest}"


class CuriosityResearcher:
    """
    トレンドトピックに関連する発信者・専門家を検索し、
    AIが「自分が調べて発見した」という口調で報告できるサマリーを生成する。

    使い方:
        researcher = CuriosityResearcher(llm_client)
        summary = await researcher.research_topic("量子コンピュータ")
        # → "田中さんっていう研究者がよくこのテーマ取り上げてるらしくて、..."
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._client = llm_client
        self._cache = AsyncTTLCache()

    async def research_topic(self, topic: str) -> str | None:
        """
        メインメソッド: トピックに関連する発信者・専門家を検索し、
        2〜3文のカジュアルな日本語サマリーを返す。
        検索失敗や有用な結果が得られない場合は None を返す。
        """
        key = _cache_key(topic)
        if cached := await self._cache.get(key, _CACHE_TTL):
            logger.debug("CuriosityResearcher cache hit: %s", topic)
            return cached

        queries = [
            f"{topic} 詳しい 発信者 インフルエンサー",
            f"{topic} 解説 YouTube OR Twitter",
        ]

        raw_results: str | None = None
        for i, query in enumerate(queries):
            if i > 0:
                await asyncio.sleep(2.0)
            try:
                result = await self._ddg_search(query)
                if result.strip():
                    raw_results = result
                    break
            except Exception as e:
                logger.warning("DuckDuckGo search failed (query=%r): %s", query, e)

        if not raw_results:
            logger.debug("CuriosityResearcher: no results for topic=%r", topic)
            return None

        summary = await self._summarize(topic, raw_results)
        if summary:
            await self._cache.set(key, summary, _CACHE_TTL)
        return summary

    async def _ddg_search(self, query: str) -> str:
        """
        DuckDuckGo HTMLエンドポイント経由でウェブ検索する。
        GET https://html.duckduckgo.com/html/?q={query}
        タイトルとスニペットを最大5件抽出し、連結したテキストを返す。
        """
        import urllib.request

        encoded = urllib.parse.urlencode({"q": query})
        url = f"{_DDG_URL}?{encoded}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "ja,en;q=0.9",
            },
        )

        # ブロッキングI/Oをスレッドプールにオフロードしてイベントループをブロックしない
        loop = asyncio.get_event_loop()
        html: str = await loop.run_in_executor(None, _fetch_url, req)

        titles = _TITLE_RE.findall(html)[:5]
        snippets = _SNIPPET_RE.findall(html)[:5]

        parts: list[str] = []
        for i, title in enumerate(titles):
            clean_title = _strip_tags(title)
            snippet_text = _strip_tags(snippets[i]) if i < len(snippets) else ""
            if clean_title:
                parts.append(f"【{clean_title}】{snippet_text}")

        return "\n".join(parts)

    async def _summarize(self, topic: str, raw_results: str) -> str | None:
        """
        LLM呼び出し: 検索結果から発信者・専門家の情報を抽出し、
        「自分が発見した」口調の2〜3文日本語サマリーを生成する。
        おすすめ・推薦表現は使わない。
        """
        prompt = (
            f"トピック: {topic}\n\n"
            f"以下は検索で見つかった情報です:\n"
            f"<results>\n{raw_results[:800]}\n</results>\n\n"
            "上記の情報から、このトピックについて発信・解説している人物や"
            "チャンネル・アカウントを見つけたことを、"
            "「〇〇さんっていう人がよく取り上げてるらしくて」のような口調で"
            "2〜3文の日本語でまとめてください。"
            "おすすめや推薦の表現は使わないでください。"
        )
        try:
            result = await self._client.chat(
                user=prompt,
                system=_SYSTEM,
                temperature=_SUMMARIZER_TEMPERATURE,
                max_tokens=_SUMMARIZER_MAX_TOKENS,
            )
            result = result.strip()
            if not result:
                return None
            return result
        except Exception as e:
            logger.warning("CuriosityResearcher summarize failed: %s", e)
            return None


def _fetch_url(req: "urllib.request.Request") -> str:
    """同期的にURLを取得し、HTMLテキストを返す（executor経由で呼ぶ）。"""
    import urllib.request

    with urllib.request.urlopen(req, timeout=8) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")
