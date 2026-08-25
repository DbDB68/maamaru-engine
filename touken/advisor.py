"""规划建议 MVP：吃现有账本数据，回答「按现在的速度，到目标日能攒多少」。

纯函数模块：不碰 FastAPI、不碰游戏画面。输入是 telemetry 的
resource_ledger(daily_series) 和 osaka.koban_session 事件，输出结构化
建议 + 一句狐狸人话。目标清单存在数据目录的 planning_goals.json。
"""
from __future__ import annotations

import json
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
RATE_WINDOW_DAYS = 14
GOALS_FILENAME = "planning_goals.json"
_MAX_TARGET = 100_000_000


def _today() -> date:
    return datetime.now(_TZ).date()


def _fmt(value: float | int) -> str:
    return f"{int(round(value)):,}"


# ── 目标清单存取 ──


def load_goals(path: Path) -> list[dict]:
    """读目标清单；文件缺失或损坏都当空清单（不炸面板）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [g for g in data if isinstance(g, dict)
            and g.get("resource") in LEDGER_RESOURCES
            and isinstance(g.get("target"), (int, float))
            and isinstance(g.get("deadline"), str)]


def _save_goals(path: Path, goals: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(goals, ensure_ascii=False, indent=2),
                    encoding="utf-8")


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
                         today: date | None = None) -> dict:
    """每种资源的日均净收支：窗口内有首末读数的日子取 total_delta 求平均。

    没有完整读数的日子跳过（不知道就是不知道，不按 0 算）。
    """
    today = today or _today()
    cutoff = (today - timedelta(days=window_days - 1)).isoformat()
    today_iso = today.isoformat()
    rates = {}
    for name in LEDGER_RESOURCES:
        deltas = [row["total_delta"] for row in daily_series
                  if row.get("resource") == name
                  and row.get("total_delta") is not None
                  and cutoff <= str(row.get("date", "")) <= today_iso]
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


def evaluate_goal(goal: dict, *, current: float | None, rate_info: dict,
                  floor_yield: dict | None, today: date | None = None) -> dict:
    """给一条目标算命。status: done / on_track / behind / expired / unknown。"""
    today = today or _today()
    resource = goal["resource"]
    target = int(goal["target"])
    deadline = date.fromisoformat(goal["deadline"])
    days_left = (deadline - today).days
    rate = (rate_info or {}).get("daily")
    advice = {
        "id": goal.get("id"),
        "resource": resource,
        "target": target,
        "deadline": goal["deadline"],
        "note": goal.get("note") or "",
        "days_left": max(days_left, 0),
        "current": current,
        "rate": rate,
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
        advice["message"] = (f"最近 {RATE_WINDOW_DAYS} 天没有{resource}的完整"
                             "收支记录，还算不出速度——再挂几天机就有了。")
        return advice

    projected = current + rate * days_left
    advice["projected"] = int(round(projected))
    advice["shortfall"] = max(0, int(round(target - projected)))
    pace = f"每天 {int(round(rate)):+,}"
    if projected >= target:
        advice["status"] = "on_track"
        advice["message"] = (f"按最近 {pace} 的速度，到 {goal['deadline']}"
                             f"（还有 {days_left} 天）能攒到 {_fmt(projected)}，"
                             f"目标 {_fmt(target)} 稳的。")
        return advice

    advice["status"] = "behind"
    extra_daily = (target - current) / days_left - rate
    advice["extra_daily"] = int(round(extra_daily))
    message = (f"照现在的速度（{pace}），到 {goal['deadline']}"
               f"（还有 {days_left} 天）大概攒到 {_fmt(projected)}，"
               f"离目标还差 {_fmt(target - projected)}——"
               f"剩下 {days_left} 天每天得多攒 {_fmt(extra_daily)}。")
    if (resource == "小判" and floor_yield
            and floor_yield.get("per_floor", 0) > 0):
        floors = extra_daily / floor_yield["per_floor"]
        advice["extra_floors"] = int(round(floors)) or 1
        message += (f"按你最近挖地的手气（每层约 "
                    f"{floor_yield['per_floor']:.0f} 小判），"
                    f"≈ 每天多挖 {advice['extra_floors']} 层大阪城。")
    advice["message"] = message
    return advice


def get_planning(store, goals_path: Path, *,
                 today: date | None = None) -> dict:
    """汇总入口：store 是 telemetry 仓库（resource_ledger / recent_events）。"""
    today = today or _today()
    now = time.time()
    ledger = store.resource_ledger(now - RATE_WINDOW_DAYS * 86400, now)
    current = {}
    for row in ledger.get("per_resource", []):
        value = row.get("closing")
        current[row.get("resource")] = value if value is not None else row.get("opening")
    rates = estimate_daily_rates(ledger.get("daily_series", []), today=today)
    floor_yield = koban_floor_yield(
        store.recent_events(limit=50, event_type="osaka.koban_session"))
    goals = [evaluate_goal(goal, current=current.get(goal["resource"]),
                           rate_info=rates.get(goal["resource"]),
                           floor_yield=floor_yield, today=today)
             for goal in load_goals(goals_path)]
    measured = measured_keys_per_run(store)
    cards = load_event_cards(Path(goals_path).parent)
    abacuses = [event_abacus(name, card, measured=measured, today=today)
                for name, card in cards.items()]
    return {
        "schema_version": PLANNING_SCHEMA_VERSION,
        "generated_at": now,
        "today": today.isoformat(),
        "rate_window_days": RATE_WINDOW_DAYS,
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


def event_abacus(name: str, card: dict, *, measured: dict | None,
                 today: date | None = None) -> dict:
    """江户城式算盘：钥匙总量 ÷ 场均 = 圈数 → 扣白票 → 补票钱。

    实测场均优先，其次老大手填预估，都没有就老实说还没数。
    """
    today = today or _today()
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

    end_date = None
    if card.get("end_date"):
        try:
            end_date = date.fromisoformat(card["end_date"])
        except ValueError:
            pass
    if end_date is None:
        # 不知道结束日：算不出白票能顶多少，给全自费上限
        abacus["koban_cost"] = runs * ticket_price
        abacus["message"] = (
            f"按{label}场均 {keys_per_run:.1f} 把钥匙，全开四座宝库要打 "
            f"{runs} 圈。门票 {ticket_price} 小判/张，全自费最坏 "
            f"{runs * ticket_price:,} 小判；每天白送 {daily_free} 张票，"
            "排进日常就能省一大截。等结束日定了狐之助再算细账。")
        return abacus

    start = date.fromisoformat(card["start_date"]) if card.get("start_date") else today
    days_left = (end_date - max(today, start)).days + 1
    abacus["days_left"] = max(days_left, 0)
    free_runs = daily_free * max(days_left, 0)
    abacus["free_runs"] = free_runs
    paid = max(0, runs - free_runs)
    abacus["paid_tickets"] = paid
    abacus["koban_cost"] = paid * ticket_price
    if paid == 0:
        abacus["message"] = (
            f"按{label}场均 {keys_per_run:.1f} 把，全开要打 {runs} 圈——"
            f"到 {card['end_date']} 的白票（每天 {daily_free} 张 × "
            f"{max(days_left, 0)} 天）就够用了，一个小判都不用花🎉")
    else:
        abacus["message"] = (
            f"按{label}场均 {keys_per_run:.1f} 把，全开要打 {runs} 圈；"
            f"到 {card['end_date']}（{max(days_left, 0)} 天）白票能顶 "
            f"{free_runs} 圈，还得补 {paid} 张票 ≈ {paid * ticket_price:,} 小判。")
    return abacus
