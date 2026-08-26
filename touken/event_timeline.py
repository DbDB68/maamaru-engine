"""事件时间轴：知识卡（已核实）+ 公告候选（待确认）合成一根轴。

产品定调（2026-08-26 牛老师设计稿）：打开页面立刻知道
「现在打什么、什么时候结束、下一个活动什么时候来」。

分组规则：
- ongoing：进行中置顶，按谁最先结束排序
- upcoming：7 天内开始排第二，按开始时间排序
- later：更远的活动（前端做紧凑行）
- unverified：公告正文抓的时间候选，没核实前沉底，不进正式轴
- 已结束的不上轴；一场活动只出现一次（同时带开始和结束）

纯函数，不碰网络和文件；server 端点负责凑齐输入。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 老 Python 兜底
    _TZ = timezone(timedelta(hours=8))

UPCOMING_DAYS = 7


def _parse_dt(value) -> datetime | None:
    """ISO 带时刻 → datetime；没有就 None。"""
    if not value or not isinstance(value, str) or "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(value) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _card_window(card: dict):
    """卡片 → (start_dt, end_dt 不含, precise)。
    只有日期的卡：开始日 00:00 起、结束日全天算进行中（到次日 00:00）。
    啥都没有 → (None, None, False)。"""
    start_dt = _parse_dt(card.get("start_at"))
    end_dt = _parse_dt(card.get("end_at"))
    precise = start_dt is not None or end_dt is not None
    if start_dt is None:
        start = _parse_date(card.get("start_date"))
        start_dt = datetime.combine(start, datetime.min.time(),
                                    tzinfo=_TZ) if start else None
    if end_dt is None:
        end = _parse_date(card.get("end_date"))
        end_dt = datetime.combine(end + timedelta(days=1),
                                  datetime.min.time(),
                                  tzinfo=_TZ) if end else None
    return start_dt, end_dt, precise


def _entry(name: str, card: dict, abacus: dict | None,
           start_dt: datetime, end_dt: datetime, precise: bool,
           now: datetime) -> dict:
    entry = {
        "name": name,
        "precise": precise,
        "start_at": start_dt.isoformat() if precise and card.get("start_at") else None,
        "end_at": end_dt.isoformat() if precise and card.get("end_at") else None,
        "start_date": start_dt.date().isoformat(),
        "end_date": (end_dt - timedelta(seconds=1)).date().isoformat()
        if end_dt else None,
        "note": card.get("note") or "",
        "budget": None,
    }
    if end_dt:
        # 只剩几天按「显示的结束日」算：date-only 卡的内部边界是次日 00:00，
        # 直接拿它算会多报一天
        end_display = (end_dt - timedelta(seconds=1)).date()
        entry["days_left"] = max((end_display - now.date()).days, 0)
    else:
        entry["days_left"] = None
    if start_dt > now:
        entry["days_until_start"] = (start_dt.date() - now.date()).days
    if abacus:
        entry["budget"] = {
            "koban_cost": abacus.get("koban_cost"),
            "available_now": abacus.get("available_now"),
            "shortfall": abacus.get("shortfall"),
            "sufficient": abacus.get("sufficient"),
            "message": abacus.get("message") or "",
        }
    return entry


def build_timeline(cards: dict, abacuses: list[dict],
                   announcements: list[dict], *,
                   now: datetime | None = None) -> dict:
    """合成时间轴。cards/abacuses 来自 advisor，announcements 来自爬虫。"""
    now = now or datetime.now(_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TZ)
    upcoming_limit = now + timedelta(days=UPCOMING_DAYS)
    abacus_by_name = {a.get("event"): a for a in abacuses or []}

    ongoing, upcoming, later = [], [], []
    for name, card in (cards or {}).items():
        start_dt, end_dt, precise = _card_window(card)
        if start_dt is None:
            continue  # 没日期的卡（休眠卡）不上轴
        if end_dt is not None and end_dt <= now:
            continue  # 已结束
        entry = _entry(name, card, abacus_by_name.get(name),
                       start_dt, end_dt, precise, now)
        if start_dt <= now:
            ongoing.append(entry)
        elif start_dt <= upcoming_limit:
            upcoming.append(entry)
        else:
            later.append(entry)
    ongoing.sort(key=lambda e: (e["end_at"] or e["end_date"] or "9999"))
    upcoming.sort(key=lambda e: (e["start_at"] or e["start_date"]))
    later.sort(key=lambda e: (e["start_at"] or e["start_date"]))

    # 待确认：公告候选里，名字没对上任何知识卡的才算「没核实」；
    # 已结束的候选不上轴；同一活动在多篇公告重复出现只留一条
    unverified = []
    seen = set()
    for ann in announcements or []:
        for cand in ann.get("schedule_candidates") or []:
            if cand.get("name") and cand["name"] in (cards or {}):
                continue  # 已有正式卡，不重复进待确认
            end_dt = _parse_dt(cand.get("end_at"))
            if end_dt is not None and end_dt <= now:
                continue  # 早结束了，确认它也没意义
            key = (cand.get("name"), cand.get("start_at"), cand.get("end_at"))
            if key in seen:
                continue
            seen.add(key)
            unverified.append({
                "name": cand.get("name"),
                "section": cand.get("section"),
                "start_at": cand.get("start_at"),
                "end_at": cand.get("end_at"),
                "announcement": ann.get("title"),
                "url": ann.get("url"),
            })

    return {
        "generated_at": now.isoformat(),
        "ongoing": ongoing,
        "upcoming": upcoming,
        "later": later,
        "unverified": unverified,
    }
