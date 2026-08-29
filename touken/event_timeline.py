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

import re
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 老 Python 兜底
    _TZ = timezone(timedelta(hours=8))

UPCOMING_DAYS = 7

# 绑活动的脚本 → 活动名（知识卡/公告候选里的名字）。不在表里的脚本
# （日课、合战场、远征等常驻功能）永远不受活动开关联动影响。
# 南瓜是「战术强化训练」系列活动（南瓜/巧克力大作战等换皮），按系列名收。
SCRIPT_EVENT_MAP = {
    "raid": ["联队战"],
    "pumpkin": ["南瓜大作战", "巧克力大作战", "战术强化训练"],
    "osaka": ["大阪城"],
    "edocastle": ["江户城潜入调查"],
}

# “待确认日期”只承担可规划活动的兜底，不展示景趣、礼包、便利道具等
# 同样带活动时间的公告小节。旧缓存没有 section_title，需靠活动名保守判断；
# 新版爬虫会带完整小节标题，可用“活动/开启”等语义进一步确认。
_PLANNABLE_NAME_RE = re.compile(
    r"江户城|大阪城|联队战|秘宝之里|战术强化训练|大作战|地下城|"
    r"特命调查|夜花夺还|对大侵寇|连队战")
_PLANNABLE_SECTION_RE = re.compile(
    r"活动|开启|调查|联队战|大阪城|秘宝之里|战术强化训练|大作战")
_NON_PLANNABLE_RE = re.compile(
    r"庭院|景趣|登录|礼包|福袋|便利道具|刀装|锻刀|内番|兑换所|商店")


def _is_plannable_candidate(cand: dict) -> bool:
    """公告时间段是否值得进入玩家的活动规划。

    宁可暂不展示模糊的道具/景趣，也不把公告目录编号冒充活动；真正已知的
    活动系列按名字保留，新抓取数据还会结合完整小节标题判断。
    """
    name = str(cand.get("name") or "").strip()
    if not name or name.isdigit() or _NON_PLANNABLE_RE.search(name):
        return False
    if _PLANNABLE_NAME_RE.search(name):
        return True
    section_title = str(cand.get("section_title") or "").strip()
    return bool(section_title
                and not _NON_PLANNABLE_RE.search(section_title)
                and _PLANNABLE_SECTION_RE.search(section_title))


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


def _norm_event_name(value) -> str:
    """活动名归一化：去空白和波浪号。公告候选名常是
    「战术强化训练 ~南瓜大作战~」这种带前缀/装饰的写法。"""
    return re.sub(r"[\s~～]+", "", str(value or ""))


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
            if not _is_plannable_candidate(cand):
                continue
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


def hidden_event_scripts(cards: dict, announcements: list[dict],
                         *, now: datetime | None = None) -> list[str]:
    """概览页「常用功能」的联动隐藏：绑活动的脚本，没有「正在开放」的
    证据就先收起来（封闭式判断，默认藏，证据说话）。

    证据两条路，任一算数：
    1. 知识卡窗口覆盖当前时间（已核实）；
    2. 公告时间候选窗口覆盖当前时间（爬虫抓的，没核实但有明确日期）。
    活动没卡也没候选、日历拉不动 → 都算没证据，藏。
    """
    now = now or datetime.now(_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TZ)

    def _open_now(name: str) -> bool:
        card = (cards or {}).get(name)
        if card:
            start_dt, end_dt, _ = _card_window(card)
            if (start_dt is not None and start_dt <= now
                    and (end_dt is None or now < end_dt)):
                return True
        # 公告候选的名字常带前后缀或波浪号（「战术强化训练 ~南瓜大作战~」），
        # 归一化后按包含关系对，不做精确相等
        target = _norm_event_name(name)
        for ann in announcements or []:
            for cand in ann.get("schedule_candidates") or []:
                cand_name = _norm_event_name(cand.get("name"))
                if not cand_name or not (cand_name in target
                                         or target in cand_name):
                    continue
                start_dt = _parse_dt(cand.get("start_at"))
                end_dt = _parse_dt(cand.get("end_at"))
                if (start_dt is not None and start_dt <= now
                        and (end_dt is None or now < end_dt)):
                    return True
        return False

    return [script for script, names in SCRIPT_EVENT_MAP.items()
            if not any(_open_now(name) for name in names)]
