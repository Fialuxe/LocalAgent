"""
Google News RSS 検索プロバイダー。

キーワードを指定してGoogleニュースのRSSを取得する。
APIキー不要・登録不要。個人利用向け。

対象カテゴリ: ファッション / ビューティー / 香水 / グルメ / ライフスタイル
"""

import urllib.parse
import xml.etree.ElementTree as ET

import httpx

from .base import BaseProvider
from .models import NewsData, NewsItem, ProviderResult

_BASE_URL = "https://news.google.com/rss/search"


class GoogleNewsSearchProvider(BaseProvider):
    """
    Google News RSS 検索プロバイダー。

    使い方:
        agg.register(GoogleNewsSearchProvider(query="ファッション トレンド", source_label="fashion", top_n=5))
    """

    default_ttl = 1800  # 30分

    def __init__(self, query: str, source_label: str = "google_news", top_n: int = 5) -> None:
        self.query = query
        self.source_label = source_label
        self.top_n = top_n
        self.name = f"google_news_search_{source_label}"

    async def fetch(self) -> ProviderResult:
        params = urllib.parse.urlencode({
            "q": self.query,
            "hl": "ja",
            "gl": "JP",
            "ceid": "JP:ja",
        })
        url = f"{_BASE_URL}?{params}"

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "LocalAgent/1.0 (personal desktop app)"},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

            root = ET.fromstring(resp.text)
            items: list[NewsItem] = []

            for i, item_el in enumerate(root.iter("item"), 1):
                title_el = item_el.find("title")
                if title_el is not None and title_el.text:
                    title = title_el.text.strip()
                    # Google News タイトルは「記事名 - メディア名」形式
                    # メディア名部分を除去して記事名だけにする
                    if " - " in title:
                        title = title.rsplit(" - ", 1)[0].strip()
                    items.append(NewsItem(rank=i, title=title))
                if len(items) >= self.top_n:
                    break

            return self._ok(NewsData(source=self.source_label, region="JP", items=items))
        except Exception as e:
            return self._err(str(e))
