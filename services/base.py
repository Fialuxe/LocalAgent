from abc import ABC, abstractmethod

from .models import ProviderResult


class BaseProvider(ABC):
    """
    全プロバイダの基底クラス。
    新しい情報源を追加するには、このクラスを継承して fetch() を実装するだけ。

    例:
        class MyProvider(BaseProvider):
            name = "my_provider"
            default_ttl = 300

            async def fetch(self) -> ProviderResult:
                data = await some_api_call()
                return self._ok(data)
    """

    name: str = "base"
    default_ttl: int = 900  # seconds

    @abstractmethod
    async def fetch(self) -> ProviderResult: ...

    def _ok(self, data) -> ProviderResult:
        return ProviderResult(provider=self.name, data=data, ttl_seconds=self.default_ttl)

    def _err(self, error: str) -> ProviderResult:
        # エラー時は短いTTLで再試行を早める
        return ProviderResult(provider=self.name, error=error, ttl_seconds=60)
