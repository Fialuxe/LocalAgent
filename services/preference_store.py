"""
嗜好シグナルストア — 時間減衰付きキーワードスコアリングによる個人化。

アルゴリズム:
  Li et al. (2010) "A Contextual-Bandit Approach to Personalized News Recommendation" を
  単一ユーザー・ローカル向けに簡略化したもの。

シグナル種別と重み:
  explicit_interest  +1.0  （「興味あり」ボタン等）
  followup_question  +0.8  （会話でフォローアップ質問）
  long_reply         +0.5  （80文字超のユーザー返信）
  view_only          +0.1  （閲覧のみ）
  explicit_skip      -0.5  （「興味なし」ボタン等）

時間減衰:
  score = weight × exp(-0.1 × days_since_signal)
  λ=0.1 → 半減期 ≈ 7日
"""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path

logger = logging.getLogger(__name__)

_SIGNAL_WEIGHTS: dict[str, float] = {
    "explicit_interest": 1.0,
    "followup_question": 0.8,
    "long_reply": 0.5,
    "view_only": 0.1,
    "explicit_skip": -0.5,
}

_DECAY_LAMBDA = 0.1  # 半減期 ≈ 7日

_DDL = """\
CREATE TABLE IF NOT EXISTS preference_signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    item_keywords  TEXT    NOT NULL,
    signal_type    TEXT    NOT NULL,
    signal_weight  REAL    NOT NULL,
    created_at     REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_keywords ON preference_signals(item_keywords);
CREATE INDEX IF NOT EXISTS idx_created  ON preference_signals(created_at);
"""


class PreferenceStore:
    """
    SQLite ベースの嗜好シグナルストア。

    使い方:
        store = PreferenceStore()
        await store.initialize()
        await store.record_signal(["久保建英", "サッカー"], "followup_question")
        top = await store.get_top_topics(n=5)
    """

    def __init__(self, db_path: str = "preferences.db") -> None:
        self._db_path = str(Path(db_path))
        self._lock: asyncio.Lock | None = None

    @property
    def _write_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    # ------------------------------------------------------------------
    # 同期ヘルパー
    # ------------------------------------------------------------------

    def _sync_initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)
            conn.commit()

    def _sync_record_signal(
        self,
        item_keywords: list[str],
        signal_type: str,
    ) -> None:
        weight = _SIGNAL_WEIGHTS.get(signal_type, 0.0)
        if weight == 0.0:
            return
        keywords_str = " ".join(sorted(set(item_keywords)))
        now = time.time()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO preference_signals (item_keywords, signal_type, signal_weight, created_at) "
                "VALUES (?, ?, ?, ?)",
                (keywords_str, signal_type, weight, now),
            )
            conn.commit()

    def _sync_score_topic(self, keywords: list[str]) -> float:
        """キーワードリストに対する時間減衰済みスコアを計算する。"""
        if not keywords:
            return 0.0
        now = time.time()
        seconds_per_day = 86400.0
        total = 0.0
        with closing(self._connect()) as conn:
            for kw in keywords:
                rows = conn.execute(
                    "SELECT signal_weight, created_at FROM preference_signals "
                    "WHERE item_keywords LIKE ?",
                    (f"%{kw}%",),
                ).fetchall()
                for row in rows:
                    days_elapsed = (now - row["created_at"]) / seconds_per_day
                    total += row["signal_weight"] * math.exp(-_DECAY_LAMBDA * days_elapsed)
        return total

    def _sync_get_top_topics(self, n: int) -> list[str]:
        """スコアが高い上位 n 個のキーワード文字列を返す。"""
        now = time.time()
        seconds_per_day = 86400.0
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT item_keywords, signal_weight, created_at FROM preference_signals"
            ).fetchall()

        scored: dict[str, float] = {}
        for row in rows:
            days_elapsed = (now - row["created_at"]) / seconds_per_day
            score = row["signal_weight"] * math.exp(-_DECAY_LAMBDA * days_elapsed)
            scored[row["item_keywords"]] = scored.get(row["item_keywords"], 0.0) + score

        sorted_topics = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        return [topic for topic, _ in sorted_topics[:n]]

    def _sync_cleanup_old_signals(self, days: int) -> int:
        cutoff = time.time() - days * 86400.0
        with closing(self._connect()) as conn:
            cur = conn.execute(
                "DELETE FROM preference_signals WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------
    # 公開 async API
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """テーブルとインデックスを作成する。起動時に一度だけ呼ぶ。"""
        await asyncio.to_thread(self._sync_initialize)
        logger.info("PreferenceStore 初期化完了: %s", self._db_path)

    async def record_signal(
        self,
        item_keywords: list[str],
        signal_type: str,
    ) -> None:
        """
        嗜好シグナルを記録する。

        Args:
            item_keywords: シグナルに関連するキーワードのリスト。
            signal_type: シグナル種別（_SIGNAL_WEIGHTS のキー）。
        """
        async with self._write_lock:
            await asyncio.to_thread(self._sync_record_signal, item_keywords, signal_type)

    async def score_topic(self, keywords: list[str]) -> float:
        """キーワードリストに対する時間減衰済みスコアを返す。"""
        return await asyncio.to_thread(self._sync_score_topic, keywords)

    async def get_top_topics(self, n: int = 5) -> list[str]:
        """スコアが高い上位 n 個のキーワード文字列を返す。"""
        return await asyncio.to_thread(self._sync_get_top_topics, n)

    async def cleanup_old_signals(self, days: int = 90) -> int:
        """
        指定日数より古いシグナルを削除する。

        Returns:
            削除したレコード数。
        """
        async with self._write_lock:
            return await asyncio.to_thread(self._sync_cleanup_old_signals, days)
