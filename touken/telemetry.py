"""Versioned, structured runtime observations for UI and future advisors.

This store deliberately keeps machine data separate from human-facing logs.  It
stores no screenshots and never raises into a game flow: telemetry may be lost,
but it must never make automation fail.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .runtime_paths import LOG_DIR


TELEMETRY_SCHEMA_VERSION = 1
DEFAULT_RETENTION_DAYS = 90


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


class TelemetryStore:
    """Small WAL-backed event store safe for panel and worker processes."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or (LOG_DIR / "telemetry.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                script TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL,
                status TEXT NOT NULL DEFAULT 'running'
            );
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                run_id TEXT,
                script TEXT,
                kind TEXT NOT NULL,
                expected TEXT,
                match_mode TEXT,
                matched INTEGER,
                roi TEXT NOT NULL,
                tokens TEXT NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                run_id TEXT,
                script TEXT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_observations_ts ON observations(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_observations_run ON observations(run_id);
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
        """)
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
            (str(TELEMETRY_SCHEMA_VERSION),),
        )
        conn.commit()

    def close(self) -> None:
        """Close this thread's connection (primarily for tests and clean shutdowns)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @staticmethod
    def runtime_context() -> tuple[str | None, str | None]:
        return (os.environ.get("MAAMARU_RUN_ID") or None,
                os.environ.get("MAAMARU_SCRIPT") or None)

    def start_run(self, run_id: str, script: str, started_at: float | None = None) -> None:
        try:
            self.prune()
            self._conn().execute(
                "INSERT OR REPLACE INTO runs(run_id, script, started_at, ended_at, status) "
                "VALUES (?, ?, ?, NULL, 'running')",
                (run_id, script, started_at or time.time()),
            )
            self._conn().commit()
        except Exception:
            pass

    def finish_run(self, run_id: str, status: str, ended_at: float | None = None) -> None:
        try:
            self._conn().execute(
                "UPDATE runs SET ended_at = ?, status = ? WHERE run_id = ?",
                (ended_at or time.time(), status, run_id),
            )
            self._conn().commit()
        except Exception:
            pass

    def record_ocr(self, *, kind: str, roi: list[int], tokens: list[dict],
                   expected: str | None = None, match_mode: str | None = None,
                   matched: bool | None = None, error: str | None = None) -> None:
        try:
            run_id, script = self.runtime_context()
            self._conn().execute(
                "INSERT INTO observations(ts, run_id, script, kind, expected, match_mode, "
                "matched, roi, tokens, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), run_id, script, kind, expected, match_mode,
                 None if matched is None else int(matched), _json(roi), _json(tokens), error),
            )
            self._conn().commit()
        except Exception:
            pass

    def record_event(self, event_type: str, payload: dict | None = None) -> None:
        try:
            run_id, script = self.runtime_context()
            self._conn().execute(
                "INSERT INTO events(ts, run_id, script, event_type, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), run_id, script, event_type, _json(payload or {})),
            )
            self._conn().commit()
        except Exception:
            pass

    def recent_events(self, limit: int = 100, event_type: str | None = None,
                      script: str | None = None) -> list[dict]:
        clauses, args = [], []
        if event_type:
            clauses.append("event_type = ?")
            args.append(event_type)
        if script:
            clauses.append("script = ?")
            args.append(script)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(max(1, min(int(limit), 1000)))
        rows = self._conn().execute(
            "SELECT id, ts, run_id, script, event_type, payload FROM events" +
            where + " ORDER BY id DESC LIMIT ?", args,
        ).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "run_id": r["run_id"],
                 "script": r["script"], "event_type": r["event_type"],
                 "payload": _loads(r["payload"], {})} for r in rows]

    def run_summary(self, run_id: str) -> dict | None:
        """Build one human-facing task result from structured events only."""
        run = self._conn().execute(
            "SELECT run_id, script, started_at, ended_at, status FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if not run:
            return None
        rows = self._conn().execute(
            "SELECT ts, event_type, payload FROM events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        events = [{"ts": r["ts"], "event_type": r["event_type"],
                   "payload": _loads(r["payload"], {})} for r in rows]
        loop_events = [e for e in events if e["event_type"] in {
            "osaka.floor_completed", "sortie.completed", "raid.round_completed",
            "pumpkin.sortie_completed",
        }]
        osaka = [e for e in loop_events if e["event_type"] == "osaka.floor_completed"]
        intervals = [b["ts"] - a["ts"] for a, b in zip(loop_events, loop_events[1:])
                     if b["ts"] > a["ts"]]
        average = sum(intervals) / len(intervals) if intervals else None
        repairs = [e for e in events if e["event_type"] == "repair.session_completed"]
        completed_repairs = [e for e in repairs
                             if int(e["payload"].get("repaired") or
                                    e["payload"].get("count") or 0) > 0]
        snapshots = [e for e in events if e["event_type"] == "inventory.captured"]
        before = next((e for e in snapshots if e["payload"].get("phase") == "before"), None)
        after = next((e for e in reversed(snapshots)
                      if e["payload"].get("phase") == "after"), None)
        deltas = {}
        if before and after:
            left = before["payload"].get("resources") or {}
            right = after["payload"].get("resources") or {}
            for name in left.keys() | right.keys():
                if isinstance(left.get(name), (int, float)) and isinstance(right.get(name), (int, float)):
                    deltas[name] = right[name] - left[name]
        selected = [e["payload"].get("selected_floor") for e in osaka
                    if e["payload"].get("selected_floor") is not None]
        return {
            "run_id": run["run_id"], "script": run["script"],
            "started_at": run["started_at"], "ended_at": run["ended_at"],
            "status": run["status"],
            "duration_seconds": ((run["ended_at"] - run["started_at"])
                                 if run["ended_at"] else None),
            "loops": len(loop_events),
            "selected_floor": selected[-1] if selected else None,
            "average_loop_seconds": round(average, 1) if average else None,
            "estimated_6h_loops": int(21600 // average) if average else None,
            "repair_sessions": len(completed_repairs),
            "repaired_swords": sum(int(e["payload"].get("repaired") or 0) for e in repairs),
            "speedups": sum(int(e["payload"].get("speedups") or 0) for e in repairs),
            "equipment_restores": sum(1 for e in events
                                      if e["event_type"] == "equipment.restored"),
            "resource_delta": deltas,
            "has_resource_comparison": bool(before and after),
        }

    def recent_run_summaries(self, limit: int = 20, script: str | None = None) -> list[dict]:
        clauses, args = ["status != 'running'"], []
        if script:
            clauses.append("script = ?")
            args.append(script)
        args.append(max(1, min(int(limit), 100)))
        rows = self._conn().execute(
            "SELECT run_id FROM runs WHERE " + " AND ".join(clauses) +
            " ORDER BY started_at DESC LIMIT ?", args,
        ).fetchall()
        return [summary for row in rows
                if (summary := self.run_summary(row["run_id"])) is not None]

    def recent_observations(self, limit: int = 100, script: str | None = None,
                            matched: bool | None = None) -> list[dict]:
        clauses, args = [], []
        if script:
            clauses.append("script = ?")
            args.append(script)
        if matched is not None:
            clauses.append("matched = ?")
            args.append(int(matched))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(max(1, min(int(limit), 1000)))
        rows = self._conn().execute(
            "SELECT id, ts, run_id, script, kind, expected, match_mode, matched, "
            "roi, tokens, error FROM observations" + where +
            " ORDER BY id DESC LIMIT ?", args,
        ).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "run_id": r["run_id"],
                 "script": r["script"], "kind": r["kind"],
                 "expected": r["expected"], "match_mode": r["match_mode"],
                 "matched": None if r["matched"] is None else bool(r["matched"]),
                 "roi": _loads(r["roi"], []), "tokens": _loads(r["tokens"], []),
                 "error": r["error"]} for r in rows]

    def summary(self, days: int = 30) -> dict:
        days = max(1, min(int(days), 3650))
        since = time.time() - days * 86400
        conn = self._conn()
        run_rows = conn.execute(
            "SELECT script, status, COUNT(*) count FROM runs WHERE started_at >= ? "
            "GROUP BY script, status", (since,),
        ).fetchall()
        run_by_script, run_by_status = {}, {}
        for row in run_rows:
            run_by_script[row["script"]] = run_by_script.get(row["script"], 0) + row["count"]
            run_by_status[row["status"]] = run_by_status.get(row["status"], 0) + row["count"]

        ocr = conn.execute(
            "SELECT COUNT(*) total, SUM(CASE WHEN matched = 1 THEN 1 ELSE 0 END) hits, "
            "SUM(CASE WHEN matched = 0 THEN 1 ELSE 0 END) misses "
            "FROM observations WHERE ts >= ?", (since,),
        ).fetchone()
        expected_rows = conn.execute(
            "SELECT expected, COUNT(*) total, "
            "SUM(CASE WHEN matched = 1 THEN 1 ELSE 0 END) hits "
            "FROM observations WHERE ts >= ? AND expected IS NOT NULL "
            "GROUP BY expected ORDER BY total DESC LIMIT 100", (since,),
        ).fetchall()
        event_rows = conn.execute(
            "SELECT event_type, COUNT(*) count FROM events WHERE ts >= ? "
            "GROUP BY event_type ORDER BY count DESC", (since,),
        ).fetchall()
        matched_total = int(ocr["hits"] or 0) + int(ocr["misses"] or 0)
        return {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "generated_at": time.time(),
            "window": {"days": days, "since": since,
                       "retention_days": DEFAULT_RETENTION_DAYS},
            "runs": {"total": sum(run_by_status.values()),
                     "by_script": run_by_script, "by_status": run_by_status},
            "ocr": {
                "total": int(ocr["total"] or 0),
                "matched": int(ocr["hits"] or 0),
                "missed": int(ocr["misses"] or 0),
                "match_rate": round(int(ocr["hits"] or 0) / matched_total, 4)
                if matched_total else None,
                "by_expected": [
                    {"expected": r["expected"], "total": r["total"],
                     "matched": int(r["hits"] or 0),
                     "match_rate": round(int(r["hits"] or 0) / r["total"], 4)}
                    for r in expected_rows
                ],
            },
            "events": {"total": sum(r["count"] for r in event_rows),
                       "by_type": {r["event_type"]: r["count"] for r in event_rows}},
        }

    def prune(self, retention_days: int = DEFAULT_RETENTION_DAYS) -> None:
        cutoff = time.time() - max(1, int(retention_days)) * 86400
        try:
            conn = self._conn()
            conn.execute("DELETE FROM observations WHERE ts < ?", (cutoff,))
            conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            conn.commit()
        except Exception:
            pass


_store: TelemetryStore | None = None
_lock = threading.Lock()


def get_telemetry_store() -> TelemetryStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = TelemetryStore()
    return _store


def record_event(event_type: str, payload: dict | None = None) -> None:
    get_telemetry_store().record_event(event_type, payload)
