from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Dict, List

from .base import BaseProvider
from .cache import AsyncTTLCache
from .models import (
    CalendarData,
    HackerNewsData,
    HolidayData,
    NewsData,
    ProviderResult,
    SystemStatusData,
    TimeContextData,
    TrendData,
    WeatherData,
)

if TYPE_CHECKING:
    from .llm_enricher import LLMEnricher

logger = logging.getLogger(__name__)


class InfoAggregator:
    """
    複数プロバイダをまとめ、LLM に渡せるコンテキスト文字列を生成する。

    使い方:
        agg = InfoAggregator()
        agg.register(WeatherProvider()).register(TimeContextProvider())
        context = await agg.format_for_llm()
    """

    def __init__(self, enricher: LLMEnricher | None = None) -> None:
        self._providers: List[BaseProvider] = []
        self._cache = AsyncTTLCache()
        self._enricher = enricher

    def register(self, provider: BaseProvider) -> "InfoAggregator":
        self._providers.append(provider)
        return self

    # ── データ取得 ────────────────────────────────────────────────────────────

    async def fetch_all(self, force: bool = False) -> Dict[str, ProviderResult]:
        tasks = [self._fetch_one(p, force) for p in self._providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: Dict[str, ProviderResult] = {}
        for provider, result in zip(self._providers, results):
            if isinstance(result, ProviderResult):
                output[provider.name] = result
            else:
                logger.error("[%s] unexpected exception: %s", provider.name, result)
                output[provider.name] = ProviderResult(
                    provider=provider.name,
                    error="内部エラー",
                    ttl_seconds=60,
                )
        return output

    async def fetch_one(self, provider_name: str, force: bool = False) -> ProviderResult | None:
        for p in self._providers:
            if p.name == provider_name:
                return await self._fetch_one(p, force)
        return None

    async def _fetch_one(self, provider: BaseProvider, force: bool) -> ProviderResult:
        key = f"provider:{provider.name}"
        if not force:
            # TTL はエントリに格納済みのため fallback_ttl は不要
            cached = await self._cache.get(key)
            if cached is not None:
                return cached
        result = await provider.fetch()
        if result.error:
            # エラー詳細はログのみ（LLMコンテキストには出さない）
            logger.warning("[%s] fetch error: %s", provider.name, result.error)
        # エラー結果も result.ttl_seconds（60秒）でキャッシュ → バックオフが効く
        await self._cache.set(key, result, ttl_seconds=result.ttl_seconds)
        return result

    async def invalidate(self, provider_name: str) -> None:
        await self._cache.invalidate(f"provider:{provider_name}")

    async def invalidate_all(self) -> None:
        await self._cache.clear()

    # ── LLM フォーマット ───────────────────────────────────────────────────────

    async def format_for_llm(self, force: bool = False) -> str:
        """
        Gemma（またはその他LLM）のシステムプロンプトに埋め込む
        自然言語コンテキストブロックを生成する。

        セキュリティ: エラー詳細はログにのみ出力し、LLMには「取得できませんでした」のみ伝える。
        """
        results = await self.fetch_all(force=force)
        lines: list[str] = []

        for name, result in results.items():
            if result.error:
                # エラーの詳細はLLMに渡さない
                lines.append(f"⚠️ {name}: 一時的に情報を取得できませんでした")
                continue

            d = result.data
            block = _render(name, d)
            if block:
                lines.append(block)

        base = "\n".join(lines)

        if self._enricher:
            enriched = await self._enricher.enrich(results)
            if enriched:
                return base + enriched
        return base

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]


def _render(name: str, d: object) -> str:
    """各データ型をLLM向けの自然言語ブロックに変換する。"""

    if isinstance(d, TimeContextData):
        return (
            f"📅 現在: {d.date_ja} {d.time_str}（{d.period_ja}）\n"
            f"   {d.comment}"
        )

    if isinstance(d, HolidayData):
        if d.is_holiday and d.holiday_name:
            region = "日本" if d.region == "JP" else "韓国"
            return f"🎌 今日は{region}の祝日です: {d.holiday_name}"
        return ""  # 祝日でない場合は何も出さない

    if isinstance(d, WeatherData):
        c = d.current
        lines = [
            f"🌤 天気（{d.location}）: {c.condition_ja}、{c.temperature}°C（体感 {c.feels_like}°C）",
            f"   湿度 {c.humidity}%、風速 {c.wind_speed} m/s",
        ]
        if d.hourly:
            snippet = "  ".join(
                f"{h.time} {h.temperature}°C" for h in d.hourly[::3][:5]
            )
            lines.append(f"   時間別 → {snippet}")
        return "\n".join(lines)

    if isinstance(d, SystemStatusData):
        parts = [f"CPU {d.cpu_percent}%", f"メモリ {d.memory_percent}%"]
        if d.battery_percent is not None:
            status = "充電中" if d.is_charging is True else "バッテリー"
            parts.append(f"{status} {d.battery_percent}%")
        return f"💻 システム: {' / '.join(parts)}"

    if isinstance(d, TrendData):
        flag = "🇯🇵" if d.region == "JP" else "🇰🇷"
        items = "、".join(item.keyword for item in d.items)
        return f"{flag} {d.region} トレンド: {items}"

    if isinstance(d, NewsData):
        flag  = "🇯🇵" if d.region == "JP" else ("🇰🇷" if d.region == "KR" else "🌐")
        label = {"JP": "日本のニュース", "KR": "韓国のニュース"}.get(d.region, "ニュース")
        items = "、".join(item.title for item in d.items)
        return f"📰 {flag} {label}: {items}"

    if isinstance(d, HackerNewsData):
        items = "、".join(f'「{item.title}」' for item in d.items[:3])
        return f"🔥 HN 注目記事: {items}"

    if isinstance(d, CalendarData):
        if not d.events:
            return "📅 予定: なし"
        lines = [f"📅 予定（今後 {d.fetch_range_days} 日間）"]
        for ev in d.events:
            t_str = "終日" if ev.is_all_day else ev.start.astimezone().strftime("%H:%M")
            loc = f" @{ev.location}" if ev.location else ""
            lines.append(f"   • {t_str} {ev.title}{loc}")
        return "\n".join(lines)

    # カスタムプロバイダ: data を str 変換（200文字で切る）
    text = str(d)[:200]
    return f"📦 {name}: {text}"
