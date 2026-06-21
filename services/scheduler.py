from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .aggregator import InfoAggregator
from .keyword_extractor import extract_nouns, nouns_to_keywords_string

if TYPE_CHECKING:
    from .curator import TopicCurator
    from .curiosity_researcher import CuriosityResearcher
    from .companion_memory import CompanionMemory
    from .fragment_generator import FragmentGenerator
    from .preference_store import PreferenceStore

logger = logging.getLogger(__name__)


class ContextScheduler:
    """
    登録済みプロバイダをバックグラウンドで自動更新する。

    APScheduler の AsyncIOScheduler に prefetch を one-shot ジョブとして登録することで、
    asyncio.create_task() のイベントループ依存問題を回避している。
    """

    def __init__(
        self,
        aggregator: InfoAggregator,
        curator: TopicCurator | None = None,
        curiosity_researcher: CuriosityResearcher | None = None,
        memory: CompanionMemory | None = None,
        fragment_generator: FragmentGenerator | None = None,
        preference_store: PreferenceStore | None = None,
    ) -> None:
        self._agg = aggregator
        self._curator = curator
        self._curiosity_researcher = curiosity_researcher
        self._memory = memory
        self._fragment_generator = fragment_generator
        self._preference_store = preference_store
        self._scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")

    def start(self) -> None:
        # 起動直後の1回限りの prefetch（APScheduler が loop を管理するため安全）
        self._scheduler.add_job(
            self._prefetch_all,
            trigger="date",   # 即時実行
            id="prefetch_once",
            replace_existing=True,
            max_instances=1,  # 重複起動防止
        )

        # 各プロバイダを TTL の半分の間隔で定期更新
        for provider in self._agg._providers:
            interval = max(provider.default_ttl // 2, 60)
            self._scheduler.add_job(
                self._refresh,
                "interval",
                seconds=interval,
                args=[provider.name],
                id=f"refresh_{provider.name}",
                replace_existing=True,
                max_instances=1,  # 前回ジョブが終わるまで次を起動しない
                coalesce=True,    # 遅延した複数の missed fire を1回にまとめる
            )
            logger.debug("Scheduled %s every %ds", provider.name, interval)

        # Run curiosity research 5 minutes after prefetch
        self._scheduler.add_job(
            self._run_curiosity_research,
            trigger="date",
            run_date=datetime.now() + timedelta(minutes=5),
            id="curiosity_research_once",
            replace_existing=True,
            max_instances=1,
        )
        # Daily curiosity research at 7:05 AM
        self._scheduler.add_job(
            self._run_curiosity_research,
            "cron", hour=7, minute=5,
            id="curiosity_research_daily",
            replace_existing=True, max_instances=1, coalesce=True,
        )
        # Nightly cleanup at 2:00 AM
        self._scheduler.add_job(
            self._cleanup_memory,
            "cron", hour=2, minute=0,
            id="memory_cleanup",
            replace_existing=True, max_instances=1, coalesce=True,
        )
        # Daily preference cleanup at 3:00 AM
        self._scheduler.add_job(
            self._cleanup_preferences,
            "cron", hour=3, minute=0,
            id="preference_cleanup",
            replace_existing=True, max_instances=1, coalesce=True,
        )

        self._scheduler.start()
        logger.info("ContextScheduler started (%d providers)", len(self._agg._providers))

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("ContextScheduler stopped")

    async def _prefetch_all(self) -> None:
        logger.info("Pre-warming context cache...")
        await self._agg.fetch_all(force=True)
        logger.info("Context cache ready.")

    async def _refresh(self, provider_name: str) -> None:
        logger.debug("Refreshing %s...", provider_name)
        await self._agg.fetch_one(provider_name, force=True)

    async def _run_curiosity_research(self) -> None:
        """After prefetch: pick interesting topics, research them, generate fragments."""
        if not (self._curator and self._curiosity_researcher and self._memory):
            return
        try:
            context = await self._agg.format_for_llm()
            topics = await self._curator.pick_interesting_topics(context, n=2)
            # 既存の pending + researched トピックは再調査しない
            existing = await self._memory.get_pending()
            existing += await self._memory.get_researched()
            existing_topics = {t["topic"] for t in existing}
            for topic in topics:
                if topic in existing_topics:
                    continue
                summary = await self._curiosity_researcher.research_topic(topic)
                if summary:
                    kws = nouns_to_keywords_string(extract_nouns(topic))
                    memory_id = await self._memory.save(
                        topic=topic,
                        keywords=kws,
                        research_type="ai_curiosity",
                        queued_content=f"{topic}に詳しい発信者を調べる",
                        expires_days=7,
                    )
                    await self._memory.update_summary(
                        memory_id=memory_id,
                        summary=summary,
                        expires_days=7,
                    )
                    # fragment生成（要約をhintとして使い、内的思考の断片を作る）
                    if self._fragment_generator:
                        fragment = await self._fragment_generator.generate_fragment(
                            topic=topic,
                            context_hint=summary,
                        )
                        if fragment:
                            frag_id = await self._memory.save(
                                topic=topic,
                                keywords=kws,
                                research_type="ai_fragment",
                                queued_content=fragment,
                                expires_days=2,
                            )
                            await self._memory.update_summary(
                                memory_id=frag_id,
                                summary=fragment,
                                expires_days=2,
                            )
                            logger.info("Fragment generated for topic=%r", topic)
        except Exception as e:
            logger.warning("curiosity research failed: %s", e)

    async def _cleanup_memory(self) -> None:
        if self._memory:
            count = await self._memory.cleanup_expired()
            logger.info("memory cleanup: %d entries cleaned", count)

    async def _cleanup_preferences(self) -> None:
        if self._preference_store:
            count = await self._preference_store.cleanup_old_signals(days=90)
            logger.info("preference cleanup: %d signals removed", count)
