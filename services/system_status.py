import asyncio

from .base import BaseProvider
from .models import ProviderResult, SystemStatusData


class SystemStatusProvider(BaseProvider):
    """
    psutil でローカルシステム状態を取得する。APIなし・外部通信なし。

    取得内容: CPU使用率 / メモリ使用率 / バッテリー残量・充電状態
    これにより「さっきからCPUが高いですね」といった作業文脈に即した発話が可能になる。
    """

    name = "system_status"
    default_ttl = 60  # 1分

    async def fetch(self) -> ProviderResult:
        return await asyncio.to_thread(self._sync_fetch)

    def _sync_fetch(self) -> ProviderResult:
        try:
            import psutil
        except ImportError:
            return self._err("psutil未インストール: pip install psutil")

        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent

        battery = psutil.sensors_battery()
        bat_pct     = round(battery.percent, 1) if battery else None
        is_charging = battery.power_plugged      if battery else None

        return self._ok(SystemStatusData(
            cpu_percent=round(cpu, 1),
            memory_percent=round(mem, 1),
            battery_percent=bat_pct,
            is_charging=is_charging,
        ))
