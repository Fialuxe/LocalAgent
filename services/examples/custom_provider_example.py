"""
カスタムプロバイダの追加例。

新しい情報源（RSS、株価、為替、ニュースAPI等）を追加するには
BaseProvider を継承して fetch() を実装するだけ。
"""

import asyncio
import httpx
from pydantic import BaseModel

from services.base import BaseProvider
from services.models import ProviderResult
from services import InfoAggregator, WeatherProvider


# ─── 例1: 為替レート（ExchangeRate-API 無料版）─────────────────────────────

class ForexData(BaseModel):
    base: str
    rates: dict[str, float]


class ForexProvider(BaseProvider):
    """USD/JPY, USD/KRW などの為替レートを取得する。APIキー不要。"""

    name = "forex"
    default_ttl = 3600  # 1時間

    def __init__(self, base: str = "USD", targets: list[str] | None = None) -> None:
        self.base = base
        self.targets = targets or ["JPY", "KRW", "EUR"]

    async def fetch(self) -> ProviderResult:
        url = f"https://open.er-api.com/v6/latest/{self.base}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                raw = resp.json()
            all_rates: dict = raw.get("rates", {})
            rates = {k: round(v, 4) for k, v in all_rates.items() if k in self.targets}
            return self._ok(ForexData(base=self.base, rates=rates))
        except Exception as e:
            return self._err(str(e))


# ─── 例2: シンプルなテキストメモプロバイダ（ローカルファイル）───────────────

class MemoData(BaseModel):
    text: str


class DailyMemoProvider(BaseProvider):
    """ローカルの memo.txt を読み込んで LLM に渡す。"""

    name = "daily_memo"
    default_ttl = 300

    def __init__(self, file_path: str = "memo.txt") -> None:
        self.file_path = file_path

    async def fetch(self) -> ProviderResult:
        try:
            import aiofiles
            async with aiofiles.open(self.file_path, encoding="utf-8") as f:
                text = await f.read()
            return self._ok(MemoData(text=text.strip()))
        except FileNotFoundError:
            return self._err(f"{self.file_path} が見つかりません")
        except Exception as e:
            return self._err(str(e))


# ─── アグリゲータへの追加 ────────────────────────────────────────────────────

async def demo() -> None:
    agg = (
        InfoAggregator()
        .register(WeatherProvider())
        .register(ForexProvider(base="USD", targets=["JPY", "KRW"]))
        # .register(DailyMemoProvider())  # memo.txt があれば有効化
    )

    context = await agg.format_for_llm()
    print(context)


if __name__ == "__main__":
    asyncio.run(demo())
