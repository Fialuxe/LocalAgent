import asyncio
import logging

import httpx

from .base import BaseProvider
from .models import HackerNewsData, HNItem, ProviderResult

logger = logging.getLogger(__name__)

_BASE = "https://hacker-news.firebaseio.com/v0"


class HackerNewsProvider(BaseProvider):
    """
    Hacker News Firebase API でトップ記事を取得する（APIキー不要・無料）。

    エンジニア向けターゲットとの親和性が高く、
    「今日 HN で話題の話なんですけど」という会話フックになる。
    """

    name = "hacker_news"
    default_ttl = 900  # 15分

    def __init__(self, top_n: int = 5) -> None:
        self.top_n = top_n

    async def fetch(self) -> ProviderResult:
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
                ids_resp = await client.get(f"{_BASE}/topstories.json")
                ids_resp.raise_for_status()
                story_ids: list[int] = ids_resp.json()[: self.top_n * 2]

                # 記事詳細を並列取得
                tasks = [
                    client.get(f"{_BASE}/item/{sid}.json")
                    for sid in story_ids
                ]
                responses = await asyncio.gather(*tasks, return_exceptions=True)

            items: list[HNItem] = []
            rank = 1
            for resp in responses:
                if isinstance(resp, Exception):
                    continue
                try:
                    d = resp.json()
                    if d and d.get("type") == "story" and d.get("title"):
                        items.append(HNItem(
                            rank=rank,
                            title=d["title"],
                            score=d.get("score", 0),
                        ))
                        rank += 1
                except Exception as e:
                    logger.debug("story parse error: %s", e)
                    continue
                if len(items) >= self.top_n:
                    break

            return self._ok(HackerNewsData(items=items))
        except Exception as e:
            return self._err(str(e))
