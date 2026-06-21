import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


class AsyncTTLCache:
    """
    インメモリTTLキャッシュ。スレッドセーフ（asyncio.Lock）。

    各エントリは set() 時に ttl_seconds を個別保持するため、
    エラー結果（60秒）と通常結果（プロバイダ毎）が混在しても正しく期限切れになる。
    """

    def __init__(self) -> None:
        self._store: Dict[str, Tuple[Any, datetime, int]] = {}
        self.__lock: Optional[asyncio.Lock] = None

    @property
    def _lock(self) -> asyncio.Lock:
        # イベントループ内で初めてアクセスされた時点で生成（Python 3.10+ 対応）
        if self.__lock is None:
            self.__lock = asyncio.Lock()
        return self.__lock

    async def get(self, key: str, fallback_ttl: int = 0) -> Optional[Any]:
        """
        エントリを返す。保存時TTL（> 0）があればそれを使い、
        なければ fallback_ttl を使う。期限切れは削除してNoneを返す。
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, stored_at, entry_ttl = entry
            ttl = entry_ttl if entry_ttl > 0 else fallback_ttl
            if ttl > 0 and (datetime.now() - stored_at).total_seconds() > ttl:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 0) -> None:
        async with self._lock:
            self._store[key] = (value, datetime.now(), ttl_seconds)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def keys(self) -> list[str]:
        async with self._lock:
            return list(self._store.keys())

    async def evict_expired(self) -> int:
        """期限切れエントリを掃除し、削除件数を返す（定期メンテナンス用）。"""
        now = datetime.now()
        async with self._lock:
            stale = [
                k for k, (_, stored_at, ttl) in self._store.items()
                if ttl > 0 and (now - stored_at).total_seconds() > ttl
            ]
            for k in stale:
                del self._store[k]
            return len(stale)
