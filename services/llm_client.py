"""
ローカルLLMクライアント — OpenAI互換APIラッパー。

対応バックエンド:
  llama.cpp server: llama-server -m model.gguf --port 8080
  LM Studio:        GUI → Local Server → Start (port 1234)

どちらも /v1/chat/completions を OpenAI 互換で公開するため、
base_url を切り替えるだけで動く。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator

from openai import AsyncOpenAI


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:1234/v1"   # LM Studio デフォルト
    model: str = "local-model"                   # LM Studio はここを無視してロード済みモデルを使う
    api_key: str = "not-needed"                  # ローカル実行はキー不要（ダミー値でOK）
    temperature: float = 0.8
    max_tokens: int = 512
    extra: dict = field(default_factory=dict)


# バックエンド別プリセット
LLAMACPP = LLMConfig(base_url="http://localhost:8080/v1", model="local")
LM_STUDIO = LLMConfig(base_url="http://localhost:1234/v1", model="local-model")


class LLMClient:
    """
    llama.cpp / LM Studio 向け非同期LLMクライアント。

    使い方:
        client = LLMClient(LM_STUDIO)
        # または
        client = LLMClient(LLAMACPP)

        # 通常呼び出し
        text = await client.chat(system="...", user="...")

        # ストリーミング
        async for chunk in client.stream(system="...", user="..."):
            print(chunk, end="", flush=True)
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._cfg = config or LM_STUDIO
        self._client = AsyncOpenAI(
            base_url=self._cfg.base_url,
            api_key=self._cfg.api_key,
        )

    async def aclose(self) -> None:
        """コネクションプールを解放する。"""
        await self._client.close()

    async def chat(
        self,
        user: str,
        system: str = "",
        history: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        messages = _build_messages(system, history, user)
        try:
            resp = await self._client.chat.completions.create(
                model=self._cfg.model,
                messages=messages,
                temperature=temperature if temperature is not None else self._cfg.temperature,
                max_tokens=max_tokens if max_tokens is not None else self._cfg.max_tokens,
                **self._cfg.extra,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            raise RuntimeError(
                f"LLM呼び出し失敗 ({self._cfg.base_url}): {e}"
            ) from e

    async def stream(
        self,
        user: str,
        system: str = "",
        history: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        messages = _build_messages(system, history, user)
        try:
            response = await self._client.chat.completions.create(
                model=self._cfg.model,
                messages=messages,
                temperature=self._cfg.temperature,
                max_tokens=self._cfg.max_tokens,
                stream=True,
                **self._cfg.extra,
            )
        except Exception as e:
            raise RuntimeError(
                f"LLMストリーム初期化失敗 ({self._cfg.base_url}): {e}"
            ) from e
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


def _build_messages(
    system: str,
    history: list[dict] | None,
    user: str,
) -> list[dict]:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user})
    return messages
