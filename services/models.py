from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ProviderResult(BaseModel):
    provider: str
    fetched_at: datetime = Field(default_factory=datetime.now)
    ttl_seconds: int = 900
    data: Any = None
    error: Optional[str] = None

    @property
    def is_stale(self) -> bool:
        return (datetime.now() - self.fetched_at).total_seconds() >= self.ttl_seconds


# ── Weather ──────────────────────────────────────────────────────────────────

class WeatherCurrent(BaseModel):
    temperature: float
    feels_like: float
    humidity: int
    wind_speed: float
    condition: str       # English (WMO)
    condition_ja: str    # 日本語


class WeatherHour(BaseModel):
    time: str            # "HH:MM"
    temperature: float
    condition_ja: str


class WeatherData(BaseModel):
    location: str
    latitude: float
    longitude: float
    current: WeatherCurrent
    hourly: List[WeatherHour] = Field(default_factory=list)
    timezone: str = "Asia/Tokyo"


# ── Trends ───────────────────────────────────────────────────────────────────

class TrendItem(BaseModel):
    rank: int
    keyword: str


class TrendData(BaseModel):
    region: str          # "JP" | "KR"
    items: List[TrendItem]


# ── Calendar ─────────────────────────────────────────────────────────────────

class CalendarEvent(BaseModel):
    title: str
    start: datetime
    end: Optional[datetime] = None
    location: Optional[str] = None
    is_all_day: bool = False


class CalendarData(BaseModel):
    events: List[CalendarEvent]
    fetch_range_days: int = 1


# ── 時刻・曜日コンテキスト ─────────────────────────────────────────────────────

class TimeContextData(BaseModel):
    iso: str            # "2026-06-21T14:30"
    date_ja: str        # "2026年6月21日（日）"
    time_str: str       # "14:30"
    day_ja: str         # "日曜日"
    period_ja: str      # "午後"
    comment: str        # "週末ですね" など


# ── システム状態 ──────────────────────────────────────────────────────────────

class SystemStatusData(BaseModel):
    cpu_percent: float
    memory_percent: float
    battery_percent: Optional[float] = None
    is_charging: Optional[bool] = None


# ── 祝日 ─────────────────────────────────────────────────────────────────────

class HolidayData(BaseModel):
    is_holiday: bool
    holiday_name: Optional[str] = None   # 例: "成人の日"（Nager.Date localName）
    region: str                           # "JP" | "KR"


# ── Hacker News ───────────────────────────────────────────────────────────────

class HNItem(BaseModel):
    rank: int
    title: str
    score: int


class HackerNewsData(BaseModel):
    items: List[HNItem]


# ── ニュース（汎用）──────────────────────────────────────────────────────────

class NewsItem(BaseModel):
    rank: int
    title: str


class NewsData(BaseModel):
    """Yahoo Japan RSS / Naver / NewsAPI など複数ソースで共有するニュースモデル。"""
    source: str    # "yahoo_jp" | "naver_kr" | "newsapi_jp" | "newsapi_kr"
    region: str    # "JP" | "KR" | "GLOBAL"
    items: List[NewsItem]


# 後方互換エイリアス（既存コードを壊さないため）
YahooJapanNewsData = NewsData
