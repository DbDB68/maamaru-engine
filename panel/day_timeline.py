"""仪表盘「今天的时间表」数据组装（纯只读）。

把远征排班投影和 telemetry 的运行记录压到同一条 24 小时横轴上，
全部依赖可注入（cfg / store / script_labels / active），方便单测。
"""

from __future__ import annotations

import time
from datetime import datetime

from . import scheduler

DAY_MINUTES = 24 * 60

# 建议层的避让口径
DAILY_RESET_WINDOW = (3 * 60 + 50, 4 * 60 + 10)  # 03:50–04:10 领旧日课+重登
ACTION_WINDOW_BEFORE_MIN = 2   # 班次计划时刻前 2 分钟起占画面（派遣/收菜动作）
ACTION_WINDOW_AFTER_MIN = 5
MIN_SUGGESTION_MIN = 30        # 一圈约 7 分钟，不足 30 分钟的碎片不建议
MAX_SUGGESTION_BLOCKS = 2      # 一块装不下才切第二块

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


def _hanafuda_active_plan(now: float, store) -> dict | None:
    """秘宝之里进行中且样本够算时返回 hanafuda_plan 的输出；否则 None。"""
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
            if (plan.get("estimated_seconds") and plan.get("seconds_to_end")
                    and plan["seconds_to_end"] > 0 and plan.get("tama_remaining")):
                return plan
    except Exception:
        pass
    return None


def _hanafuda_hint(plan: dict | None) -> str | None:
    if not plan:
        return None
    est = plan["estimated_seconds"]
    hours = est / 3600.0
    duration = (f"约 {hours:.1f} 小时" if hours >= 1
                else f"约 {int(est // 60)} 分钟")
    return f"秘宝之里：按现在的节奏，拿完剩下的玉还要{duration}。"


def _daily_quota_seconds(plan: dict, remaining_today: float) -> int | None:
    """今天该挂多少秒。

    口径和活动卡前端一致（EventTimeline.vue tamaTimeText）：
    estimated_seconds 按剩余天数（seconds_to_end / 86400）平摊，
    再被 estimated_seconds 本身、今天剩余时间、收摊时间三头卡住。
    """
    est = plan.get("estimated_seconds")
    seconds_to_end = plan.get("seconds_to_end")
    if not (est and seconds_to_end and seconds_to_end > 0):
        return None
    days_left = seconds_to_end / 86400
    daily = est / days_left if days_left > 0 else est
    quota = min(daily, est, remaining_today, seconds_to_end)
    return int(quota) if quota > 0 else None


def suggest_windows(now_min: float, occupied: list[dict],
                    needed_seconds: int) -> tuple[list[dict], int]:
    """从 now_min 向 24:00 贪心填空闲段，返回 (建议块, 排不下的秒数)。

    occupied: [{start_min, end_min, label}]，会被裁剪合并。
    规则：最多 2 块；不足 30 分钟的碎片不出块（除非这一块正好填满需求）；
    块尾的 note 记录它避开的占用段。
    """
    if needed_seconds <= 0:
        return [], 0
    cursor = max(0, min(int(now_min), DAY_MINUTES))
    merged = []
    for seg in sorted(occupied, key=lambda s: (s["start_min"], s["end_min"])):
        s = max(0, int(seg["start_min"]))
        e = min(DAY_MINUTES, int(seg["end_min"]))
        if e <= s:
            continue
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e, merged[-1][2])
        else:
            merged.append((s, e, seg.get("label") or ""))

    blocks = []
    remaining = needed_seconds
    min_block = MIN_SUGGESTION_MIN * 60

    def _try_fill(free_start: int, free_end: int, label: str) -> None:
        nonlocal remaining
        cap = (free_end - free_start) * 60
        if cap <= 0:
            return
        piece = min(remaining, cap)
        if piece < min_block and piece < remaining:
            return  # 碎片太短，留给 shortfall 诚实上报
        blocks.append({
            "start_min": free_start,
            "duration_min": piece // 60,
            "note": f"避开{label}" if label else "",
        })
        remaining -= piece

    for s, e, label in merged:
        if remaining <= 0 or len(blocks) >= MAX_SUGGESTION_BLOCKS:
            break
        if e <= cursor:
            continue
        if s > cursor:
            _try_fill(cursor, s, label)
        cursor = max(cursor, e)
    if (remaining > 0 and len(blocks) < MAX_SUGGESTION_BLOCKS
            and cursor < DAY_MINUTES):
        _try_fill(cursor, DAY_MINUTES, "")
    return blocks, remaining


def _occupied_segments(expedition_items: list[dict], cfg: dict,
                       hanafuda_team_no: int | None) -> list[dict]:
    """把三类占用段拼出来：日课刷新窗口、班次动作窗口、活动队的远征时段。"""
    occupied = [{
        "start_min": DAILY_RESET_WINDOW[0],
        "end_min": DAILY_RESET_WINDOW[1],
        "label": "日课刷新",
    }]
    try:
        managed = scheduler.managed_teams(cfg)
    except Exception:
        managed = set()
    away_whole_shift = bool(hanafuda_team_no and hanafuda_team_no in managed)
    for e in expedition_items:
        if not e.get("enabled"):
            continue
        team = scheduler.TEAM_NAMES.get(int(e.get("team_no") or 0),
                                        f"部队{e.get('team_no')}")
        start = e["time_min"]
        when = f"{start // 60:02d}:{start % 60:02d}"
        occupied.append({
            "start_min": start - ACTION_WINDOW_BEFORE_MIN,
            "end_min": start + ACTION_WINDOW_AFTER_MIN,
            "label": f"{when} {team}派遣",
        })
        # 活动队被远征排班管着时，整段远征队伍都不在家，出不了阵
        if away_whole_shift and int(e.get("team_no") or 0) == hanafuda_team_no:
            occupied.append({
                "start_min": start,
                "end_min": start + int(e.get("duration_min") or 0),
                "label": f"{when} {team}远征",
            })
    return occupied


def build_day_timeline(now: float | None = None, *, cfg: dict | None = None,
                       store=None, script_labels: dict | None = None,
                       active: dict | None = None,
                       hanafuda_team_no: int | None = None) -> dict:
    """组装 24 小时只读时间轴：远征班次块 + 任务运行条 + 参考线 + 挂机建议。"""
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
    expeditions = _expedition_items(cfg, now, day_start)
    plan = _hanafuda_active_plan(now, store)
    suggestions = None
    shortfall_seconds = None
    quota = _daily_quota_seconds(plan, day_end - now) if plan else None
    if quota:
        occupied = _occupied_segments(expeditions, cfg, hanafuda_team_no)
        now_min = (now - day_start) / 60
        suggestions, shortfall_seconds = suggest_windows(now_min, occupied, quota)
    return {
        "now": now,
        "day_start": day_start,
        "markers": [{"time_min": 240, "label": "日课刷新", "kind": "daily_reset"}],
        "expeditions": expeditions,
        "runs": _run_items(store, active, day_start, day_end, script_labels),
        "hint": _hanafuda_hint(plan),
        "suggestions": suggestions,
        "shortfall_seconds": shortfall_seconds,
    }
