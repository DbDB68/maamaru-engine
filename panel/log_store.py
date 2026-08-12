"""
日志持久化 —— SQLite 存储，每条 yield 消息当一条记录存。
脚本崩了 Ctrl+C 了，打开面板历史全部在。
"""

import json
import sqlite3
import threading
import time
from pathlib import Path

from touken.runtime_paths import LOG_DIR


class LogStore:
    """线程安全的日志持久化存储"""

    def __init__(self, db_path: str | Path = None):
        if db_path is None:
            db_path = LOG_DIR / "maamaru_logs.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """每个线程拿自己的连接（SQLite 连接不是线程安全的）"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                run_id      TEXT    NOT NULL,
                script      TEXT    NOT NULL,
                message     TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_run ON logs(run_id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL
            )
        """)
        conn.commit()

    def append(self, run_id: str, script: str, message: str):
        """追加一条日志"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO logs (ts, run_id, script, message) VALUES (?, ?, ?, ?)",
            (time.time(), run_id, script, message),
        )
        conn.commit()

    def get_recent(self, limit: int = 100, after_id: int = 0) -> list[dict]:
        """获取最近日志，支持增量拉取（after_id）"""
        conn = self._get_conn()
        if after_id > 0:
            rows = conn.execute(
                "SELECT id, ts, run_id, script, message FROM logs "
                "WHERE id > ? ORDER BY id ASC LIMIT ?",
                (after_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, ts, run_id, script, message FROM logs "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            rows.reverse()
        return [
            {
                "id": row[0],
                "ts": row[1],
                "run_id": row[2],
                "script": row[3],
                "message": row[4],
            }
            for row in rows
        ]

    def get_last_id(self) -> int:
        """获取最新日志 ID（用于增量拉取）"""
        conn = self._get_conn()
        row = conn.execute("SELECT MAX(id) FROM logs").fetchone()
        return row[0] or 0

    def add_chat(self, role: str, content: str):
        """存一条聊天记录"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO chat_history (ts, role, content) VALUES (?, ?, ?)",
            (time.time(), role, content),
        )
        conn.commit()

    def get_chat_history(self, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT ts, role, content FROM chat_history ORDER BY id ASC"
        ).fetchall()
        return [
            {"ts": row[0], "role": row[1], "content": row[2]} for row in rows
        ]


# 全局单例
_store: LogStore | None = None
_lock = threading.Lock()


def get_store() -> LogStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = LogStore()
    return _store
