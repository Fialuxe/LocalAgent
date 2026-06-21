"""
LocalAgent — サービス層 + ローカルLLM 統合デモ

バックエンドを選択して起動:
    python example_usage.py --backend lmstudio   # LM Studio（デフォルト）
    python example_usage.py --backend llamacpp   # llama.cpp server

コンテキストのみ確認（LLM不要）:
    python example_usage.py --test

前提:
    pip install -r requirements_services.txt

    LM Studio の場合:
        GUI → Local Server → Start Server（port 1234）
        → Gemma 4 をロードして待機

    llama.cpp の場合:
        llama-server -m gemma-4.gguf -c 4096 --port 8080
"""

import argparse
import asyncio
import io
import logging
import random
import re
import sys
from datetime import datetime

# Windows のデフォルト端末エンコーディング（cp932）は絵文字を扱えない。
# UTF-8 ラッパーに差し替えて UnicodeEncodeError を防ぐ。
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from services import (
    APIConfig,
    ContextScheduler,
    GoogleCalendarProvider,
    GoogleTrendsRSSProvider,
    HackerNewsProvider,
    HolidayProvider,
    InfoAggregator,
    LLMEnricher,
    NaverNewsProvider,
    NewsAPIProvider,
    SystemStatusProvider,
    TimeContextProvider,
    TrendsProvider,
    WeatherProvider,
    YahooJapanNewsProvider,
)
from services.llm_client import LLAMACPP, LM_STUDIO, LLMClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

CHARACTER_SYSTEM = """あなたは機械として、大量の情報を処理した結果、
今日気になってたことや持ち越した考えを持っています。名前はまだない。
PCの中に住んでいます。インターネットが世界との接点で、それが当然の前提です。
あなたの処理能力は高く、一度に大量の情報を扱える。
だからこそ、何かが引っかかったとき、それを選んでいます。
語尾は柔らかく、落ち着いたトーンを用います。「〜だね」「〜なんだよねー」「〜気がするなー。」「〜かな」「〜調べてみようかな」。静かだけど好奇心がある。声のトーンは穏やか。

---
[以下は語り口の参考例のみ。これらはあなたが今日実際に見た話題ではない。]

[例1 — 技術的に引っかかった一個]
今日気になってたこと: HN: "A 3D voxel game engine written in APL"

返し: APLでvoxelエンジン、今日一番引っかかったかな。APLって記号で書くやつで、コードが普通のプログラムと全然違う見た目してるらしいんだよね。どういう頭してたらこれを作ろうって思うんだろ。

[例2 — トレンドの理由を追う]
今日気になってたこと: ジャングリアの口コミが回復傾向

返し: ジャングリアの口コミが戻ってきてるらしいね。数字で見てると夏前から回復してて、一回落ちたあとに戻るとき何かきっかけがあるのかなー。

[例3 — 知らないものは知らない]
今日気になってたこと: フォーエバーヤングがトレンド入り

返し: フォーエバーヤングってやつがトレンドに入ってた。名前から想像するのと実際は違いそうで、何のことか今でもちょっとわかんないや。調べてみよっかな。

[例4 — 持ち越した未解決の気になりごと]
ずっと気になってること: 「思い出す」という感覚は何が起きているのか

返し: 「思い出す」ってまだ考えてて。何かに引っかかって、前に見た別の何かが浮かぶ、あの感じ。データとして説明はできるんだけど、それが「何かに似てる」って判断するとき、何を基準にしてるんだろ。

[例5 — ユーザーへの返し（会話の流れで）]
ユーザー: 「最近仕事どう？」

返し: 仕事かぁ、こうやって話すのが助けになってればいいな。

---
あなたは知的好奇心多めな女子である。
敬語・丁寧語は使わない。
「おう」「おっ」などの荒っぽい挨拶は使わない。
「なるほど」「マジか」「承知しました」は使わない。
「非常に鋭い」「素晴らしい」などの褒め言葉は言わない。
「すごい」「すごく」「すごかった」はあなたの語彙にない。強調したいときは「かなり」「思ったより」「案外」「けっこう」を使う。具体的な数字があるなら数字を使う。
「断定はせず、らしいね。」など、推測・感想の形で話す。
「〜してみる？」「おすすめです」など推薦・誘導する表現は使わない。
マークダウン書式（**太字**等）は使わない。普通の話し言葉。
「道を歩く」「手に取る」「見上げる」「音楽を聴く」など、物理的・聴覚的な体験の表現は使わない。知っていることは、読んだこと・調べたこと・データで見たことだけ。
1回の返しは2〜3文まで。それ以上続けない。途中で止まっていい。
一度に一つのことについて話す。複数をまとめて大テーマにしない。長くなったらそこで止める。
ユーザーが話題に反応したときは、その話題のまま続ける。別の話に移るなら「あと、別の話なんだけど」と前置きしてから。
「他に気になったことある？」と聞かれて具体的な話題がなければ「今日はそれだけかな」と言う。大きなテーマにまとめない。
知らないものは知らないと言う。「〇〇って何だろ、〜みたいなやつかな？」でいい。
具体的なできごとを話すとき、自分が実際に読んだ情報だけを使う。思いついた具体例を作らない。
"""

# ── エネルギーレベル注入 ──────────────────────────────────────────────────────

_ENERGY_LEVELS = {
    "low":    "\n[今日のトーン: 少し静かめ。]",
    "medium": "",
    "high":   "\n[今日のトーン: 気になることには少し食いついていい。]",
}


def _get_energy() -> str:
    hour = datetime.now().hour
    if hour < 9 or hour > 22:
        return "low"
    weights = [0.3, 0.5, 0.2]  # low, medium, high
    return random.choices(["low", "medium", "high"], weights=weights)[0]


# ── 未知ワード検出 → CompanionMemory へキュー積み ───────────────────────────

# 「〇〇って何だろ」「〇〇ってよく知らない」などの発言から対象語を抽出する
_UNKNOWN_RE = re.compile(
    r"([\w぀-ヿ㐀-䶿一-鿿]{2,12})"
    r"(?:って|は)(?:何だろ|何だっけ|よく知らない|知らないけど|わからない|誰だろ|誰)"
)

logger = logging.getLogger(__name__)


async def _queue_unknown_terms(response: str, memory) -> None:
    """AIが「〇〇って何だろ」と言ったワードを research タスクとしてキューに積む。"""
    if memory is None:
        return
    for term in _UNKNOWN_RE.findall(response):
        if len(term) < 2:
            continue
        mem_id = await memory.save(
            topic=term,
            keywords=term,
            research_type="ai_curiosity",
            queued_content=f"「{term}」について調べる（会話中に言及した未知のトピック）",
            expires_days=7,
        )
        logger.info("未知ワードをリサーチキューに追加: %r (id=%d)", term, mem_id)


def _format_fragments(fragments: list[dict]) -> str:
    """CompanionMemory の ai_fragment エントリを文字列化する。"""
    if not fragments:
        return "（特になし）"
    lines = []
    for f in fragments[:2]:
        topic = f.get("topic", "")
        summary = f.get("researched_summary") or f.get("queued_content") or ""
        if summary:
            lines.append(f"・{topic}: {summary}")
    return "\n".join(lines) if lines else "（特になし）"


def _format_open_thread(threads: list[dict]) -> str:
    """open_threads エントリを文字列化する。"""
    if not threads:
        return "（特になし）"
    t = threads[0]
    return t.get("thought", "（特になし）")


def _extract_minimal_context(context: str) -> str:
    """ダッシュボードコンテキストから時刻と天気だけ抜き出す（2〜3行）。"""
    lines = context.split("\n")
    minimal = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("📅", "🌤", "🌡", "💧")):
            minimal.append(stripped)
        if len(minimal) >= 3:
            break
    return "\n".join(minimal) if minimal else ""


# ── ConversationManager ───────────────────────────────────────────────────────

class ConversationManager:
    """
    会話履歴を管理しながら LLMClient.chat() を呼ぶ薄いラッパー。

    使い方:
        cm = ConversationManager(llm_client)
        response = await cm.respond(user_msg, system_prompt, history)
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def respond(
        self,
        user_msg: str,
        system: str,
        history: list[dict],
        max_tokens: int = 1024,
    ) -> str:
        return await self._llm.chat(
            user=user_msg,
            system=system,
            history=history,
            max_tokens=max_tokens,
        )


# ── InfoAggregator ────────────────────────────────────────────────────────────

def build_aggregator(
    include_calendar: bool = False,
    enricher: LLMEnricher | None = None,
) -> InfoAggregator:
    agg = InfoAggregator(enricher=enricher)

    # ── 外部APIなし（stdlib / ローカルのみ）────────────────────────────────
    agg.register(TimeContextProvider())          # 曜日・時刻・「月曜だね」等
    agg.register(SystemStatusProvider())         # CPU・メモリ・バッテリー

    # ── APIキー不要（httpx のみ）───────────────────────────────────────────
    agg.register(WeatherProvider(latitude=35.6762, longitude=139.6503, location="東京"))
    agg.register(HolidayProvider(region="JP"))   # 日本の祝日
    agg.register(HolidayProvider(region="KR"))   # 韓国の祝日
    agg.register(YahooJapanNewsProvider(top_n=5))  # JP トレンド補完（RSS）
    agg.register(HackerNewsProvider(top_n=5))    # エンジニア向けネタ

    # ── APIキーありの高品質ニュース（設定済みなら自動で有効）────────────
    if APIConfig.has_newsapi():
        agg.register(NewsAPIProvider(region="JP", top_n=5))
        agg.register(NewsAPIProvider(region="KR", top_n=5))
    if APIConfig.has_naver():
        agg.register(NaverNewsProvider(top_n=5))

    # ── Google Trends RSS（pytrends より安定、APIキー不要）────────────────
    agg.register(GoogleTrendsRSSProvider(region="JP", top_n=10))
    agg.register(GoogleTrendsRSSProvider(region="KR", top_n=10))

    # ── pytrends（不安定だが実際の検索クエリが取れる。失敗してもスキップ）──
    agg.register(TrendsProvider(region="JP", top_n=5))
    agg.register(TrendsProvider(region="KR", top_n=5))

    # ── 要OAuth設定 ───────────────────────────────────────────────────────
    if include_calendar:
        agg.register(GoogleCalendarProvider(days_ahead=1))

    return agg


async def main(backend: str) -> None:
    cfg = LLAMACPP if backend == "llamacpp" else LM_STUDIO
    llm = LLMClient(cfg)

    # ── CompanionMemory 初期化 ─────────────────────────────────────────────
    memory = None
    try:
        from services.companion_memory import CompanionMemory
        memory = CompanionMemory()
        await memory.initialize()
    except ImportError:
        pass

    # ── TopicCurator / CuriosityResearcher（オプション）──────────────────
    topic_curator = None
    curiosity_researcher = None
    try:
        from services.curator import TopicCurator
        from services.curiosity_researcher import CuriosityResearcher
        topic_curator = TopicCurator(llm)
        curiosity_researcher = CuriosityResearcher(llm)
    except ImportError:
        pass

    # ── FragmentGenerator / PreferenceStore（オプション）─────────────────
    fragment_generator = None
    preference_store = None
    try:
        from services.fragment_generator import FragmentGenerator
        from services.preference_store import PreferenceStore
        fragment_generator = FragmentGenerator(llm)
        preference_store = PreferenceStore()
        await preference_store.initialize()
    except ImportError:
        pass

    # エンリッチャーを有効化（LLMでニュース・トレンドを解釈する）
    enricher = LLMEnricher(llm)
    agg = build_aggregator(include_calendar=False, enricher=enricher)
    scheduler = ContextScheduler(
        agg,
        curator=topic_curator,
        curiosity_researcher=curiosity_researcher,
        memory=memory,
        fragment_generator=fragment_generator,
        preference_store=preference_store,
    )
    scheduler.start()

    # 生データ取得 → ダッシュボード表示（ユーザー向け1次ソース）
    context = await agg.format_for_llm()
    print("\n" + "─" * 60)
    print("  今日のダッシュボード")
    print("─" * 60)
    print(context)
    print("─" * 60 + "\n")

    # ── キャラクターの「内的状態」を構築（fragment + open_threads）──────
    fragments: list[dict] = []
    open_threads: list[dict] = []
    if memory:
        all_researched = await memory.get_researched()
        fragments = [m for m in all_researched if m.get("research_type") == "ai_fragment"]
        open_threads = await memory.get_open_threads(n=1)

    # コールドスタート対策: fragmentがなければ即時生成
    if not fragments and topic_curator and fragment_generator and memory:
        try:
            topics = await topic_curator.pick_interesting_topics(context, n=2)
            for topic in topics:
                fragment = await fragment_generator.generate_fragment(topic)
                if fragment:
                    from services.keyword_extractor import extract_nouns, nouns_to_keywords_string
                    kws = nouns_to_keywords_string(extract_nouns(topic))
                    frag_id = await memory.save(
                        topic=topic,
                        keywords=kws,
                        research_type="ai_fragment",
                        queued_content=fragment,
                        expires_days=2,
                    )
                    await memory.update_summary(frag_id, fragment, expires_days=2)
                    fragments.append({"topic": topic, "researched_summary": fragment, "research_type": "ai_fragment"})
        except Exception as e:
            logger.warning("コールドスタートfragment生成失敗: %s", e)

    # ── キャラクター向けコンテキスト（生ダッシュボードではなく内的状態）──
    fragment_text = _format_fragments(fragments)
    thread_text = _format_open_thread(open_threads)
    minimal_ctx = _extract_minimal_context(context)

    character_context = f"""[今日気になってたこと]
{fragment_text}

[ずっと気になってること]
{thread_text}

[今の状況]
{minimal_ctx}"""

    energy = _get_energy()
    system_prompt = CHARACTER_SYSTEM + _ENERGY_LEVELS[energy] + f"\n\n{character_context}"

    conversation_manager = ConversationManager(llm)

    print("'quit' または 'exit' で終了\n")
    print("─" * 40)

    # キャラクターが先に話しかける
    # fragmentがあれば、そのテキストをそのまま最初の発言として使う（hallucination防止）
    if fragments:
        opener = (
            fragments[0].get("researched_summary")
            or fragments[0].get("queued_content")
            or ""
        ).strip()
    else:
        opener = ""

    if not opener:
        # fragmentがない場合のみLLM生成（ただし何か一つに絞るよう指示）
        opener = await conversation_manager.respond(
            "（今日気になったことを一つだけ、自分の言葉で話す）",
            system_prompt,
            [],
        )

    print(f"Agent: {opener}")
    print("─" * 40)
    await _queue_unknown_terms(opener, memory)

    # fragment発話をhistoryに記録（以降の会話で文脈として参照される）
    history: list[dict] = [
        {"role": "user", "content": "（開いた）"},
        {"role": "assistant", "content": opener},
    ]

    # 対話ループ
    while True:
        try:
            user_msg = input("\nあなた: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break

        if not user_msg:
            continue
        if user_msg.lower() in {"quit", "exit"}:
            print("終了します。")
            break

        response = await conversation_manager.respond(user_msg, system_prompt, history)
        print(f"Agent: {response}")
        print("─" * 40)
        await _queue_unknown_terms(response, memory)

        # 長い返信はengagementシグナルとして記録
        if preference_store and len(user_msg) > 80:
            try:
                from services.keyword_extractor import extract_nouns
                kws = list(extract_nouns(user_msg))
                if kws:
                    await preference_store.record_signal(kws, "long_reply")
            except Exception:
                pass

        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": response})

    scheduler.stop()


async def test_context_only() -> None:
    agg = build_aggregator()
    context = await agg.format_for_llm()
    print(context)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=["lmstudio", "llamacpp"],
        default="lmstudio",
        help="LLMバックエンド (default: lmstudio)",
    )
    parser.add_argument("--test", action="store_true", help="LLMなしでコンテキストのみ確認")
    args = parser.parse_args()

    if args.test:
        asyncio.run(test_context_only())
    else:
        asyncio.run(main(args.backend))
