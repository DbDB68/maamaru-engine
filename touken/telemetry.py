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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .runtime_paths import LOG_DIR


TELEMETRY_SCHEMA_VERSION = 4
DEFAULT_RETENTION_DAYS = 90

# ── 资源总账（resource_ledger）契约常量 ──
LEDGER_SCHEMA_VERSION = 1
# 资源全集，顺序固定：顶栏四资源 + 真小判 + 甲州金 + 右栏两符
LEDGER_RESOURCES = ("木炭", "玉钢", "冷却材", "砥石", "小判", "甲州金", "委托符", "加速符")
# peek 只有顶栏五资源（契约：永远不含小判/委托符/加速符），
# 白名单过滤防脏 payload 污染小判观察链
_LEDGER_PEEK_RESOURCES = frozenset(("木炭", "玉钢", "冷却材", "砥石", "甲州金"))
_LEDGER_OBS_TYPES = ("inventory.captured", "inventory.peek", "osaka.koban_session")
_LEDGER_MERGE_SECONDS = 5.0  # 同一时刻多来源同值观察的去重窗口

try:
    from zoneinfo import ZoneInfo
    _LEDGER_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # Windows 无 tzdata 时兜底：上海 1991 年后无夏令时，固定 +8 够用
    _LEDGER_TZ = timezone(timedelta(hours=8))


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
            CREATE TABLE IF NOT EXISTS human_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                occurred_at REAL NOT NULL,
                source TEXT NOT NULL,
                gap_key TEXT,
                activities TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_observations_ts ON observations(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_observations_run ON observations(run_id);
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_human_reports_occurred
                ON human_reports(occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_human_reports_gap
                ON human_reports(gap_key);
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

    def record_event(self, event_type: str, payload: dict | None = None) -> int | None:
        """写入一条事件并返回事件 id（供 resource.change 的 source_event_id 关联）。

        写失败返回 None——telemetry 丢了不许拖垮玩法流程。
        """
        try:
            run_id, script = self.runtime_context()
            cursor = self._conn().execute(
                "INSERT INTO events(ts, run_id, script, event_type, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), run_id, script, event_type, _json(payload or {})),
            )
            self._conn().commit()
            return cursor.lastrowid
        except Exception:
            return None

    def attach_inventory_snapshot(self, run_id: str, snapshot: dict,
                                  captured_ts: float | None = None) -> dict:
        """Attach a later standalone inventory snapshot as a run's closing snapshot.

        Unlike passive telemetry writes, this is a user-requested correction and must
        fail loudly when the association would be ambiguous or misleading.
        """
        conn = self._conn()
        run = conn.execute(
            "SELECT run_id, script, ended_at FROM runs WHERE run_id = ?", (run_id,),
        ).fetchone()
        if not run:
            raise ValueError("找不到这轮任务记录")
        if run["ended_at"] is None:
            raise ValueError("任务还在运行，不能补收工盘点")
        resources = snapshot.get("resources")
        if not isinstance(resources, dict) or not resources:
            raise ValueError("最近的库存快照没有可用资源数据")
        captured_ts = float(captured_ts or time.time())
        if captured_ts < float(run["ended_at"]):
            raise ValueError("最近的库存快照早于这轮收工，请先重新运行“库存快照”")
        snapshot_rows = conn.execute(
            "SELECT e.run_id, e.payload, r.started_at FROM events e "
            "JOIN runs r ON r.run_id = e.run_id "
            "WHERE e.event_type = 'inventory.captured' ORDER BY r.started_at DESC, e.id DESC",
        ).fetchall()
        latest_started_run = next((row["run_id"] for row in snapshot_rows
                                   if _loads(row["payload"], {}).get("phase") == "before"), None)
        if latest_started_run and latest_started_run != run_id:
            raise ValueError("只能给最近一条带开工盘点的挂机记录补录，不能把新库存补到旧轮次")
        existing = conn.execute(
            "SELECT payload FROM events WHERE run_id = ? AND event_type = 'inventory.captured'",
            (run_id,),
        ).fetchall()
        payloads = [_loads(row["payload"], {}) for row in existing]
        if any(payload.get("phase") == "after" for payload in payloads):
            raise ValueError("这轮已经有收工盘点，无需重复补录")
        if not any(payload.get("phase") == "before" for payload in payloads):
            raise ValueError("这轮没有开工盘点，单独补收工数据也无法计算变化")
        payload = dict(snapshot)
        payload.update({"phase": "after", "source": "manual_attach"})
        conn.execute(
            "INSERT INTO events(ts, run_id, script, event_type, payload) VALUES (?, ?, ?, ?, ?)",
            (captured_ts, run_id, run["script"], "inventory.captured", _json(payload)),
        )
        conn.commit()
        return self.run_summary(run_id)

    def add_human_report(self, *, occurred_at: float, activities: list[str],
                         note: str = "", source: str = "proactive",
                         gap_key: str | None = None) -> dict:
        activities = [str(value).strip()[:40] for value in activities
                      if str(value).strip()][:20]
        note = str(note or "").strip()[:300]
        source = source if source in {"proactive", "gap"} else "proactive"
        gap_key = str(gap_key or "").strip()[:80] or None
        if not activities and not note:
            raise ValueError("请至少选一项，或留一句说明")
        created_at = time.time()
        cursor = self._conn().execute(
            "INSERT INTO human_reports(created_at, occurred_at, source, gap_key, activities, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (created_at, float(occurred_at), source, gap_key, _json(activities), note),
        )
        self._conn().commit()
        return {"id": cursor.lastrowid, "created_at": created_at,
                "occurred_at": float(occurred_at), "source": source,
                "gap_key": gap_key, "activities": activities, "note": note}

    def human_reports(self, limit: int = 200) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id, created_at, occurred_at, source, gap_key, activities, note "
            "FROM human_reports ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        return [{**dict(row), "activities": _loads(row["activities"], [])}
                for row in rows]

    def delete_human_report(self, report_id: int) -> bool:
        cursor = self._conn().execute(
            "DELETE FROM human_reports WHERE id = ?", (int(report_id),),
        )
        self._conn().commit()
        return cursor.rowcount > 0

    def inventory_gaps(self, limit: int = 50) -> list[dict]:
        """Return resource changes between a prior closing snapshot and next run start."""
        rows = self._conn().execute(
            "SELECT id, ts, run_id, payload FROM events "
            "WHERE event_type = 'inventory.captured' ORDER BY ts, id",
        ).fetchall()
        snapshots = [{**dict(row), "payload": _loads(row["payload"], {})}
                     for row in rows]
        reported = {row["gap_key"] for row in self._conn().execute(
            "SELECT gap_key FROM human_reports WHERE gap_key IS NOT NULL",
        ).fetchall()}
        gaps = []
        for previous, current in zip(snapshots, snapshots[1:]):
            previous_phase = previous["payload"].get("phase")
            current_phase = current["payload"].get("phase")
            if current_phase != "before" or previous_phase not in {"after", None}:
                continue
            if previous["run_id"] == current["run_id"]:
                continue
            left = previous["payload"].get("resources") or {}
            right = current["payload"].get("resources") or {}
            delta = {name: right[name] - left[name] for name in left.keys() & right.keys()
                     if isinstance(left.get(name), (int, float))
                     and isinstance(right.get(name), (int, float))
                     and right[name] != left[name]}
            if not delta:
                continue
            gap_key = f'{previous["id"]}:{current["id"]}'
            gaps.append({"gap_key": gap_key, "started_at": previous["ts"],
                         "ended_at": current["ts"], "resource_delta": delta,
                         "reported": gap_key in reported})
        return list(reversed(gaps[-max(1, min(int(limit), 200)):]))

    def resource_ledger(self, from_ts: float, to_ts: float) -> dict:
        """聚合时间窗口内八种资源的总账：观察链、已确认归因、缺口。

        SQL 层按 ts 过滤，不走 recent_events 的 1000 条上限。
        total_delta 保留符号、恒等于 attributed + unattributed（负残差不截断）；
        观察不足形成不了 opening/closing 时 total_delta 为 None，
        但 confirmed 明细仍保留在 attributions 里。
        """
        from_ts, to_ts = float(from_ts), float(to_ts)
        if to_ts < from_ts:
            from_ts, to_ts = to_ts, from_ts
        conn = self._conn()
        event_types = ("inventory.captured", "inventory.peek", "osaka.koban_session",
                       "repair.session_completed", "resource.change")
        marks = ",".join("?" * len(event_types))
        rows = conn.execute(
            "SELECT id, ts, run_id, script, event_type, payload FROM events "
            f"WHERE ts >= ? AND ts <= ? AND event_type IN ({marks}) ORDER BY ts, id",
            (from_ts, to_ts, *event_types)).fetchall()
        # 窗前基线：三种观察来源各取窗口前最近一条，合成各资源的 opening
        baseline_rows = []
        for event_type in _LEDGER_OBS_TYPES:
            row = conn.execute(
                "SELECT id, ts, run_id, script, event_type, payload FROM events "
                "WHERE ts < ? AND event_type = ? ORDER BY ts DESC, id DESC LIMIT 1",
                (from_ts, event_type)).fetchone()
            if row:
                baseline_rows.append(row)
        # resource.change 的 before/after 同样是直读观察（异去补充提灯等），
        # 但不是每条都有余额，基线向前翻找最近一条带 before/after 的
        for row in conn.execute(
                "SELECT id, ts, run_id, script, event_type, payload FROM events "
                "WHERE ts < ? AND event_type = 'resource.change' "
                "ORDER BY ts DESC, id DESC LIMIT 50", (from_ts,)).fetchall():
            rc_payload = _loads(row["payload"], {})
            if (rc_payload.get("resource")
                    and isinstance(rc_payload.get("before"), (int, float))
                    and isinstance(rc_payload.get("after"), (int, float))):
                baseline_rows.append(row)
                break
        reports = conn.execute(
            "SELECT id, occurred_at, gap_key FROM human_reports "
            "WHERE occurred_at <= ? ORDER BY occurred_at, id", (to_ts,)).fetchall()

        # ── 观察流：优先级 直读 before/after(3) > captured(2) > peek(1) ──
        raw: list[dict] = []
        for row in [*baseline_rows, *rows]:
            payload = _loads(row["payload"], {})
            event_type = row["event_type"]
            if event_type == "osaka.koban_session":
                # sub 区分同事件内 before/after 的先后顺序（事件只有一个 ts）
                for sub, key in ((0, "before"), (1, "after")):
                    value = payload.get(key)
                    if isinstance(value, (int, float)):
                        raw.append({"ts": row["ts"], "sub": sub, "resource": "小判",
                                    "value": value, "priority": 3, "source": event_type,
                                    "event_id": row["id"], "evidence": [row["id"]]})
            elif event_type == "inventory.captured":
                for name, value in (payload.get("resources") or {}).items():
                    if isinstance(value, (int, float)):
                        raw.append({"ts": row["ts"], "sub": 0, "resource": name,
                                    "value": value, "priority": 2, "source": event_type,
                                    "event_id": row["id"], "evidence": [row["id"]]})
            elif event_type == "inventory.peek":
                for name in _LEDGER_PEEK_RESOURCES:
                    value = payload.get(name)
                    if isinstance(value, (int, float)):
                        raw.append({"ts": row["ts"], "sub": 0, "resource": name,
                                    "value": value, "priority": 1, "source": event_type,
                                    "event_id": row["id"], "evidence": [row["id"]]})
            elif event_type == "resource.change":
                # 带 before/after 的 resource.change（如异去补充提灯）是直读观察，
                # 否则跨日分桶的 opening 会跳过这条消费链，把支出漏成次日未归因
                name = payload.get("resource")
                if name:
                    for sub, key in ((0, "before"), (1, "after")):
                        value = payload.get(key)
                        if isinstance(value, (int, float)):
                            raw.append({"ts": row["ts"], "sub": sub, "resource": name,
                                        "value": value, "priority": 3,
                                        "source": event_type,
                                        "event_id": row["id"], "evidence": [row["id"]]})

        # 去重：时间贴脸（5 秒内）且数值一致 = 同一观察点，合并证据 event id，
        # 来源升到最高优先级；数值不同 = 证据冲突，各算各的观察并记冲突缺口
        observations: dict[str, list[dict]] = {}
        conflicts: list[tuple] = []
        by_resource: dict[str, list[dict]] = {}
        for entry in raw:
            by_resource.setdefault(entry["resource"], []).append(entry)
        for name, entries in by_resource.items():
            entries.sort(key=lambda e: (e["ts"], e["sub"], -e["priority"], e["event_id"]))
            merged: list[dict] = []
            for entry in entries:
                if merged and entry["ts"] - merged[-1]["ts"] <= _LEDGER_MERGE_SECONDS:
                    last = merged[-1]
                    if entry["value"] == last["value"]:
                        last["evidence"].append(entry["event_id"])
                        if entry["priority"] > last["priority"]:
                            last.update(priority=entry["priority"], source=entry["source"])
                        continue
                    # 同事件的 before/after 本来就不同值，不算冲突；
                    # 不同来源贴脸读数不一致才是证据冲突
                    if entry["event_id"] != last["event_id"]:
                        conflicts.append((name, last["ts"], entry["ts"],
                                          last["value"], entry["value"]))
                merged.append(entry)
            observations[name] = merged

        # ── 归因：resource.change 双写去重（source_event_id 指向旧事件时跳过旧的那份）──
        shadowed = set()
        # 加速符去重：同 run 已有 repair.confirm_screen 的逐笔记账时，
        # repair.session_completed 的 speedups 汇总让位（逐笔粒度更细更准）；
        # 没有逐笔记录的老数据照常靠 session_completed 归因
        per_repair_runs: set = set()
        per_repair_any = False
        for row in rows:
            if row["event_type"] == "resource.change":
                rc_payload = _loads(row["payload"], {})
                source_event_id = rc_payload.get("source_event_id")
                if isinstance(source_event_id, (int, float)):
                    shadowed.add(int(source_event_id))
                if (rc_payload.get("source") == "repair.confirm_screen"
                        and rc_payload.get("resource") == "加速符"):
                    per_repair_any = True
                    if row["run_id"]:
                        per_repair_runs.add(row["run_id"])
        attributions: list[dict] = []
        for row in rows:
            payload = _loads(row["payload"], {})
            event_type = row["event_type"]
            item = None
            if event_type == "osaka.koban_session" and row["id"] not in shadowed:
                delta = payload.get("delta")
                if isinstance(delta, (int, float)) and delta:
                    item = {"resource": "小判", "delta": delta, "source": event_type,
                            "label": f"挖地小判 {int(delta):+d}", "confidence": "confirmed"}
            elif event_type == "repair.session_completed" and row["id"] not in shadowed:
                # run_id 优先配对；run_id 缺失时按窗内是否有逐笔记录兜底
                has_per_repair = (row["run_id"] in per_repair_runs
                                  if row["run_id"] else per_repair_any)
                speedups = payload.get("speedups")
                if (not has_per_repair
                        and isinstance(speedups, (int, float)) and speedups):
                    item = {"resource": "加速符", "delta": -int(speedups),
                            "source": event_type,
                            "label": f"手入加速符 {-int(speedups):+d}",
                            "confidence": "confirmed"}
            elif event_type == "resource.change":
                delta = payload.get("delta")
                resource = str(payload.get("resource") or "")
                if resource and isinstance(delta, (int, float)) and delta:
                    item = {"resource": resource, "delta": delta,
                            "source": str(payload.get("source") or event_type),
                            "label": str(payload.get("note") or f"{resource} {int(delta):+d}"),
                            "confidence": str(payload.get("attribution") or "confirmed")}
            if item:
                item.update({"id": f"a{len(attributions) + 1}", "ts": row["ts"],
                             "script": row["script"], "run_id": row["run_id"],
                             "event_id": row["id"]})
                attributions.append(item)

        # ── 缺口：跨 run 快照差值 + 人工报备 + 证据冲突 ──
        gaps: list[dict] = []
        report_list = [{"id": r["id"], "occurred_at": r["occurred_at"],
                        "gap_key": r["gap_key"]} for r in reports]
        captured = sorted((r for r in [*baseline_rows, *rows]
                           if r["event_type"] == "inventory.captured"),
                          key=lambda r: (r["ts"], r["id"]))
        for prev, cur in zip(captured, captured[1:]):
            prev_payload = _loads(prev["payload"], {})
            cur_payload = _loads(cur["payload"], {})
            if (cur_payload.get("phase") != "before"
                    or prev_payload.get("phase") not in ("after", None)):
                continue
            if prev["run_id"] == cur["run_id"]:
                continue
            if cur["ts"] < from_ts or prev["ts"] > to_ts:
                continue
            left = prev_payload.get("resources") or {}
            right = cur_payload.get("resources") or {}
            delta = {name: right[name] - left[name] for name in left.keys() & right.keys()
                     if isinstance(left.get(name), (int, float))
                     and isinstance(right.get(name), (int, float))
                     and right[name] != left[name]}
            if not delta:
                continue
            gap_key = f'{prev["id"]}:{cur["id"]}'
            linked = [r["id"] for r in report_list
                      if r["gap_key"] == gap_key
                      or (prev["ts"] < r["occurred_at"] <= cur["ts"])]
            gaps.append({"id": f'gap-{int(prev["ts"])}-{int(cur["ts"])}',
                         "from": prev["ts"], "to": cur["ts"], "resources": delta,
                         "reason": "no_observation", "human_report_ids": linked})
        linked_report_ids = {rid for gap in gaps for rid in gap["human_report_ids"]}
        for report in report_list:
            # 没挂上任何缺口的窗口内人工报备单独成条：只降置信度，不改写库存
            if (report["id"] in linked_report_ids
                    or not from_ts <= report["occurred_at"] <= to_ts):
                continue
            gaps.append({"id": f'gap-hr-{report["id"]}',
                         "from": report["occurred_at"], "to": report["occurred_at"],
                         "resources": {}, "reason": "human_reported",
                         "human_report_ids": [report["id"]]})
        for name, ts_a, ts_b, value_a, value_b in conflicts:
            gaps.append({"id": f"gap-conflict-{int(ts_a)}-{int(ts_b)}",
                         "from": ts_a, "to": ts_b,
                         "resources": {name: value_b - value_a},
                         "reason": "conflicting_evidence", "human_report_ids": []})
        gaps.sort(key=lambda g: (g["from"], g["id"]))

        def _gap_ids(start: float, end: float) -> list[str]:
            return [g["id"] for g in gaps if g["from"] <= end and g["to"] >= start]

        def _confidence(obs_count: int, attrs: list[dict], paired: bool,
                        start: float, end: float) -> str:
            # 观察缺失 / 有人工报备或缺口 / 证据冲突 = low；
            # 观察链完整且有 confirmed 覆盖 = high；只有观察差值无归因 = medium
            if obs_count == 0 or _gap_ids(start, end):
                return "low"
            if paired and any(a["confidence"] == "confirmed" for a in attrs):
                return "high"
            return "medium"

        def _pair(all_obs: list[dict], start: float, end: float):
            """opening = 窗前基线（没有则窗内首观察），closing = 窗内末观察。

            只有孤零零一条观察时不构成 opening/closing 对，返回 paired=False。
            """
            before = [o for o in all_obs if o["ts"] < start]
            within = [o for o in all_obs if start <= o["ts"] <= end]
            opening = before[-1] if before else (within[0] if within else None)
            closing = within[-1] if within else None
            paired = bool(opening is not None and closing is not None
                          and opening is not closing)
            return opening, closing, within, paired

        per_resource = []
        for name in LEDGER_RESOURCES:
            opening, closing, within, paired = _pair(
                observations.get(name, []), from_ts, to_ts)
            attrs = [a for a in attributions if a["resource"] == name]
            attributed = sum(a["delta"] for a in attrs)
            total = closing["value"] - opening["value"] if paired else None
            per_resource.append({
                "resource": name,
                "opening": opening["value"] if opening else None,
                "closing": closing["value"] if closing else None,
                "total_delta": total,
                "attributed_delta": attributed,
                "unattributed_delta": (total - attributed) if total is not None else None,
                "observation_count": len(within),
                "confidence": _confidence(len(within), attrs, paired, from_ts, to_ts),
            })

        # ── 按 Asia/Shanghai 日期分桶：跨日 run 按观察发生日记账 ──
        daily_series = []
        day = datetime.fromtimestamp(from_ts, _LEDGER_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0)
        last_day = datetime.fromtimestamp(to_ts, _LEDGER_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0)
        while day <= last_day:
            next_day = day + timedelta(days=1)
            start_ts, end_ts = day.timestamp(), next_day.timestamp() - 1e-6
            for name in LEDGER_RESOURCES:
                opening, closing, within, paired = _pair(
                    observations.get(name, []), start_ts, end_ts)
                day_attrs = [a for a in attributions
                             if a["resource"] == name and start_ts <= a["ts"] <= end_ts]
                if not within and not day_attrs:
                    continue
                attributed = sum(a["delta"] for a in day_attrs)
                total = closing["value"] - opening["value"] if paired else None
                daily_series.append({
                    "date": day.date().isoformat(), "resource": name,
                    "opening": opening["value"] if opening else None,
                    "closing": closing["value"] if closing else None,
                    "total_delta": total,
                    "attributed_delta": attributed,
                    "unattributed_delta": (total - attributed) if total is not None else None,
                    "observation_count": len(within),
                    "confidence": _confidence(len(within), day_attrs, paired,
                                              start_ts, end_ts),
                    "gap_ids": _gap_ids(start_ts, end_ts),
                    "attribution_ids": [a["id"] for a in day_attrs],
                })
            day = next_day

        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "generated_at": time.time(),
            "window": {"from": from_ts, "to": to_ts, "timezone": "Asia/Shanghai",
                       "days": round((to_ts - from_ts) / 86400, 2)},
            "per_resource": per_resource,
            "daily_series": daily_series,
            "gaps": gaps,
            "attributions": attributions,
        }

    def recent_events(self, limit: int = 100, event_type: str | None = None,
                      script: str | None = None,
                      before_id: int | None = None,
                      from_ts: float | None = None,
                      to_ts: float | None = None) -> list[dict]:
        clauses, args = [], []
        if event_type:
            clauses.append("event_type = ?")
            args.append(event_type)
        if script:
            clauses.append("script = ?")
            args.append(script)
        if before_id is not None:
            clauses.append("id < ?")
            args.append(max(1, int(before_id)))
        if from_ts is not None:
            clauses.append("ts >= ?")
            args.append(float(from_ts))
        if to_ts is not None:
            clauses.append("ts < ?")
            args.append(float(to_ts))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(max(1, min(int(limit), 1001)))
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
            "pumpkin.sortie_completed", "sortie.retreated_before_boss",
        }]
        osaka = [e for e in loop_events if e["event_type"] == "osaka.floor_completed"]
        intervals = [b["ts"] - a["ts"] for a, b in zip(loop_events, loop_events[1:])
                     if b["ts"] > a["ts"]]
        average = sum(intervals) / len(intervals) if intervals else None
        play_duration = ((loop_events[-1]["ts"] - run["started_at"])
                         if loop_events and loop_events[-1]["ts"] >= run["started_at"]
                         else None)
        repairs = [e for e in events if e["event_type"] == "repair.session_completed"]
        completed_repairs = [e for e in repairs
                             if int(e["payload"].get("repaired") or
                                    e["payload"].get("count") or 0) > 0]
        snapshots = [e for e in events if e["event_type"] == "inventory.captured"]
        peeks = [e for e in events if e["event_type"] == "inventory.peek"]
        attributed_deltas: dict[str, int | float] = {}
        resource_change_count = 0
        for event in events:
            if event["event_type"] != "resource.change":
                continue
            payload = event["payload"]
            delta = payload.get("delta")
            resource = payload.get("resource")
            if not resource or not isinstance(delta, (int, float)) or not delta:
                continue
            resource_change_count += 1
            attributed_deltas[resource] = attributed_deltas.get(resource, 0) + delta
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
        # 挖地小判掉落率实验：没有前后盘点时，用实验自带的开工/收场小判顶上
        # （run 级盘点 2026-08 退役后，这是挖地成绩单小判差值的主要来源）
        koban_science = None
        if not (before and after):
            sci = [e["payload"] for e in events
                   if e["event_type"] == "osaka.koban_session"
                   and isinstance(e["payload"].get("before"), (int, float))
                   and isinstance(e["payload"].get("after"), (int, float))]
            if sci:
                koban_science = sci[-1]
                deltas["小判"] = (int(koban_science["after"])
                                  - int(koban_science["before"]))
        selected = [e["payload"].get("selected_floor") for e in osaka
                    if e["payload"].get("selected_floor") is not None]
        return {
            "run_id": run["run_id"], "script": run["script"],
            "started_at": run["started_at"], "ended_at": run["ended_at"],
            "status": run["status"],
            "duration_seconds": ((run["ended_at"] - run["started_at"])
                                 if run["ended_at"] else None),
            "play_duration_seconds": round(play_duration, 1) if play_duration is not None else None,
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
            "attributed_resource_delta": attributed_deltas,
            "resource_change_count": resource_change_count,
            "inventory_observation": (peeks[-1]["payload"] if peeks else None),
            "inventory_observation_count": len(peeks),
            "has_resource_comparison": bool(before and after) or bool(koban_science),
            "has_before_snapshot": bool(before) or bool(koban_science),
            "has_after_snapshot": bool(after) or bool(koban_science),
            "after_snapshot_source": (after["payload"].get("source") if after
                                      else ("auto_science" if koban_science else None)),
            "koban_session": koban_science,
        }

    def recent_run_summaries(self, limit: int = 20, script: str | None = None,
                             before_started_at: float | None = None,
                             from_ts: float | None = None,
                             to_ts: float | None = None) -> list[dict]:
        clauses, args = ["status != 'running'"], []
        if script:
            clauses.append("script = ?")
            args.append(script)
        if before_started_at is not None:
            clauses.append("started_at < ?")
            args.append(float(before_started_at))
        if from_ts is not None:
            clauses.append("started_at >= ?")
            args.append(float(from_ts))
        if to_ts is not None:
            clauses.append("started_at < ?")
            args.append(float(to_ts))
        args.append(max(1, min(int(limit), 101)))
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
        activity_rows = conn.execute(
            "SELECT event_type, payload FROM events WHERE ts >= ? AND event_type IN "
            "('sortie.completed', 'sortie.retreated_before_boss', "
            "'osaka.floor_completed', 'raid.round_completed', "
            "'pumpkin.sortie_completed', 'practice.result')",
            (since,),
        ).fetchall()
        activity = {"sorties": 0, "practice": {"total": 0, "wins": 0,
                                                "losses": 0, "unknown": 0},
                    "sortie_groups": []}
        sortie_groups: dict[tuple, dict] = {}
        for row in activity_rows:
            event_type = row["event_type"]
            payload = _loads(row["payload"], {})
            if event_type == "practice.result":
                activity["practice"]["total"] += 1
                result = str(payload.get("result") or payload.get("outcome") or "").lower()
                if "胜" in result or result.startswith("win") or result == "won":
                    activity["practice"]["wins"] += 1
                elif "败" in result or result.startswith("lose") or result == "lost":
                    activity["practice"]["losses"] += 1
                else:
                    activity["practice"]["unknown"] += 1
                continue
            activity["sorties"] += 1
            if event_type == "osaka.floor_completed":
                key = ("osaka", payload.get("selected_floor"))
            elif event_type in {"sortie.completed", "sortie.retreated_before_boss"}:
                key = (event_type, payload.get("mode"), payload.get("chapter"),
                       payload.get("map_no"))
            elif event_type == "raid.round_completed":
                key = ("raid", payload.get("difficulty"), bool(payload.get("triple")))
            else:
                key = ("pumpkin",)
            group = sortie_groups.setdefault(key, {
                "event_type": event_type, "payload": payload, "count": 0,
            })
            group["count"] += 1
        activity["sortie_groups"] = sorted(
            sortie_groups.values(), key=lambda item: item["count"], reverse=True)
        matched_total = int(ocr["hits"] or 0) + int(ocr["misses"] or 0)
        return {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "generated_at": time.time(),
            "window": {"days": days, "since": since,
                       "retention_days": DEFAULT_RETENTION_DAYS,
                       "detail_retention_days": DEFAULT_RETENTION_DAYS,
                       "history_retention_days": None},
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
            "activity": activity,
        }

    def prune(self, retention_days: int | None = None) -> None:
        """Trim bulky OCR detail; explicit retention keeps the legacy full trim."""
        days = DEFAULT_RETENTION_DAYS if retention_days is None else retention_days
        cutoff = time.time() - max(1, int(days)) * 86400
        try:
            conn = self._conn()
            conn.execute("DELETE FROM observations WHERE ts < ?", (cutoff,))
            if retention_days is not None:
                conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
                conn.execute("DELETE FROM human_reports WHERE occurred_at < ?", (cutoff,))
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


def record_event(event_type: str, payload: dict | None = None) -> int | None:
    """记录事件，返回事件 id（失败返回 None）。"""
    return get_telemetry_store().record_event(event_type, payload)
