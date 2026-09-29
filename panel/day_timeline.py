"""仪表盘「今天的时间表」数据组装（纯只读）。

把远征排班投影和 telemetry 的运行记录压到同一条 24 小时横轴上，
全部依赖可注入（cfg / store / script_labels / active），方便单测。
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone

from . import scheduler
from .expedition_choices import is_forced, load_choice_sets
from . import expedition_advisor

DAY_MINUTES = 24 * 60
SHANGHAI_TZ = timezone(timedelta(hours=8))

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


# 建议引擎的家底报告（resource_watch / koban_watch）：30 秒轮询的时间表
# 不值得每次都重算一遍账本，成功结果缓存两分钟；失败不缓存，下次再试。
_PLANNING_TTL_SEC = 120.0
_planning_cache: dict[float, dict] = {}


def _load_planning_snapshot(store):
    if store is None:
        return None
    now = time.time()
    for cached_at, data in list(_planning_cache.items()):
        if now - cached_at < _PLANNING_TTL_SEC and data is not None:
            return data
    try:
        from touken import advisor
        from touken.runtime_paths import CONFIG_PATH, STATE_DIR
        recipe = None
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            recipe = (config.get("forge") or {}).get("recipe")
        except Exception:
            pass
        data = advisor.get_planning(store, STATE_DIR / advisor.GOALS_FILENAME,
                                    forge_recipe=recipe)
    except Exception:
        return None
    _planning_cache.clear()
    _planning_cache[now] = data if isinstance(data, dict) else None
    return data


def _minute_of(time_text: str) -> int:
    try:
        hh, mm = str(time_text).split(":")[:2]
        return int(hh) * 60 + int(mm)
    except (ValueError, TypeError):
        return 0


def _expedition_items(cfg: dict, now: float, day_start: float,
                      choices: dict | None = None,
                      forced: dict | None = None) -> list[dict]:
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
    forced = forced or {}

    items = []
    # 预设循环可能跨午夜；取今天开头和结尾所在的两个循环，按真实日期筛选。
    projected = {}
    for at in (day_start + 1, day_start + 86399, now):
        try:
            projection = scheduler.today_projection(cfg=cfg, now=at,
                                                    choices=choices, forced=forced)
        except Exception:
            continue
        for item in projection.get(mode, []):
            projected[item["key"]] = item
    for it in projected.values():
        team_no = int(it.get("team_no") or 0)
        map_code = it.get("map_code", "")
        forced_today = is_forced(forced, key=it["key"], team_no=team_no,
                                 map_code=map_code)
        if mode == "preset":
            entry_enabled = True
        else:
            idx = it.get("index")
            entry = entries[idx] if isinstance(idx, int) and 0 <= idx < len(entries) else {}
            entry_enabled = bool(entry.get("enabled", True))
        base_enabled = auto_enabled and entry_enabled
        skipped_today = bool(it.get("skipped_today")) and not forced_today
        # 会跑 = 排班开着且没跳过，或被单班强制启用（自定义排班条目被关掉的除外）
        will_run = (base_enabled and not skipped_today) or (forced_today and entry_enabled)
        planned_at = float(it.get("planned_at") or 0)
        if not day_start <= planned_at < day_start + 86400:
            continue
        time_min = int((planned_at - day_start) // 60)
        duration = durations.get(map_code, 0)
        items.append({
            "key": it["key"], "planned_at": planned_at,
            "time_min": time_min,
            "duration_min": duration,
            "team_no": it.get("team_no"),
            "map_code": map_code,
            "state": it.get("state", "pending"),
            "blocked_reason": it.get("blocked_reason") or "",
            "late_min": int(it.get("late_min") or 0),
            "enabled": base_enabled and not skipped_today,
            "base_enabled": base_enabled,
            "entry_enabled": entry_enabled,
            "skipped_today": skipped_today,
            "forced_today": forced_today,
            "will_run": will_run,
            "toggleable": (entry_enabled and planned_at > now + 60
                           and it.get("state") in ("pending", "skipped")),
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
            # 工作流在开工时已经把当时的名字写进 runs.label；优先使用这份
            # 快照，既不退回笼统的“自定义工作流”，也不被日后改名篡改历史。
            "label": row.get("label") or labels.get(script) or script,
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
        now_dt = datetime.fromtimestamp(now, SHANGHAI_TZ)
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


def _raid_active_plan(now: float, store) -> dict | None:
    """只使用已确认的本期联队战卡与实测圈数／圈速。"""
    if store is None:
        return None
    try:
        from touken import advisor
        from touken.runtime_paths import STATE_DIR
        cards = advisor.load_event_cards(STATE_DIR)
        now_dt = datetime.fromtimestamp(now, SHANGHAI_TZ)
        for card in (cards or {}).values():
            if not isinstance(card, dict) or card.get("mechanics") != "raid":
                continue
            plan = advisor.currency_plan(store, card, now_dt=now_dt,
                                         mechanics="raid")
            if (plan.get("runs_needed") and plan.get("seconds_per_loop")
                    and plan.get("seconds_to_end") and plan["seconds_to_end"] > 0
                    and plan.get("tama_remaining")):
                game_day = now_dt.replace(hour=4, minute=0, second=0,
                                          microsecond=0)
                if now_dt < game_day:
                    game_day -= timedelta(days=1)
                period_events = advisor._currency_period_events(
                    store, card, mechanics="raid", limit=1001)
                observed_at = plan.get("tama_observed_at") or now
                plan["completed_today"] = sum(
                    1 for ts, _ in period_events
                    if game_day.timestamp() <= ts <= min(now, observed_at))
                plan["game_day_started_at"] = game_day.timestamp()
                plan["now"] = now
                return plan
    except Exception:
        pass
    return None


def _raid_daily_runs(plan: dict) -> int:
    """活动卡的日均圈数扣掉本丸换日后已完成的圈，不让目标边跑边重置。"""
    runs = int(plan["runs_needed"])
    completed = int(plan.get("completed_today") or 0)
    elapsed = max(0, plan.get("now", 0) - plan.get("game_day_started_at", 0))
    days_left = (plan["seconds_to_end"] + elapsed) / 86400
    original_target = min(runs + completed,
                          max(1, math.ceil((runs + completed) / days_left)))
    return min(runs, max(0, original_target - completed))


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


def suggest_round_windows(now_min: float, occupied: list[dict],
                          needed_runs: int, seconds_per_loop: int) -> tuple[list[dict], int]:
    """联队战建议只放完整圈；每段最多 99 圈，避免推荐任务表单填不下的数量。"""
    if needed_runs <= 0 or seconds_per_loop <= 0:
        return [], max(0, needed_runs)
    cursor = max(0, min(math.ceil(now_min), DAY_MINUTES))
    merged = []
    for seg in sorted(occupied, key=lambda s: (s["start_min"], s["end_min"])):
        start = max(0, int(seg["start_min"]))
        end = min(DAY_MINUTES, int(seg["end_min"]))
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end, merged[-1][2])
        else:
            merged.append((start, end, seg.get("label") or ""))

    blocks = []
    remaining = needed_runs

    def fill(start: int, end: int, label: str) -> None:
        nonlocal remaining
        while remaining > 0 and len(blocks) < MAX_SUGGESTION_BLOCKS:
            capacity = (end - start) * 60 // seconds_per_loop
            runs = min(remaining, capacity, 99)
            if runs <= 0:
                return
            duration = math.ceil(runs * seconds_per_loop / 60)
            blocks.append({
                "start_min": start,
                "duration_min": duration,
                "runs": runs,
                "note": f"避开{label}" if label else "",
            })
            remaining -= runs
            start += duration

    for start, end, label in merged:
        if remaining <= 0 or len(blocks) >= MAX_SUGGESTION_BLOCKS:
            break
        if end <= cursor:
            continue
        if start > cursor:
            fill(cursor, start, label)
        cursor = max(cursor, end)
    if remaining > 0 and len(blocks) < MAX_SUGGESTION_BLOCKS and cursor < DAY_MINUTES:
        fill(cursor, DAY_MINUTES, "")
    return blocks, remaining


def _occupied_segments(expedition_items: list[dict], cfg: dict,
                       activity_team_no: int | None) -> list[dict]:
    """避开刷新、派遣动作和活动队外出；队伍未知时保守避开全部远征。"""
    occupied = [{
        "start_min": DAILY_RESET_WINDOW[0],
        "end_min": DAILY_RESET_WINDOW[1],
        "label": "日课刷新",
    }]
    try:
        managed = scheduler.managed_teams(cfg)
    except Exception:
        managed = {int(e.get("team_no") or 0) for e in expedition_items
                   if e.get("enabled")}
    away_whole_shift = bool(activity_team_no and activity_team_no in managed)
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
        if activity_team_no is None or (away_whole_shift
                                        and int(e.get("team_no") or 0) == activity_team_no):
            occupied.append({
                "start_min": start,
                "end_min": start + int(e.get("duration_min") or 0)
                if e.get("duration_min") else DAY_MINUTES,
                "label": f"{when} {team}远征",
            })
    return occupied


def build_day_timeline(now: float | None = None, *, cfg: dict | None = None,
                       store=None, script_labels: dict | None = None,
                       active: dict | None = None,
                       hanafuda_team_no: int | None = None,
                       raid_team_no: int | None = None,
                       expedition_choices: dict | None = None,
                       expedition_forced: dict | None = None,
                       expedition_help: dict | None = None,
                       planning: dict | None = None,
                       situation_path=None) -> dict:
    """组装 24 小时只读时间轴：远征班次块 + 任务运行条 + 参考线 + 挂机建议。

    expedition_help / planning 都可注入（测试）；缺省分别从偏好文件和
    账本报告取，取不到就给空建议 + 原因。
    """
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
    if expedition_choices is None or expedition_forced is None:
        loaded_choices, loaded_forced = load_choice_sets()
        if expedition_choices is None:
            expedition_choices = loaded_choices
        if expedition_forced is None:
            expedition_forced = loaded_forced
    expeditions = _expedition_items(cfg, now, day_start,
                                    expedition_choices, expedition_forced)
    if expedition_help is None:
        expedition_help = expedition_advisor.load_prefs()
    if planning is None and int(expedition_help.get("teams_out") or 0) > 0:
        planning = _load_planning_snapshot(store)
    advice = expedition_advisor.build_expedition_suggestions(
        {"expeditions": expeditions}, expedition_help, planning=planning,
        situation_path=situation_path)
    hanafuda_plan = _hanafuda_active_plan(now, store)
    raid_plan = _raid_active_plan(now, store)
    suggestions = None
    shortfall_seconds = None
    activity = None
    hint = None
    now_min = (now - day_start) / 60
    if hanafuda_plan and raid_plan:
        hint = "秘宝之里和联队战都在进行，今天先不替你选活动；时间表仍显示远征班次。"
    elif raid_plan:
        daily_runs = _raid_daily_runs(raid_plan)
        pace = int(raid_plan["seconds_per_loop"])
        completed = int(raid_plan.get("completed_today") or 0)
        if active and active.get("script"):
            hint = "有任务正在运行；收工并记下圈数后，再按远征班次安排联队战。"
        else:
            occupied = _occupied_segments(expeditions, cfg, raid_team_no)
            # 活动收摊前留五分钟收尾，不把一圈安排到收摊之后。
            finish_min = math.floor(now_min + raid_plan["seconds_to_end"] / 60 - 5)
            if finish_min < DAY_MINUTES:
                occupied.append({"start_min": finish_min,
                                 "end_min": DAY_MINUTES, "label": "活动收摊"})
            suggestions, remaining_runs = suggest_round_windows(
                now_min, occupied, daily_runs, pace)
            shortfall_seconds = remaining_runs * pace
            activity = {"name": "联队战", "target_runs": daily_runs,
                        "planned_runs": daily_runs - remaining_runs,
                        "completed_today": completed,
                        "seconds_per_loop": pace,
                        "remaining_runs": int(raid_plan["runs_needed"]),
                        "event_end_at": now + raid_plan["seconds_to_end"],
                        "occupied": occupied}
            pace_label = (f"{pace // 60} 分 {pace % 60} 秒" if pace >= 60
                          else f"{pace} 秒")
            hint = (f"联队战：今天已记 {completed} 圈，接下来按进度建议"
                    f" {daily_runs} 圈；按本期实测每圈约 {pace_label}"
                    "找远征空窗。只是建议，不会自动开工。")
    else:
        quota = (_daily_quota_seconds(hanafuda_plan, day_end - now)
                 if hanafuda_plan else None)
        if quota:
            occupied = _occupied_segments(expeditions, cfg, hanafuda_team_no)
            suggestions, shortfall_seconds = suggest_windows(now_min, occupied, quota)
        hint = _hanafuda_hint(hanafuda_plan)
    return {
        "now": now,
        "day_start": day_start,
        "markers": [{"time_min": 240, "label": "日课刷新", "kind": "daily_reset"}],
        "expeditions": expeditions,
        "expedition_schedule_enabled": bool(cfg.get("automation", {}).get("enabled")),
        "expedition_help": {
            "teams_out": int(expedition_help.get("teams_out") or 0),
            "available_teams": list(expedition_help.get("available_teams") or []),
        },
        "expedition_suggestions": advice["suggestions"],
        "expedition_advice_note": advice["note"],
        "runs": _run_items(store, active, day_start, day_end, script_labels),
        "hint": hint,
        "activity": activity,
        "suggestions": suggestions,
        "shortfall_seconds": shortfall_seconds,
    }
