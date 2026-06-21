"""実際の FragmentGenerator + CHARACTER_SYSTEM 動作確認。"""
import asyncio
import io
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from services.llm_client import LM_STUDIO, LLMClient
from services.fragment_generator import FragmentGenerator


async def main() -> None:
    llm = LLMClient(LM_STUDIO)
    gen = FragmentGenerator(llm)

    topics = [
        "APL製3Dゲームエンジン",
        "ジャングリア口コミ回復",
        "IPv6普及率50%",
        "フォーエバーヤング",
    ]

    print("=== Fragment 生成テスト ===")
    for topic in topics:
        fragment = await gen.generate_fragment(topic)
        print(f"[{topic}]:\n  → {fragment}\n")

asyncio.run(main())
