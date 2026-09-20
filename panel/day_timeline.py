"""仪表盘「今天的时间表」数据组装（纯只读）。

把远征排班投影和 telemetry 的运行记录压到同一条 24 小时横轴上，
全部依赖可注入（cfg / store / script_labels / active），方便单测。
"""

from __future__ import annotations

import time
from datetime import datetime

from . import scheduler

DAY_MINUTES = 24 * 60

_RUN_TONES = {
    "completed": "ok",
    "failed": "failed",
    "stopped": "stopped",
    "watchdog": "stopped",
    "running": "running",
}


def _day_window(now: float) -> tuple[float, float]:
    day_start = datetime.fromtimestamp(now).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    return day_start, day_start + 86400


def _minute_of(time_text: str) -> int:
    try:
        hh, mm = str(time_text).split(":")[:2]
        return int(hh) * 60 + int(mm)
    except (ValueError, TypeError):
        return 0


def _expedition_items(cfg: dict, now: float, day_start: float) -> list[dict]:
    auto = cfg.get("automation", {}) if isinstance(cfg, dict) else {}
    mode = auto.get("mode", "preset")
    auto_enabled = bool(auto.get("enabled", True))
    durations = {}
    try:
        durations = {m["code"]: int(m.get("duration_min", 0))
                     for m in scheduler.map_options()}
    except Exception:
        pass
    entries = cfg.get("entries", []) if isinstance(cfg, dict) else []

    items = []
    try:
        projection = scheduler.today_projection(cfg=cfg, now=now)
    except Exception:
        projection = {"preset": [], "custom": []}
    for lane_name, lane_items in (("preset", projection.get("preset", [])),
                                  ("custom", projection.get("custom", []))):
        for it in lane_items:
            if lane_name == "preset":
                enabled = auto_enabled and mode == "preset"
            else:
                idx = it.get("index")
                entry = entries[idx] if isinstance(idx, int) and 0 <= idx < len(entries) else {}
                enabled = (auto_enabled and mode == "custom"
                           and bool(entry.get("enabled", True)))
            time_min = _minute_of(it.get("time", "00:00"))
            duration = durations.get(it.get("map_code"), 0)
            # 只保留与今天有重叠的班（preset 的循环日可能跨零点）
            start_ts = day_start + time_min * 60
            end_ts = start_ts + duration * 60
            day_end = day_start + 86400
            if end_ts <= day_start or start_ts >= day_end:
                continue
            items.append({
                "time_min": time_min,
                "duration_min": duration,
                "team_no": it.get("team_no"),
                "map_code": it.get("map_code", ""),
                "state": it.get("state", "pending"),
                "blocked_reason": it.get("blocked_reason") or "",
                "late_min": int(it.get("late_min") or 0),
                "enabled": enabled,
            })
    items.sort(key=lambda x: (x["time_min"], x.get("team_no") or 0))
    return items


def _run_items(store, active: dict | None, day_start: float, day_end: float,
               script_labels: dict | None) -> list[dict]:
    labels = script_labels or {}
    try:
        rows = store.runs_between(day_start, day_end) if store else []
    except Exception:
        rows = []
    active_script = (active or {}).get("script")
    active_started = float((active or {}).get("started") or 0)
    items = []
    for row in rows:
        script = row.get("script") or ""
        started_at = float(row.get("started_at") or 0)
        ended_at = row.get("ended_at")
        ended_at = float(ended_at) if ended_at else None
        status = row.get("status") or ""
        tone = _RUN_TONES.get(status, "stopped")
        is_active = bool(
            active_script and script == active_script
            and abs(started_at - active_started) < 2)
        # runs_between 会把所有 ended_at=NULL 的旧记录当作跨日记录返回。
        # 它们只是往日面板异常退出留下的尸体，不属于“今天”，也不能全挤在 0 点。
        if started_at < day_start and ended_at is None and not is_active:
            continue
        if is_active:
            tone = "running"
            ended_at = None
        elif status == "running":
            # 脚本只活在面板进程里：runner 没在跑它，这条就是上次面板挂掉
            # 留下的「尸体」记录，别在轴上画成还在跑
            tone = "stopped"
            ended_at = None
        items.append({
            "script": script,
            "label": labels.get(script) or script,
            "started_at": started_at,
            "ended_at": ended_at,
            "status": status,
            "tone": tone,
        })
    return items


def _hanafuda_hint(now: float, store) -> str | None:
    """秘宝之里进行中且算得出剩余时长时给一句话彩蛋；算不出就 None。"""
    if store is None:
        return None
    try:
        from touken import advisor
        from touken.runtime_paths import STATE_DIR
        cards = advisor.load_event_cards(STATE_DIR)
        now_dt = datetime.fromtimestamp(now)
        for card in (cards or {}).values():
            if not isinstance(card, dict) or card.get("mechanics") != "hanafuda":
                continue
            plan = advisor.hanafuda_plan(store, card, now_dt=now_dt)
            est = plan.get("estimated_seconds")
            seconds_to_end = plan.get("seconds_to_end")
            if not (est and seconds_to_end and seconds_to_end > 0
                    and plan.get("tama_remaining")):
                continue
            hours = est / 3600.0
            duration = (f"约 {hours:.1f} 小时" if hours >= 1
                        else f"约 {int(est // 60)} 分钟")
            return f"秘宝之里：按现在的节奏，拿完剩下的玉还要{duration}。"
    except Exception:
        pass
    return None


def build_day_timeline(now: float | None = None, *, cfg: dict | None = None,
                       store=None, script_labels: dict | None = None,
                       active: dict | None = None) -> dict:
    """组装 24 小时只读时间轴：远征班次块 + 任务运行条 + 参考线。"""
    now = time.time() if now is None else now
    if cfg is None:
        cfg = scheduler.load_config()
    if store is None:
        try:
            from touken.telemetry import get_telemetry_store
            store = get_telemetry_store()
        except Exception:
            store = None
    day_start, day_end = _day_window(now)
    return {
        "now": now,
        "day_start": day_start,
        "markers": [{"time_min": 240, "label": "日课刷新", "kind": "daily_reset"}],
        "expeditions": _expedition_items(cfg, now, day_start),
        "runs": _run_items(store, active, day_start, day_end, script_labels),
        "hint": _hanafuda_hint(now, store),
    }
