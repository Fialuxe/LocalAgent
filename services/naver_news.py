"""
Naver ニュース検索 API プロバイダ（韓国語ニュース）。

登録無料・APIキー無料:
  https://developers.naver.com/apps/#/register
  → Application 登録 → 「検索」にチェック → Client ID と Secret を取得

.env に以下を設定:
  NAVER_CLIENT_ID=your_client_id
  NAVER_CLIENT_SECRET=your_client_secret
"""

import httpx

from .base import BaseProvider
from .config import APIConfig
from .models import NewsData, NewsItem, ProviderResult

_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"


class NaverNewsProvider(BaseProvider):
    """
    Naver ニュース検索 API で韓国の最新ニュースを取得する。
    pytrends の KR 代替として機能する。安定・高速。

    Args:
        query:   検索クエリ（デフォルト: "속보" = 速報）
        top_n:   取得件数
    """

    name = "naver_news"
    default_ttl = 1800  # 30分

    def __init__(self, query: str = "속보", top_n: int = 5) -> None:
        self.query = query
        self.top_n = top_n

    async def fetch(self) -> ProviderResult:
        if not APIConfig.has_naver():
            return self._err(
                "Naver APIキー未設定。.env に NAVER_CLIENT_ID と "
                "NAVER_CLIENT_SECRET を設定してください。"
            )
        headers = {
            "X-Naver-Client-Id":     APIConfig.NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": APIConfig.NAVER_CLIENT_SECRET,
        }
        params = {
            "query":   self.query,
            "display": self.top_n,
            "sort":    "date",
            "start":   1,
        }
        try:
            async with httpx.AsyncClient(timeout=8.0, verify=True) as client:
                resp = await client.get(_ENDPOINT, headers=headers, params=params)
                resp.raise_for_status()
                raw: dict = resp.json()

            items = [
                NewsItem(
                    rank=i + 1,
                    # タイトルに混在するHTMLタグを除去
                    title=_strip_html(article.get("title", "")),
                )
                for i, article in enumerate(raw.get("items", [])[: self.top_n])
            ]
            return self._ok(NewsData(source="naver_kr", region="KR", items=items))
        except Exception as e:
            return self._err(str(e))


def _strip_html(text: str) -> str:
    """Naver APIが返すHTMLタグ（<b> など）を除去する。"""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()
