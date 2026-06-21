from .aggregator import InfoAggregator
from .base import BaseProvider
from .calendar_provider import GoogleCalendarProvider
from .config import APIConfig
from .google_trends_rss import GoogleTrendsRSSProvider
from .hacker_news import HackerNewsProvider
from .holidays import HolidayProvider
from .llm_client import LLAMACPP, LM_STUDIO, LLMClient, LLMConfig
from .llm_enricher import LLMEnricher
from .models import (
    CalendarData,
    CalendarEvent,
    HackerNewsData,
    HNItem,
    HolidayData,
    NewsData,
    NewsItem,
    ProviderResult,
    SystemStatusData,
    TimeContextData,
    TrendData,
    TrendItem,
    WeatherData,
    YahooJapanNewsData,  # 後方互換エイリアス
)
from .naver_news import NaverNewsProvider
from .newsapi_provider import NewsAPIProvider
from .fragment_generator import FragmentGenerator
from .preference_store import PreferenceStore
from .scheduler import ContextScheduler
from .system_status import SystemStatusProvider
from .time_context import TimeContextProvider
from .trends import TrendsProvider
from .weather import WeatherProvider
from .yahoo_japan_news import YahooJapanNewsProvider

__all__ = [
    # コアクラス
    "InfoAggregator",
    "BaseProvider",
    "ContextScheduler",
    "FragmentGenerator",
    "PreferenceStore",
    # LLM
    "LLMClient",
    "LLMConfig",
    "LLMEnricher",
    "LM_STUDIO",
    "LLAMACPP",
    # 設定
    "APIConfig",
    # プロバイダ（APIキー不要）
    "WeatherProvider",
    "TimeContextProvider",
    "SystemStatusProvider",
    "HolidayProvider",
    "HackerNewsProvider",
    "YahooJapanNewsProvider",
    "GoogleTrendsRSSProvider",   # pytrends より安定したトレンド取得
    "TrendsProvider",            # pytrends（不安定だがバックアップとして残す）
    # プロバイダ（APIキーあり）
    "NaverNewsProvider",
    "NewsAPIProvider",
    "GoogleCalendarProvider",
    # データモデル
    "ProviderResult",
    "WeatherData",
    "TrendData",
    "TrendItem",
    "CalendarData",
    "CalendarEvent",
    "TimeContextData",
    "SystemStatusData",
    "HolidayData",
    "HackerNewsData",
    "HNItem",
    "NewsData",
    "NewsItem",
    "YahooJapanNewsData",
]
