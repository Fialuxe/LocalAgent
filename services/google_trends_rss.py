"""
Google Trends RSS プロバイダ。

pytrends の安定版代替。同じデータソース（Google Trends）を
JavaScript重いページではなくRSSエンドポイント経由で取得するため、
レート制限・Bot検出に引っかかりにくい。

APIキー不要・無料。

エンドポイント（2025年後半以降の新URL）:
  日本: https://trends.google.com/trending/rss?geo=JP
  韓国: https://trends.google.com/trending/rss?geo=KR

  旧URL（404になる場合あり）:
  https://trends.google.com/trends/trendingsearches/daily/rss?geo=JP

返却データ形式:
  TrendData（既存の TrendsProvider と同じ型）→ LLMEnricher がそのまま解釈できる。
"""

import xml.etree.ElementTree as ET
from typing import Literal

import httpx

from .base import BaseProvider
from .models import ProviderResult, TrendData, TrendItem

# 新URL（2025年後半から）→ 旧URL（フォールバック）の順で試す
_RSS_URLS = [
    "https://trends.google.com/trending/rss",
    "https://trends.google.com/trends/trendingsearches/daily/rss",
]

# Google Trends が使う名前空間（新旧どちらのURLでも同じ）
_NS = {"ht": "https://trends.google.com/trends/trendingsearches/daily"}


class GoogleTrendsRSSProvider(BaseProvider):
    """
    Google Trends の RSS エンドポイントからトレンドを取得する。

    pytrends より安定した代替実装。返す型は TrendData で同一なので
    LLMEnricher の cross_regional_insight がそのまま使える。

    Args:
        region: "JP"（日本）または "KR"（韓国）
        top_n:  取得するトレンド件数
    """

    default_ttl = 3600  # 1時間（Daily Trends は1日単位で更新）

    def __init__(self, region: Literal["JP", "KR"] = "JP", top_n: int = 10) -> None:
        self.region = region
        self.top_n  = top_n
        self.name   = f"google_trends_rss_{region.lower()}"

    async def fetch(self) -> ProviderResult:
        params = {"geo": self.region}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ja-JP,ja;q=0.9" if self.region == "JP" else "ko-KR,ko;q=0.9",
        }
        last_err: Exception = Exception(f"URL リストが空です (region={self.region})")
        async with httpx.AsyncClient(
            timeout=10.0,
            verify=True,
            follow_redirects=True,
        ) as client:
            for base_url in _RSS_URLS:
                try:
                    resp = await client.get(base_url, params=params, headers=headers)
                    resp.raise_for_status()
                    items = _parse_trends_rss(resp.text, self.top_n)
                    return self._ok(TrendData(region=self.region, items=items))
                except Exception as e:
                    last_err = e
                    continue

        return self._err(str(last_err))


def _parse_trends_rss(xml_text: str, top_n: int) -> list[TrendItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"RSS parse error: {e}") from e

    items: list[TrendItem] = []
    for rank, item_el in enumerate(root.iter("item"), 1):
        title_el = item_el.find("title")
        if title_el is None or not title_el.text:
            continue

        # 検索トラフィック量（任意）
        traffic_el = item_el.find("ht:approx_traffic", _NS)
        traffic    = traffic_el.text if traffic_el is not None else None

        keyword = title_el.text.strip()
        if traffic:
            # "200,000+" のような文字列をそのまま keyword に付加してリッチにする
            keyword = f"{keyword}（{traffic}）"

        items.append(TrendItem(rank=rank, keyword=keyword))
        if len(items) >= top_n:
            break

    return items
