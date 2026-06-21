import asyncio
import threading
from typing import Literal

from .base import BaseProvider
from .models import ProviderResult, TrendData, TrendItem

_REGION_TO_PN = {
    "JP": "japan",
    "KR": "south_korea",
}
_REGION_TO_HL = {
    "JP": "ja-JP",
    "KR": "ko-KR",
}

# urllib3 v2 互換パッチ（一度だけ、スレッドセーフに適用）
_urllib3_patched = False
_urllib3_patch_lock = threading.Lock()


def _apply_urllib3_compat() -> None:
    """urllib3 v2 で method_whitelist → allowed_methods に改名された互換パッチ。"""
    global _urllib3_patched
    if _urllib3_patched:
        return
    with _urllib3_patch_lock:
        if _urllib3_patched:
            return
        try:
            import urllib3.util.retry as _r
            _orig = _r.Retry.__init__
            def _patched(self, *args, **kw):
                if "method_whitelist" in kw and "allowed_methods" not in kw:
                    kw["allowed_methods"] = kw.pop("method_whitelist")
                elif "method_whitelist" in kw:
                    kw.pop("method_whitelist")
                _orig(self, *args, **kw)
            _r.Retry.__init__ = _patched
            _urllib3_patched = True
        except ImportError:
            pass
        except Exception:
            pass


class TrendsProvider(BaseProvider):
    """
    Google Trends（pytrends）経由のトレンドプロバイダ。
    JP（日本）と KR（韓国）に対応。

    注意: pytrends はレート制限があるため TTL を長めに設定（1時間）。
    取得失敗時は空リストではなくエラー結果を返し、60秒後に再試行する。

    Args:
        region: "JP" または "KR"
        top_n:  取得するトレンド件数（最大20）
    """

    default_ttl = 3600  # 1時間

    def __init__(self, region: Literal["JP", "KR"] = "JP", top_n: int = 10) -> None:
        if region not in _REGION_TO_PN:
            raise ValueError(f"region must be 'JP' or 'KR', got '{region}'")
        self.region = region
        self.top_n = min(top_n, 20)
        self.name = f"trends_{region.lower()}"

    async def fetch(self) -> ProviderResult:
        try:
            return await asyncio.to_thread(self._sync_fetch)
        except Exception as e:
            return self._err(str(e))

    def _sync_fetch(self) -> ProviderResult:
        try:
            from pytrends.request import TrendReq
        except ImportError:
            return self._err("pytrends がインストールされていません: pip install pytrends")

        _apply_urllib3_compat()

        hl = _REGION_TO_HL[self.region]
        pn = _REGION_TO_PN[self.region]

        try:
            pytrends = TrendReq(
                hl=hl,
                tz=540,             # JST / KST ともに UTC+9
                retries=2,
                backoff_factor=0.5,
                timeout=(5, 20),
            )
            df = pytrends.trending_searches(pn=pn)
            keywords: list[str] = df[0].tolist()[: self.top_n]
        except Exception as e:
            # TooManyRequestsError など
            return self._err(f"Google Trends 取得失敗: {e}")

        items = [TrendItem(rank=i + 1, keyword=str(kw)) for i, kw in enumerate(keywords)]
        return self._ok(TrendData(region=self.region, items=items))
