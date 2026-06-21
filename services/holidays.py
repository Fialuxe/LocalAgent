from datetime import date as dt_date
from typing import Literal

import httpx

from .base import BaseProvider
from .models import HolidayData, ProviderResult

_BASE = "https://date.nager.at/api/v3/PublicHolidays"


class HolidayProvider(BaseProvider):
    """
    Nager.Date API で日本・韓国の祝日を取得する（APIキー不要・無料）。

    「今日は祝日ですよ」「成人の日ですね」などの発話トリガーになる。
    TTL 24時間で1日1回のみ問い合わせる。

    Args:
        region: "JP"（日本）または "KR"（韓国）
    """

    default_ttl = 86_400  # 24時間

    def __init__(self, region: Literal["JP", "KR"] = "JP") -> None:
        self.region = region
        self.name = f"holiday_{region.lower()}"

    async def fetch(self) -> ProviderResult:
        today = dt_date.today()
        url = f"{_BASE}/{today.year}/{self.region}"
        try:
            async with httpx.AsyncClient(timeout=8.0, verify=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                holidays: list[dict] = resp.json()

            today_str = today.isoformat()
            for h in holidays:
                if h.get("date") == today_str:
                    return self._ok(HolidayData(
                        is_holiday=True,
                        holiday_name=h.get("localName") or h.get("name"),
                        region=self.region,
                    ))
            return self._ok(HolidayData(is_holiday=False, region=self.region))
        except Exception as e:
            return self._err(str(e))
