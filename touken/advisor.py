"""规划建议 MVP：吃现有账本数据，回答「按现在的速度，到目标日能攒多少」。

纯函数模块：不碰 FastAPI、不碰游戏画面。输入是 telemetry 的
resource_ledger(daily_series) 和 osaka.koban_session 事件，输出结构化
建议 + 一句狐狸人话。目标清单存在数据目录的 planning_goals.json。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 老 Python 兜底
    _TZ = timezone(timedelta(hours=8))

from .telemetry import LEDGER_RESOURCES

PLANNING_SCHEMA_VERSION = 1
GOALS_SCHEMA_VERSION = 2  # planning_goals.json 文件格式：{schema_version, goals[]}
RATE_WINDOW_DAYS = 14
EVENT_RATE_WINDOW_DAYS = 60
GOALS_FILENAME = "planning_goals.json"
_MAX_TARGET = 100_000_000

# 这些天进账结构完全不同（活动图/门票/钥匙），和平常不能一锅端
_EVENT_SOURCE_HEADS = ("osaka", "edocastle", "raid", "pumpkin")


def _today() -> date:
    return datetime.now(_TZ).date()


def _resolve_now(today: date | None = None,
                 now: datetime | None = None) -> datetime:
    """生产入口用真实上海时刻；测试显式传 today 时保持中午的确定性。"""
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=_TZ)
        return now.astimezone(_TZ)
    if today is not None:
        return datetime.combine(today, datetime.min.time(), tzinfo=_TZ) \
            + timedelta(hours=12)
    return datetime.now(_TZ)


def _fmt(value: float | int) -> str:
    return f"{int(round(value)):,}"


def _local_date(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), _TZ).date().isoformat()


# ── 目标清单存取 ──


def load_goals(path: Path) -> list[dict]:
    """读目标清单；文件缺失或损坏都当空清单（不炸面板）。
    兼容两代格式：v1 纯数组、v2 {schema_version, goals[]}。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        entries = data.get("goals")
    else:
        entries = data  # v1：顶层就是数组
    if not isinstance(entries, list):
        return []
    goals = [g for g in entries if isinstance(g, dict)
             and g.get("resource") in LEDGER_RESOURCES
             and isinstance(g.get("target"), (int, float))
             and isinstance(g.get("deadline"), str)]
    for goal in goals:
        goal.setdefault("kind", "resource")  # v1 老目标一律是攒钱目标
    return goals


def _save_goals(path: Path, goals: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # v1 → v2 迁移留后路：先备份旧文件，再临时文件 + 原子替换
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            old = None
        if isinstance(old, list):
            shutil.copy2(path, path.with_name(path.name + ".v1.bak"))
    payload = {"schema_version": GOALS_SCHEMA_VERSION, "goals": goals}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


def add_goal(path: Path, *, resource: str, target, deadline: str,
             note: str = "") -> dict:
    """加一条攒钱目标。参数不像话就 ValueError（人话，直接给前端显示）。"""
    if resource not in LEDGER_RESOURCES:
        raise ValueError(f"不认识「{resource}」，目标资源得是账本里的八种之一")
    try:
        target = int(target)
    except (TypeError, ValueError):
        raise ValueError("目标数量得是个整数")
    if not 0 < target <= _MAX_TARGET:
        raise ValueError("目标数量不对劲（得大于 0，也别超过一亿啦）")
    try:
        deadline_date = date.fromisoformat(str(deadline).strip())
    except ValueError:
        raise ValueError("截止日期得是 年-月-日 这样的日期")
    if deadline_date < _today():
        raise ValueError("截止日期已经过去啦，往今天以后挑")
    goals = load_goals(path)
    goal = {
        "id": max([int(g.get("id") or 0) for g in goals], default=0) + 1,
        "kind": "resource",
        "resource": resource,
        "target": target,
        "deadline": deadline_date.isoformat(),
        "note": str(note or "").strip()[:50],
        "created_at": time.time(),
    }
    goals.append(goal)
    _save_goals(path, goals)
    return goal


def delete_goal(path: Path, goal_id: int) -> bool:
    goals = load_goals(path)
    kept = [g for g in goals if int(g.get("id") or 0) != int(goal_id)]
    if len(kept) == len(goals):
        return False
    _save_goals(path, kept)
    return True


# ── 速率与单产估计 ──


def estimate_daily_rates(daily_series: list[dict], *,
                         window_days: int = RATE_WINDOW_DAYS,
                         today: date | None = None,
                         exclude_dates: set[str] | None = None) -> dict:
    """每种资源的日均净收支：窗口内有首末读数的日子取 total_delta 求平均。

    没有完整读数的日子跳过（不知道就是不知道，不按 0 算）。
    exclude_dates 里的日子（活动期）不算进平常速度——活动期间和平常
    的进账是两码事，混在一起预测必歪。
    """
    today = today or _today()
    cutoff = (today - timedelta(days=window_days - 1)).isoformat()
    today_iso = today.isoformat()
    excluded = exclude_dates or set()
    rates = {}
    for name in LEDGER_RESOURCES:
        deltas = [row["total_delta"] for row in daily_series
                  if row.get("resource") == name
                  and row.get("total_delta") is not None
                  and cutoff <= str(row.get("date", "")) <= today_iso
                  and str(row.get("date", "")) not in excluded]
        rates[name] = {
            "daily": (sum(deltas) / len(deltas)) if deltas else None,
            "days_observed": len(deltas),
        }
    return rates


def event_day_dates(attributions: list[dict], *,
                    window_days: int = EVENT_RATE_WINDOW_DAYS,
                    today: date | None = None) -> set[str]:
    """哪些日子是「活动期间」：归因里出现活动来源（大阪城/江户城/联队战/南瓜）的日子。"""
    today = today or _today()
    cutoff = (today - timedelta(days=window_days - 1)).isoformat()
    dates: set[str] = set()
    for item in attributions:
        head = str(item.get("source") or "").split(".", 1)[0].split("/", 1)[0]
        if head not in _EVENT_SOURCE_HEADS:
            continue
        ts = item.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        day = _local_date(ts)
        if cutoff <= day <= today.isoformat():
            dates.add(day)
    return dates


def estimate_event_rates(daily_series: list[dict], event_dates: set[str], *,
                         today: date | None = None) -> dict:
    """活动期间的日均净收支：只取活动日的 total_delta 求平均。

    活动样本本来就少，不设观察天数下限，但 days_observed 会如实带出去，
    让前端/建议文案知道这是几场活动的手气。
    """
    today = today or _today()
    today_iso = today.isoformat()
    rates = {}
    for name in LEDGER_RESOURCES:
        deltas = [row["total_delta"] for row in daily_series
                  if row.get("resource") == name
                  and row.get("total_delta") is not None
                  and str(row.get("date", "")) in event_dates
                  and str(row.get("date", "")) <= today_iso]
        rates[name] = {
            "daily": (sum(deltas) / len(deltas)) if deltas else None,
            "days_observed": len(deltas),
        }
    return rates


def koban_floor_yield(events: list[dict], *,
                      max_sessions: int = 30,
                      window_days: int = RATE_WINDOW_DAYS,
                      now: float | None = None) -> dict | None:
    """从 osaka.koban_session 事件估平均每层小判（按层数加权）。

    events 用 recent_events 的倒序结果即可。只认 window_days 天内的样本——
    大阪城关了之后还拿旧手气换算「每天多挖 N 层」就是空头支票；
    没有新鲜样本就返回 None，建议里不提层数。
    """
    cutoff = (now if now is not None else time.time()) - window_days * 86400
    floors_total = 0.0
    delta_total = 0.0
    sessions = 0
    for event in events[:max_sessions]:
        if not isinstance(event.get("ts"), (int, float)) or event["ts"] < cutoff:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        floors = payload.get("floors")
        delta = payload.get("delta")
        if not isinstance(floors, (int, float)) or floors <= 0:
            continue
        if not isinstance(delta, (int, float)):
            continue
        floors_total += floors
        delta_total += delta
        sessions += 1
    if not sessions or floors_total <= 0:
        return None
    return {"per_floor": delta_total / floors_total, "sessions": sessions}


# ── 目标评估 ──


def _split_goal_days(today: date, deadline: date,
                     event_windows: list[dict] | None) -> tuple[int, int, list[str]]:
    """今天到截止日之间，平常几天、活动期几天（按活动知识卡的开打/收摊日）。

    返回 (平常天数, 活动期天数, 沾边的活动名)。活动期重叠的日子只算一次。
    """
    if isinstance(today, str):
        today = date.fromisoformat(today)
    if isinstance(deadline, str):
        deadline = date.fromisoformat(deadline)
    event_dates: set[date] = set()
    names: list[str] = []
    for window in event_windows or []:
        try:
            start = date.fromisoformat(str(window.get("start_date") or ""))
            end = date.fromisoformat(str(window.get("end_date") or ""))
        except ValueError:
            continue
        # 攒钱从明天算起（days_left 语义），截止日当天也算一天
        start = max(start, today + timedelta(days=1))
        end = min(end, deadline)
        if start > end:
            continue
        if window.get("name"):
            names.append(str(window["name"]))
        day = start
        while day <= end:
            event_dates.add(day)
            day += timedelta(days=1)
    total = max((deadline - today).days, 0)
    return total - len(event_dates), len(event_dates), names


def _window_coverage(today: date, deadline: date,
                     window: dict) -> tuple[int, int]:
    """活动窗口落在目标期内的天数 + 窗口总天数（用来按比例折算窗口影响）。"""
    try:
        start = date.fromisoformat(str(window.get("start_date") or ""))
        end = date.fromisoformat(str(window.get("end_date") or ""))
    except ValueError:
        return 0, 1
    total = max((end - start).days + 1, 1)
    covered_start = max(start, today + timedelta(days=1))
    covered_end = min(end, deadline)
    covered = max((covered_end - covered_start).days + 1, 0)
    return covered, total


def evaluate_goal(goal: dict, *, current: float | None, rate_info: dict,
                  floor_yield: dict | None, today: date | None = None,
                  event_windows: list[dict] | None = None,
                  window_impacts: dict | None = None) -> dict:
    """给一条目标算命。status: done / on_track / behind / expired / unknown。

    rate_info 里 daily 是平常速度、event_daily 是活动期间速度；截止日内
    落在活动期的天数按活动速度估，其余按平常速度。
    """
    today = today or _today()
    resource = goal["resource"]
    target = int(goal["target"])
    deadline = date.fromisoformat(goal["deadline"])
    days_left = (deadline - today).days
    rate = (rate_info or {}).get("daily")
    advice = {
        "id": goal.get("id"),
        "kind": goal.get("kind") or "resource",
        "event": goal.get("event"),
        "resource": resource,
        "target": target,
        "deadline": goal["deadline"],
        "note": goal.get("note") or "",
        "days_left": max(days_left, 0),
        "current": current,
        "rate": rate,
        "event_days": 0,
        "event_rate": None,
        "projected": None,
        "shortfall": None,
        "extra_daily": None,
        "extra_floors": None,
        "status": "unknown",
        "message": "",
    }

    if current is None:
        advice["message"] = (f"还没观察到{resource}的库存，跑一趟任务"
                             "让狐之助看一眼家底再算。")
        return advice
    if current >= target:
        advice["status"] = "done"
        advice["message"] = (f"{resource}已经有 {_fmt(current)}，"
                             f"目标 {_fmt(target)} 稳稳拿下啦🎉")
        return advice
    if days_left <= 0:
        advice["status"] = "expired"
        advice["shortfall"] = target - current
        advice["message"] = (f"截止日到了，{resource}还差 "
                             f"{_fmt(target - current)}。把目标往后挪挪，"
                             "或者这页就翻篇~")
        return advice
    if rate is None:
        advice["message"] = (f"最近 {RATE_WINDOW_DAYS} 天没有{resource}的平常"
                             "收支记录，还算不出速度——再挂几天机就有了。")
        return advice

    normal_days, event_days, event_names = _split_goal_days(today, deadline, event_windows)
    # 有知识卡机理模型的活动窗口：按模型直接算净影响（江户城门票是负数），
    # 不再拿「速率 × 天数」猜（§25）；没模型的窗口维持速率兜底。
    modeled_days = 0
    modeled_delta = 0.0
    modeled_notes = []
    for window in event_windows or []:
        impact = (window_impacts or {}).get(str(window.get("name") or ""))
        if not impact or impact.get("resource") != resource:
            continue
        covered, total_days = _window_coverage(today, deadline, window)
        if not covered:
            continue
        scaled = impact["delta"] * covered / total_days
        modeled_days += covered  # 活动重叠很罕见，真重叠时多算几天认了
        modeled_delta += scaled
        modeled_notes.append(
            f"{window['name']}按知识卡估 {int(round(scaled)):+,}")
    unmodeled_days = max(event_days - modeled_days, 0)
    event_rate = (rate_info or {}).get("event_daily")
    if unmodeled_days and event_rate is None:
        # 活动收益还没实测过，先按平常速度兜底，文案里说清楚
        event_rate = rate
        event_guessed = True
    else:
        event_guessed = False
    advice["event_days"] = event_days
    advice["event_rate"] = event_rate if unmodeled_days else None
    advice["event_modeled"] = modeled_notes
    projected = (current + rate * normal_days
                 + (event_rate or 0) * unmodeled_days + modeled_delta)
    advice["projected"] = int(round(projected))
    advice["shortfall"] = max(0, int(round(target - projected)))
    if event_days:
        if unmodeled_days:
            pace = f"平常每天 {int(round(rate)):+,}、活动期每天 {int(round(event_rate)):+,}"
        else:
            pace = f"平常每天 {int(round(rate)):+,}"
        event_note = f"其中 {event_days} 天撞上{'、'.join(event_names) or '活动'}，"
        if modeled_notes:
            event_note += "；".join(modeled_notes) + "。"
        if unmodeled_days:
            event_note += ("活动期的收益还没实测过，先按平常速度估。"
                           if event_guessed else "按活动期间的速度另算。")
    else:
        pace = f"平常每天 {int(round(rate)):+,}"
        event_note = ""
    if projected >= target:
        advice["status"] = "on_track"
        advice["message"] = (f"按{pace}的速度，到 {goal['deadline']}"
                             f"（还有 {days_left} 天）能攒到 {_fmt(projected)}，"
                             f"目标 {_fmt(target)} 稳的。{event_note}")
        return advice

    advice["status"] = "behind"
    extra_daily = (target - projected) / days_left
    advice["extra_daily"] = int(round(extra_daily))
    message = (f"按{pace}的速度，到 {goal['deadline']}"
               f"（还有 {days_left} 天）大概攒到 {_fmt(projected)}，"
               f"离目标还差 {_fmt(target - projected)}——"
               f"剩下 {days_left} 天每天得多攒 {_fmt(extra_daily)}。{event_note}")
    if (resource == "小判" and floor_yield
            and floor_yield.get("per_floor", 0) > 0):
        floors = extra_daily / floor_yield["per_floor"]
        advice["extra_floors"] = int(round(floors)) or 1
        message += (f"按你最近挖地的手气（每层约 "
                    f"{floor_yield['per_floor']:.0f} 小判），"
                    f"≈ 每天多挖 {advice['extra_floors']} 层大阪城。")
    advice["message"] = message
    return advice


def _current_balances(store, now: float) -> dict:
    """账本里每种资源的最新余额（closing 优先，opening 兜底）。"""
    ledger = store.resource_ledger(now - EVENT_RATE_WINDOW_DAYS * 86400, now)
    current = {}
    for row in ledger.get("per_resource", []):
        value = row.get("closing")
        current[row.get("resource")] = value if value is not None else row.get("opening")
    return current


def _upsert_event_goal(path: Path, *, event: str, target: int,
                       deadline: str, note: str) -> dict:
    """每个活动至多一条预算目标；预算变化时原位更新，不重复追加。"""
    if not 0 < int(target) <= _MAX_TARGET:
        raise ValueError("活动预算不对劲，暂时不能立目标")
    goals = load_goals(path)
    goal = next((item for item in goals
                 if item.get("kind") == "event"
                 and item.get("event") == event), None)
    if goal is None:
        goal = {
            "id": max([int(item.get("id") or 0) for item in goals], default=0) + 1,
            "kind": "event",
            "event": event,
            "resource": "小判",
            "target": int(target),
            "deadline": deadline,
            "note": note[:50],
            "created_at": time.time(),
        }
        goals.append(goal)
    else:
        goal.update({"resource": "小判", "target": int(target),
                     "deadline": deadline, "note": note[:50],
                     "updated_at": time.time()})
    _save_goals(path, goals)
    return dict(goal)


def add_event_goal(store, goals_path: Path, event: str, *,
                   today: date | None = None,
                   now: datetime | None = None) -> dict:
    """把活动预算立成攒钱目标。语义：目标是「预算本身」，家底会拿来抵；
    不是旧前端那套「现有余额 + 预算」（那等于让人家多攒一倍）。
    家底已够就不立目标，直接报充足。预算数字只能这里算，前端不许自己拼。
    """
    now_dt = _resolve_now(today, now)
    today = today or now_dt.date()
    cards = load_event_cards(Path(goals_path).parent)
    if event not in cards:
        raise ValueError(f"不认识活动「{event}」")
    card = cards[event]
    abacus = event_abacus(event, card,
                          measured=measured_keys_per_run(store), today=today,
                          now=now_dt)
    cost = abacus.get("koban_cost")
    if cost is None:
        raise ValueError(abacus.get("message") or "这场活动的预算还算不出来")
    current = _current_balances(store, now_dt.timestamp()).get("小判")
    deadline = card.get("start_date") or card.get("end_date")
    if not deadline:
        raise ValueError("这张活动卡还没日期，立不了目标")
    start_dt, _, _ = _card_window(card)
    if ((start_dt is not None and now_dt >= start_dt)
            or date.fromisoformat(deadline) < today) and card.get("end_date"):
        deadline = card["end_date"]  # 已开打：钱在收摊前备齐就行
    if date.fromisoformat(deadline) < today:
        raise ValueError("这场活动已经结束，不能再立预算目标")
    result = {"sufficient": None, "goal": None, "koban_cost": cost,
              "available_now": current, "shortfall": None}
    if cost <= 0:
        result["shortfall"] = 0
        result["sufficient"] = True
    elif current is not None:
        result["shortfall"] = max(0, int(cost - current))
        result["sufficient"] = result["shortfall"] == 0
    existing = next((item for item in load_goals(goals_path)
                     if item.get("kind") == "event"
                     and item.get("event") == event), None)
    if result["sufficient"] and existing is None:
        return result
    result["goal"] = _upsert_event_goal(
        goals_path, event=event, target=cost, deadline=deadline,
        note=f"{event}门票预算")
    return result


def get_planning(store, goals_path: Path, *,
                 today: date | None = None,
                 now: datetime | None = None) -> dict:
    """汇总入口：store 是 telemetry 仓库（resource_ledger / recent_events）。"""
    now_dt = _resolve_now(today, now)
    today = today or now_dt.date()
    now_ts = now_dt.timestamp()
    # 平常速度看最近 14 天；活动速度要回望更久，老活动样本也是样本
    ledger = store.resource_ledger(now_ts - EVENT_RATE_WINDOW_DAYS * 86400,
                                   now_ts)
    current = {}
    for row in ledger.get("per_resource", []):
        value = row.get("closing")
        current[row.get("resource")] = value if value is not None else row.get("opening")
    event_dates = event_day_dates(ledger.get("attributions", []), today=today)
    normal_rates = estimate_daily_rates(ledger.get("daily_series", []),
                                        today=today, exclude_dates=event_dates)
    event_rates = estimate_event_rates(ledger.get("daily_series", []),
                                       event_dates, today=today)
    rates = {}
    for name in LEDGER_RESOURCES:
        rates[name] = {**normal_rates[name],
                       "event_daily": event_rates[name]["daily"],
                       "event_days_observed": event_rates[name]["days_observed"]}
    floor_yield = koban_floor_yield(
        store.recent_events(limit=50, event_type="osaka.koban_session"),
        now=now_ts)
    cards = load_event_cards(Path(goals_path).parent)
    event_windows = [{"name": name, "start_date": card.get("start_date"),
                      "end_date": card.get("end_date")}
                     for name, card in cards.items()
                     if card.get("start_date") and card.get("end_date")]
    measured = measured_keys_per_run(store)
    # §25：有机理模型的活动按知识卡直接算窗口净影响，喂给目标评估
    window_impacts = {}
    for name, card in cards.items():
        impact = window_impact(name, card, measured_keys=measured,
                               floor_yield=floor_yield, today=today,
                               now=now_dt)
        if impact:
            window_impacts[name] = impact
    goals = [evaluate_goal(goal, current=current.get(goal["resource"]),
                           rate_info=rates.get(goal["resource"]),
                           floor_yield=floor_yield, today=today,
                           event_windows=event_windows,
                           window_impacts=window_impacts)
             for goal in load_goals(goals_path)]
    abacuses = [event_abacus(name, card, measured=measured, today=today,
                             now=now_dt)
                for name, card in cards.items()]
    # 预算 vs 家底的判定也在服务端做：前端只展示，不许自己拼目标数字
    koban_now = current.get("小判")
    for abacus in abacuses:
        cost = abacus.get("koban_cost")
        abacus["available_now"] = koban_now
        if cost is None or koban_now is None:
            abacus["sufficient"] = None
            abacus["shortfall"] = None
        else:
            abacus["shortfall"] = max(0, int(cost - koban_now))
            abacus["sufficient"] = abacus["shortfall"] == 0
    return {
        "schema_version": PLANNING_SCHEMA_VERSION,
        "generated_at": now_ts,
        "today": today.isoformat(),
        "rate_window_days": RATE_WINDOW_DAYS,
        "event_rate_window_days": EVENT_RATE_WINDOW_DAYS,
        "rates": rates,
        "current": current,
        "koban_per_floor": floor_yield,
        "goals": goals,
        "events": abacuses,
    }


# ── 活动算盘（江户城这类门票/钥匙活动的预算） ──

EVENTS_META_LOCAL = "events_meta.local.json"
_DATA_DIR = Path(__file__).resolve().parent / "data"


def load_event_cards(status_dir: Path) -> dict:
    """活动知识卡：仓库默认卡 + 数据目录本地覆盖（老大的场均预估存本地）。"""
    cards = {}
    try:
        cards = json.loads((_DATA_DIR / "events_meta.json")
                           .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        local = json.loads((Path(status_dir) / EVENTS_META_LOCAL)
                           .read_text(encoding="utf-8"))
        for name, patch in local.items():
            if isinstance(patch, dict) and name in cards:
                cards[name].update(patch)
    except (OSError, ValueError):
        pass
    return cards


def save_key_estimate(status_dir: Path, event: str, keys_per_run) -> dict:
    """保存老大手填的场均钥匙预估（实测数据来了会被实测覆盖显示）。"""
    cards = load_event_cards(status_dir)
    if event not in cards:
        raise ValueError(f"不认识活动「{event}」")
    try:
        estimate = float(keys_per_run)
    except (TypeError, ValueError):
        raise ValueError("场均钥匙得是个数")
    if not 0 < estimate <= 200:
        raise ValueError("场均钥匙不对劲（大于 0，别超过 200）")
    path = Path(status_dir) / EVENTS_META_LOCAL
    try:
        local = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        local = {}
    local.setdefault(event, {})["est_keys_per_run"] = estimate
    path.write_text(json.dumps(local, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return cards[event]


def measured_keys_per_run(store, *, limit: int = 50) -> dict | None:
    """实测场均钥匙：edocastle.run_completed 事件（江户城流程产出）的平均。"""
    events = store.recent_events(limit=limit, event_type="edocastle.run_completed")
    keys = []
    for event in events:
        payload = event.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("keys"), (int, float)) \
                and payload["keys"] > 0:
            keys.append(payload["keys"])
    if not keys:
        return None
    return {"per_run": sum(keys) / len(keys), "runs": len(keys)}


def _ticket_cap(card: dict) -> int:
    return (int(card.get("ticket_cap") or 0)
            or int(card.get("daily_free_tickets") or 0) // 2)


def _card_window(card: dict):
    """活动窗口：(start_dt, end_dt, precise)。优先精确时刻，退回日期按整天。"""
    try:
        if card.get("start_at") and card.get("end_at"):
            return (datetime.fromisoformat(str(card["start_at"])),
                    datetime.fromisoformat(str(card["end_at"])), True)
        if card.get("start_date") and card.get("end_date"):
            start = date.fromisoformat(str(card["start_date"]))
            end = date.fromisoformat(str(card["end_date"]))
            return (datetime.combine(start, datetime.min.time(), tzinfo=_TZ),
                    datetime.combine(end, datetime.max.time(), tzinfo=_TZ), False)
    except ValueError:
        pass
    return None, None, False


def _count_free_tickets(card: dict, start_dt: datetime, end_dt: datetime) -> int:
    """按回满点（默认每天 5:00/17:00）与窗口的交集数白票。

    回满是重置不是累加：回满时刻起 12 小时内落在活动窗口里的那段，
    这 6 枚令牌才花得出去。开打前最近一次回满（如 8-27 05:00）的存货
    靠交集自然算进来；收摊瞬间的回满（9-10 05:00）零交集自然排除。
    """
    cap = _ticket_cap(card)
    if not cap:
        return 0
    hours = card.get("refill_hours") or [5, 17]
    count = 0
    day = start_dt.date() - timedelta(days=1)
    while day <= end_dt.date():
        for hour in hours:
            refill = (datetime.combine(day, datetime.min.time(), tzinfo=_TZ)
                      + timedelta(hours=hour))
            if min(refill + timedelta(hours=12), end_dt) > max(refill, start_dt):
                count += 1
        day += timedelta(days=1)
    return count * cap


def event_abacus(name: str, card: dict, *, measured: dict | None,
                 today: date | None = None, now: datetime | None = None) -> dict:
    """江户城式算盘：钥匙总量 ÷ 场均 = 圈数 → 扣白票 → 补票钱。

    实测场均优先，其次老大手填预估，都没有就老实说还没数。
    """
    now_dt = _resolve_now(today, now)
    today = today or now_dt.date()
    keys_total = int(card.get("keys_total") or 0)
    ticket_price = int(card.get("ticket_price") or 0)
    daily_free = int(card.get("daily_free_tickets") or 0)
    abacus = {
        "event": name,
        "start_date": card.get("start_date"),
        "end_date": card.get("end_date"),
        "keys_total": keys_total,
        "boxes": card.get("boxes"),
        "ticket_price": ticket_price,
        "daily_free_tickets": daily_free,
        "note": card.get("note") or "",
        "keys_per_run": None,
        "keys_source": None,
        "runs_needed": None,
        "free_runs": None,
        "paid_tickets": None,
        "koban_cost": None,
        "days_left": None,
        "message": "",
    }

    if measured:
        keys_per_run, source = measured["per_run"], "measured"
    elif card.get("est_keys_per_run"):
        keys_per_run, source = float(card["est_keys_per_run"]), "estimate"
    else:
        keys_per_run, source = None, None
    abacus["keys_per_run"] = round(keys_per_run, 1) if keys_per_run else None
    abacus["keys_source"] = source

    if not keys_total or not ticket_price:
        abacus["message"] = "这张活动卡还缺数据，回头补。"
        return abacus
    if keys_per_run is None:
        abacus["message"] = (
            f"四座宝库全开要 {keys_total:,} 把钥匙（{card.get('boxes')} 箱 × "
            f"{card.get('keys_per_box')} 把）。场均几把还没数——你可以先填个估计，"
            "或者等开战狐之助实测几圈就会算了。")
        return abacus

    import math
    runs = math.ceil(keys_total / keys_per_run)
    abacus["runs_needed"] = runs
    label = "实测" if source == "measured" else "估计"

    start_dt, end_dt, precise = _card_window(card)
    if end_dt is None:
        # 不知道结束日：算不出白票能顶多少，给全自费上限
        abacus["koban_cost"] = runs * ticket_price
        abacus["message"] = (
            f"按{label}场均 {keys_per_run:.1f} 把钥匙，全开四座宝库要打 "
            f"{runs} 圈。门票 {ticket_price} 小判/张，全自费最坏 "
            f"{runs * ticket_price:,} 小判；每天白送 {daily_free} 张票，"
            "排进日常就能省一大截。等结束日定了狐之助再算细账。")
        return abacus

    effective_start = max(start_dt, now_dt) if start_dt else now_dt
    days_left = max((end_dt.date() - effective_start.date()).days + 1, 0)
    abacus["days_left"] = days_left
    if precise:
        free_runs = _count_free_tickets(card, effective_start, end_dt)
        free_desc = f"回满 {free_runs // _ticket_cap(card)} 次 × {_ticket_cap(card)} 枚"
    else:
        free_runs = daily_free * days_left
        free_desc = f"每天 {daily_free} 张 × {days_left} 天"
    abacus["free_runs"] = free_runs
    paid = max(0, runs - free_runs)
    abacus["paid_tickets"] = paid
    abacus["koban_cost"] = paid * ticket_price
    end_label = card.get("end_at") or card["end_date"]
    if precise and isinstance(end_label, str) and "T" in end_label:
        end_label = end_label.replace("T", " ")[:16]
    if paid == 0:
        abacus["message"] = (
            f"按{label}场均 {keys_per_run:.1f} 把，全开要打 {runs} 圈——"
            f"到 {end_label} 的白票（{free_desc}）就够用了，"
            "一个小判都不用花🎉")
    else:
        abacus["message"] = (
            f"按{label}场均 {keys_per_run:.1f} 把，全开要打 {runs} 圈；"
            f"到 {end_label}（还剩 {days_left} 天）白票能顶 "
            f"{free_runs} 圈，还得补 {paid} 张票 ≈ {paid * ticket_price:,} 小判。")
    return abacus


def window_impact(name: str, card: dict, *, measured_keys: dict | None = None,
                  floor_yield: dict | None = None,
                  today: date | None = None,
                  now: datetime | None = None) -> dict | None:
    """按知识卡机理算活动窗口的资源净影响（§25 活动感知规划）。

    返回 {"resource", "delta", "detail"} 或 None（没模型/缺数据/没日期）。
    delta 正数 = 活动净赚，负数 = 活动净花（门票钱）。没数据时返回 None，
    让目标评估退回速率兜底——宁可少说，不许瞎编。
    """
    now_dt = _resolve_now(today, now)
    today = today or now_dt.date()
    mechanics = card.get("mechanics")
    if mechanics == "edocastle":
        abacus = event_abacus(name, card, measured=measured_keys, today=today,
                              now=now_dt)
        cost = abacus.get("koban_cost")
        if cost is None:
            return None
        return {"resource": "小判", "delta": -int(cost),
                "detail": f"{name}门票钱"}
    if mechanics == "osaka":
        per_floor = (floor_yield or {}).get("per_floor")
        if not per_floor:
            return None
        try:
            start = date.fromisoformat(str(card.get("start_date")))
            end = date.fromisoformat(str(card.get("end_date")))
        except ValueError:
            return None
        days = max((end - max(today, start)).days + 1, 0)
        if not days:
            return None
        hours = float(card.get("hours_per_night") or 6)
        lap_min = float(card.get("lap_minutes") or 5)
        if lap_min <= 0:
            return None
        floors = hours * 60 / lap_min * days
        return {"resource": "小判", "delta": int(round(floors * per_floor)),
                "detail": f"{name}挂机 {days} 晚"}
    return None
