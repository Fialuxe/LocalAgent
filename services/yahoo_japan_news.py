import xml.etree.ElementTree as ET

import httpx

from .base import BaseProvider
from .models import NewsData, NewsItem, ProviderResult

# Yahoo! Japan トップニュース RSS（APIキー不要・登録不要・安定）
_RSS_URL = "https://news.yahoo.co.jp/rss/topics/top-picks.xml"


class YahooJapanNewsProvider(BaseProvider):
    """
    Yahoo! Japan トップニュース RSS プロバイダ。

    pytrends の代替として日本語トレンドを補完する。
    feedparser 不要 — stdlib の xml.etree + httpx だけで動作。
    TTL 30分（pytrends の1時間より短く設定して鮮度を保つ）。
    """

    name = "yahoo_japan_news"
    default_ttl = 1800  # 30分

    def __init__(self, top_n: int = 5) -> None:
        self.top_n = top_n

    async def fetch(self) -> ProviderResult:
        try:
            async with httpx.AsyncClient(
                timeout=8.0,
                verify=True,
                headers={"User-Agent": "LocalAgent/1.0 (personal desktop app)"},
                follow_redirects=True,
            ) as client:
                resp = await client.get(_RSS_URL)
                resp.raise_for_status()

            root = ET.fromstring(resp.text)
            items: list[NewsItem] = []

            for i, item_el in enumerate(root.iter("item"), 1):
                title_el = item_el.find("title")
                if title_el is not None and title_el.text:
                    items.append(NewsItem(rank=i, title=title_el.text.strip()))
                if len(items) >= self.top_n:
                    break

            return self._ok(NewsData(source="yahoo_jp", region="JP", items=items))
        except Exception as e:
            return self._err(str(e))
