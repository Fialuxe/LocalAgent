"""
コンパニオンメモリ — SQLite 永続化記憶システム。

ユーザーとの会話から抽出したトピックと、AIが自律的に興味を持った事柄を
SQLite に保存・更新・検索する。

使い方:
    memory = CompanionMemory()
    await memory.initialize()

    await memory.save("天気", "天気 雨 傘", research_type="user_mention")

    pending = await memory.get_pending()
    await memory.update_summary(pending[0]["id"], "東京は明日も雨の見込み。")

    researched = await memory.get_researched()
    await memory.mark_delivered(researched[0]["id"])

    cleaned = await memory.cleanup_expired()
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# アクティブエントリ（pending + researched）の上限
_ACTIVE_CAP = 200

# delivered エントリを完全削除するまでの猶予日数
_DELIVERED_RETENTION_DAYS = 90

_DDL = """\
CREATE TABLE IF NOT EXISTS memories (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    topic            TEXT    NOT NULL,
    keywords         TEXT    NOT NULL,
    first_mentioned  TEXT    NOT NULL,
    last_mentioned   TEXT    NOT NULL,
    times_mentioned  INTEGER DEFAULT 1,
    queued_content   TEXT,
    researched_summary TEXT,
    research_type    TEXT    DEFAULT 'user_mention',
    status           TEXT    DEFAULT 'pending',
    expires_at       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status   ON memories(status);
CREATE INDEX IF NOT EXISTS idx_keywords ON memories(keywords);
CREATE TABLE IF NOT EXISTS open_threads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    thought      TEXT    NOT NULL,
    source_topic TEXT    DEFAULT '',
    created_at   TEXT    NOT NULL,
    status       TEXT    DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS idx_thread_status ON open_threads(status);
"""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


class CompanionMemory:
    """
    SQLite ベースの永続化記憶システム。

    すべての書き込み操作は asyncio.Lock で保護し、
    ブロッキング SQLite 呼び出しは asyncio.to_thread() でオフロードする。
    """

    def __init__(self, db_path: str = "companion_memory.db") -> None:
        self._db_path = str(Path(db_path))
        self._lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------
    # Lock はイベントループ内で初めてアクセスした時点に生成（cache.py と同じ慣用句）
    # ------------------------------------------------------------------
    @property
    def _write_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------
    # 同期ヘルパー（asyncio.to_thread でオフロード）
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _sync_initialize(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)
            conn.commit()

    def _sync_save(
        self,
        topic: str,
        keywords: str,
        research_type: str,
        queued_content: str | None,
        expires_days: int,
    ) -> int:
        now = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()

        with closing(self._connect()) as conn:
            # 同一トピックで pending / researched のエントリがあれば更新
            row = conn.execute(
                "SELECT id, times_mentioned FROM memories "
                "WHERE topic = ? AND status IN ('pending', 'researched') "
                "LIMIT 1",
                (topic,),
            ).fetchone()

            if row:
                conn.execute(
                    "UPDATE memories "
                    "SET keywords = ?, last_mentioned = ?, "
                    "    times_mentioned = ?, queued_content = COALESCE(?, queued_content) "
                    "WHERE id = ?",
                    (
                        keywords,
                        now,
                        row["times_mentioned"] + 1,
                        queued_content,
                        row["id"],
                    ),
                )
                conn.commit()
                return int(row["id"])
            else:
                # アクティブ上限チェック：超えている場合は最古の pending を削除
                active_count: int = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE status IN ('pending', 'researched')"
                ).fetchone()[0]

                if active_count >= _ACTIVE_CAP:
                    excess = active_count - _ACTIVE_CAP + 1
                    oldest_ids = [
                        r[0]
                        for r in conn.execute(
                            "SELECT id FROM memories WHERE status = 'pending' "
                            "ORDER BY last_mentioned ASC LIMIT ?",
                            (excess,),
                        ).fetchall()
                    ]
                    if oldest_ids:
                        conn.execute(
                            f"DELETE FROM memories WHERE id IN ({','.join('?' * len(oldest_ids))})",
                            oldest_ids,
                        )
                        logger.debug("アクティブ上限超過のため %d 件の pending を削除しました", len(oldest_ids))

                cur = conn.execute(
                    "INSERT INTO memories "
                    "(topic, keywords, first_mentioned, last_mentioned, "
                    " queued_content, research_type, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (topic, keywords, now, now, queued_content, research_type, expires_at),
                )
                conn.commit()
                return int(cur.lastrowid)

    def _sync_get_researched(self) -> list[dict]:
        now = datetime.now().isoformat()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM memories "
                "WHERE status = 'researched' AND expires_at > ? "
                "ORDER BY last_mentioned DESC",
                (now,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def _sync_mark_delivered(self, memory_id: int) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE memories SET status = 'delivered' WHERE id = ?",
                (memory_id,),
            )
            conn.commit()

    def _sync_update_summary(
        self,
        memory_id: int,
        summary: str,
        expires_days: int,
    ) -> None:
        expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE memories "
                "SET researched_summary = ?, status = 'researched', expires_at = ? "
                "WHERE id = ?",
                (summary, expires_at, memory_id),
            )
            conn.commit()

    def _sync_get_pending(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM memories "
                "WHERE status = 'pending' "
                "ORDER BY last_mentioned DESC",
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def _sync_cleanup_expired(self) -> int:
        now = datetime.now().isoformat()
        cutoff = (datetime.now() - timedelta(days=_DELIVERED_RETENTION_DAYS)).isoformat()
        cleaned = 0

        with closing(self._connect()) as conn:
            # 期限切れの pending / researched を stale に変更
            cur = conn.execute(
                "UPDATE memories SET status = 'stale' "
                "WHERE status IN ('pending', 'researched') AND expires_at <= ?",
                (now,),
            )
            cleaned += cur.rowcount

            # 90日超えの delivered を物理削除
            cur = conn.execute(
                "DELETE FROM memories "
                "WHERE status = 'delivered' AND last_mentioned <= ?",
                (cutoff,),
            )
            cleaned += cur.rowcount

            conn.commit()

        logger.debug("cleanup_expired: %d 件を処理しました", cleaned)
        return cleaned

    # ------------------------------------------------------------------
    # 公開 async API
    # ------------------------------------------------------------------
    async def initialize(self) -> None:
        """テーブルとインデックスを作成する。起動時に一度だけ呼ぶ。"""
        await asyncio.to_thread(self._sync_initialize)
        logger.info("CompanionMemory 初期化完了: %s", self._db_path)

    async def save(
        self,
        topic: str,
        keywords: str,
        research_type: str = "user_mention",
        queued_content: str | None = None,
        expires_days: int = 14,
    ) -> int:
        """
        記憶を保存または更新する。挿入/更新した行の id を返す。

        同一トピックで pending / researched のエントリが既にある場合は
        times_mentioned をインクリメントして last_mentioned を更新する。
        """
        async with self._write_lock:
            return await asyncio.to_thread(
                self._sync_save,
                topic,
                keywords,
                research_type,
                queued_content,
                expires_days,
            )

    async def get_researched(self) -> list[dict]:
        """status='researched' かつ未期限のエントリを返す。"""
        return await asyncio.to_thread(self._sync_get_researched)

    async def mark_delivered(self, memory_id: int) -> None:
        """AIがユーザーに共有済みの記憶を delivered に更新する。"""
        async with self._write_lock:
            await asyncio.to_thread(self._sync_mark_delivered, memory_id)

    async def update_summary(
        self,
        memory_id: int,
        summary: str,
        expires_days: int = 30,
    ) -> None:
        """
        調査結果を保存して status を researched に移行する。

        summary は 2〜3行を目安にコンパクトにまとめること。
        """
        async with self._write_lock:
            await asyncio.to_thread(
                self._sync_update_summary,
                memory_id,
                summary,
                expires_days,
            )

    async def get_pending(self) -> list[dict]:
        """status='pending' かつ未期限のエントリを返す。"""
        return await asyncio.to_thread(self._sync_get_pending)

    async def cleanup_expired(self) -> int:
        """
        期限切れエントリを stale に変更し、90日超えの delivered を物理削除する。

        Returns:
            処理（変更 + 削除）したエントリの合計件数。
        """
        async with self._write_lock:
            return await asyncio.to_thread(self._sync_cleanup_expired)

    # ------------------------------------------------------------------
    # open_threads — セッションをまたぐ未解決の気になりごと
    # research_type: 'user_mention' | 'ai_curiosity' | 'ai_fragment'
    # ------------------------------------------------------------------

    def _sync_save_thread(self, thought: str, source_topic: str) -> int:
        now = datetime.now().isoformat()
        with closing(self._connect()) as conn:
            cur = conn.execute(
                "INSERT INTO open_threads (thought, source_topic, created_at) VALUES (?, ?, ?)",
                (thought, source_topic, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def _sync_get_open_threads(self, n: int) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM open_threads WHERE status = 'open' "
                "ORDER BY created_at DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def _sync_resolve_thread(self, thread_id: int) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE open_threads SET status = 'resolved' WHERE id = ?",
                (thread_id,),
            )
            conn.commit()

    async def save_open_thread(self, thought: str, source_topic: str = "") -> int:
        """未解決の気になりごとを保存する。"""
        async with self._write_lock:
            return await asyncio.to_thread(self._sync_save_thread, thought, source_topic)

    async def get_open_threads(self, n: int = 3) -> list[dict]:
        """未解決スレッドを n 件返す（新しい順）。"""
        return await asyncio.to_thread(self._sync_get_open_threads, n)

    async def resolve_thread(self, thread_id: int) -> None:
        """スレッドを解決済みにする。"""
        async with self._write_lock:
            await asyncio.to_thread(self._sync_resolve_thread, thread_id)
