"""
NewsAPI.org プロバイダ（日本・韓国ニュース）。

無料プラン: 100リクエスト/日
登録: https://newsapi.org/register

.env に設定:
  NEWSAPI_KEY=your_api_key
"""

from typing import Literal

import httpx

from .base import BaseProvider
from .config import APIConfig
from .models import NewsData, NewsItem, ProviderResult

_ENDPOINT = "https://newsapi.org/v2/top-headlines"

_REGION_PARAMS: dict[str, dict] = {
    "JP": {"country": "jp", "language": "ja"},
    "KR": {"country": "kr", "language": "ko"},
}


class NewsAPIProvider(BaseProvider):
    """
    NewsAPI.org でトップニュースを取得する。
    JP / KR 両対応。Yahoo Japan RSS より信頼性が高く、記事の鮮度も良い。

    Args:
        region: "JP" または "KR"
        top_n:  取得件数（最大 5、無料枠節約のため）
    """

    default_ttl = 1800  # 30分

    def __init__(self, region: Literal["JP", "KR"] = "JP", top_n: int = 5) -> None:
        if region not in _REGION_PARAMS:
            raise ValueError(f"region must be 'JP' or 'KR', got '{region}'")
        self.region = region
        self.top_n = min(top_n, 10)
        self.name = f"newsapi_{region.lower()}"

    async def fetch(self) -> ProviderResult:
        if not APIConfig.has_newsapi():
            return self._err(
                "NewsAPI キー未設定。.env に NEWSAPI_KEY を設定してください。"
            )
        params = {
            **_REGION_PARAMS[self.region],
            "pageSize": self.top_n,
        }
        # APIキーはURLではなくヘッダーで送る（URLはログ・プロキシに残るため）
        headers = {"X-Api-Key": APIConfig.NEWSAPI_KEY or ""}
        try:
            async with httpx.AsyncClient(timeout=8.0, verify=True) as client:
                resp = await client.get(_ENDPOINT, params=params, headers=headers)
                resp.raise_for_status()
                raw: dict = resp.json()

            articles = raw.get("articles", [])[: self.top_n]
            items = [
                NewsItem(
                    rank=i + 1,
                    title=(a.get("title") or "").split(" - ")[0].strip(),  # 末尾のソース名を除去
                )
                for i, a in enumerate(articles)
                if a.get("title") and a["title"] != "[Removed]"
            ]
            source_key = f"newsapi_{self.region.lower()}"
            return self._ok(NewsData(source=source_key, region=self.region, items=items))
        except Exception as e:
            return self._err(str(e))
