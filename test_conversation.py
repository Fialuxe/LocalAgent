"""会話テスト: fragment opener + multi-turn。"""
import asyncio
import sys

# Windowsエンコーディング設定はここで行わない（asyncio.run後に閉じてしまうため）
# 代わりにPYTHONIOENCODING=utf-8 で実行する

from services.llm_client import LM_STUDIO, LLMClient
from services.fragment_generator import FragmentGenerator


async def main() -> None:
    llm = LLMClient(LM_STUDIO)
    gen = FragmentGenerator(llm)

    # 今日のトレンドトピックで fragment 生成
    topics = ["シートベルト", "海上ヒッチハイク", "IPv6普及50%超え"]
    print("=== Fragment 品質確認 ===")
    fragments = []
    for topic in topics:
        f = await gen.generate_fragment(topic)
        print(f"[{topic}]:\n  {f}\n")
        if f:
            fragments.append({"topic": topic, "text": f})

    if not fragments:
        print("fragment 生成失敗")
        return

    # 最初の fragment を opener として multi-turn テスト
    opener = fragments[0]["text"]
    print("=== 会話テスト ===")
    print(f"Agent: {opener}\n")

    from example_usage import CHARACTER_SYSTEM, _ENERGY_LEVELS
    char_context = f"（今日考えてたこと）\n{opener}"
    system_prompt = CHARACTER_SYSTEM + f"\n\n{char_context}"

    history = [
        {"role": "user", "content": "（開いた）"},
        {"role": "assistant", "content": opener},
    ]

    test_msgs = [
        "それってどんな感じなんだろう？",
        "そうなんだ。ほかにも気になったことある？",
        "すごいね"
    ]

    for user_msg in test_msgs:
        print(f"あなた: {user_msg}")
        r = await llm.chat(
            user=user_msg,
            system=system_prompt,
            history=history,
            max_tokens=1024,
        )
        print(f"Agent: {r}\n")
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": r})


asyncio.run(main())
