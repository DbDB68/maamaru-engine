"""远征建议引擎 v2：家底缺什么 → 今天丢哪几队、去哪些图。

玩家每天只做一个决定：丢几队出门（0–5）；"哪些队可以丢"是长期偏好。
v2 起建议不再依赖 preset 排班投影——引擎按缺口排序直接算班
（图/队伍/时刻自描述），采纳 = 写一条自描述 forced 记录
（expedition_day_choices.json v2），排班总开关关着也单独走状态机，
点了才跑，绝不自动执行。

缺口排序：resource_watch.limiting（锻刀短板，先卡炉的在前）→ 小判
（有目标缺口时）→ 剩下的按锻刀余量从少到多补齐（最终兜底小判）。
拿不到 resource_watch（没盘点过）时给空建议 + 原因，不瞎猜。
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from touken.runtime_paths import STATE_DIR

PREFS_PATH = STATE_DIR / "expedition_help_prefs.json"
PREFS_VERSION = 1
DEFAULT_TEAMS_OUT = 1
DEFAULT_AVAILABLE_TEAMS = [1, 4, 5]
MAX_TEAMS_OUT = 5
VALID_TEAMS = (1, 2, 3, 4, 5)

TEAM_NAMES = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}
FORGE_RESOURCES = ("木炭", "玉钢", "冷却材", "砥石")
KOBAN = "小判"

_MAPS_PATH = (Path(__file__).resolve().parent.parent
              / "touken" / "data" / "expedition_maps.json")
SITUATION_FILENAME = "youzu_home_situation.json"

_WRITE_LOCK = threading.Lock()


# ── 长期偏好：今天丢几队 + 哪些队可以丢 ──


def _normalize_prefs(value) -> dict:
    """宽容归一：缺键用默认、坏值回退，永远吐得出能用的偏好。"""
    if not isinstance(value, dict):
        value = {}
    try:
        teams_out = int(value.get("teams_out", DEFAULT_TEAMS_OUT))
    except (TypeError, ValueError):
        teams_out = DEFAULT_TEAMS_OUT
    teams_out = max(0, min(MAX_TEAMS_OUT, teams_out))
    raw_teams = value.get("available_teams", DEFAULT_AVAILABLE_TEAMS)
    teams: list[int] = []
    if isinstance(raw_teams, list):
        for item in raw_teams:
            try:
                team = int(item)
            except (TypeError, ValueError):
                continue
            if team in VALID_TEAMS and team not in teams:
                teams.append(team)
    if not teams:
        teams = list(DEFAULT_AVAILABLE_TEAMS)
    return {"version": PREFS_VERSION, "teams_out": teams_out,
            "available_teams": sorted(teams)}


def load_prefs(path: Path = PREFS_PATH) -> dict:
    """坏文件当没有；不存在的键用默认。只读不写。"""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _normalize_prefs(None)
    if not isinstance(value, dict) or value.get("version") != PREFS_VERSION:
        return _normalize_prefs(None)
    return _normalize_prefs(value)


def _as_count(value, label: str) -> int:
    """JSON 数字 → 整数；布尔/字符串/小数一律拒。"""
    if isinstance(value, bool):
        raise ValueError(f"{label}得是个数")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{label}得是个数")


def save_prefs(*, teams_out, available_teams,
               path: Path = PREFS_PATH) -> dict:
    """校验落盘（原子替换 + 备份上一版）；参数不合法抛 ValueError。"""
    teams_out = _as_count(teams_out, "丢几队")
    if not 0 <= teams_out <= MAX_TEAMS_OUT:
        raise ValueError(f"丢几队要在 0 到 {MAX_TEAMS_OUT} 之间")
    if not isinstance(available_teams, list):
        raise ValueError("可丢的队伍得是一串队号")
    teams: list[int] = []
    for item in available_teams:
        team = _as_count(item, "队号")
        if team not in VALID_TEAMS:
            raise ValueError(f"队伍只有一到五，{team} 不存在")
        if team not in teams:
            teams.append(team)
    prefs = _normalize_prefs({"version": PREFS_VERSION,
                              "teams_out": teams_out,
                              "available_teams": sorted(teams)})
    path = Path(path)
    with _WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(prefs, ensure_ascii=False, indent=2)
                             + "\n", encoding="utf-8")
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        temporary.replace(path)
    return prefs


# ── 数据装载 ──


def load_maps(path: Path = _MAPS_PATH) -> dict:
    """远征图数据：code → meta（含各资源收益/时长/等级条件）。坏文件当空。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    maps = data.get("maps")
    return maps if isinstance(maps, dict) else {}


def party_levels_from_situation(path: Path) -> dict | None:
    """本丸近况 → {队号: {sum, max, count, names}}；读不到（没同步过）返回 None。

    有了它才能核远征图的 total_level/level_req 和刀种要求；没有就只做
    收益匹配，建议里注明等级没核。names 是成员名册名（简体中文，极化带
    「·极」后缀），刀种资格门用。
    """
    try:
        situation = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    parties = situation.get("parties")
    if not isinstance(parties, list):
        return None
    levels: dict[int, dict] = {}
    for party in parties:
        if not isinstance(party, dict):
            continue
        try:
            team = int(party.get("party_no"))
        except (TypeError, ValueError):
            continue
        rows = [m for m in party.get("members") or [] if isinstance(m, dict)]
        members = [int(m["level"]) for m in rows
                   if isinstance(m.get("level"), (int, float))]
        if not members:
            continue
        levels[team] = {"sum": sum(members), "max": max(members),
                        "count": len(members),
                        "names": [str(m.get("name") or "") for m in rows]}
    return levels or None


# 名册（swords.json）刀种是日文旧字体（脇差/槍/剣），远征规则和面板用简体；
# 映射与 touken/flows/team_roster._TYPE_NORMALIZE 保持一致
_TYPE_NORMALIZE = {"脇差": "胁差", "槍": "枪", "剣": "剑"}
_SWORD_TYPE_TABLE: dict | None = None


def _sword_type_table() -> dict:
    """刀名（日/中）→ 规范刀种（简体）。精确匹配不模糊——资格门认错比
    认不到更糟（错拦只是少条建议，错放就是 failed_unknown）。"""
    global _SWORD_TYPE_TABLE
    if _SWORD_TYPE_TABLE is None:
        from touken import sword_db
        table = {}
        for info in sword_db.all_swords().values():
            raw = info.get("type") or ""
            sword_type = _TYPE_NORMALIZE.get(raw, raw)
            if not sword_type:
                continue
            for name in (info.get("name"), info.get("name_zh")):
                if name:
                    table.setdefault(name, sword_type)
        _SWORD_TYPE_TABLE = table
    return _SWORD_TYPE_TABLE


def party_sword_types(party: dict) -> list:
    """近况队伍 → 每人规范刀种（认不出为 None）。极化刀种不变，去「·极」后缀。"""
    table = _sword_type_table()
    types = []
    for name in party.get("names") or []:
        base = str(name).removesuffix("·极").strip()
        types.append(table.get(base))
    return types


def _type_shortfall(meta, party) -> dict | None:
    """刀种门槛（「含有」语义：至少一把该刀种在队）。

    返回 None = 合格/无从核（图没要求、没近况、名册全认不出都不拦，
    和等级门一个口径）；否则 {"missing": [缺的刀种], "distinct": (现有种数,
    要求种数) | None}。
    """
    if not party:
        return None
    rules = meta.get("rules") if isinstance(meta, dict) else None
    if not isinstance(rules, dict):
        return None
    required = rules.get("required_types")
    distinct_need = rules.get("min_distinct_types")
    has_distinct_rule = isinstance(distinct_need, int) \
        and not isinstance(distinct_need, bool) and distinct_need > 0
    if required is None and not has_distinct_rule:
        return None
    known = [t for t in party_sword_types(party) if t]
    if not known:
        return None
    missing = []
    if isinstance(required, dict):
        for type_name, need in sorted(required.items()):
            if not isinstance(need, int) or isinstance(need, bool) \
                    or need <= 0:
                continue
            if known.count(type_name) < need:
                missing.append(type_name)
    distinct = None
    if has_distinct_rule:
        have = len(set(known))
        if have < distinct_need:
            distinct = (have, distinct_need)
    if missing or distinct:
        return {"missing": missing, "distinct": distinct}
    return None


def _type_block_detail(team_no: int, party: dict, shortfall: dict) -> str:
    """人话描述哪队卡在哪：「部队四全是太刀，没有打刀」。"""
    team = f"部队{TEAM_NAMES.get(team_no, team_no)}"
    known = sorted({t for t in party_sword_types(party) if t})
    if len(known) == 1:
        comp = f"全是{known[0]}"
    elif known:
        comp = f"只有{'、'.join(known)}"
    else:
        comp = "刀种没核到"
    parts = []
    if shortfall["missing"]:
        parts.append("没有" + "和".join(shortfall["missing"]))
    if shortfall["distinct"]:
        have, need = shortfall["distinct"]
        parts.append(f"只凑出{have}种刀，要{need}种")
    return f"{team}{comp}，{'，'.join(parts)}"


def _type_req_text(meta) -> str:
    """图的刀种要求人话：「队里有打刀和太刀」「凑4种刀」。"""
    rules = meta.get("rules") if isinstance(meta, dict) else None
    if not isinstance(rules, dict):
        return ""
    parts = []
    required = rules.get("required_types")
    if isinstance(required, dict) and required:
        parts.append("队里有" + "和".join(sorted(required)))
    distinct_need = rules.get("min_distinct_types")
    if isinstance(distinct_need, int) and not isinstance(distinct_need, bool) \
            and distinct_need > 0:
        parts.append(f"凑{distinct_need}种刀")
    return "，".join(parts)


def _per_hour(meta, resource: str) -> float:
    if not isinstance(meta, dict):
        return 0.0
    amount = meta.get(resource)
    duration = meta.get("duration_min")
    if (not isinstance(amount, (int, float)) or amount <= 0
            or not isinstance(duration, (int, float)) or duration <= 0):
        return 0.0
    return round(amount / duration * 60, 2)


def _resource_rank(maps: dict, resource: str, map_code: str) -> int | None:
    """某图在某资源的时薪榜排第几（1 起）；不入榜（不产/没这图）返回 None。"""
    entries = []
    for code, meta in maps.items():
        rate = _per_hour(meta, resource)
        if rate > 0:
            entries.append((code, rate))
    if not entries:
        return None
    entries.sort(key=lambda item: -item[1])
    for index, (code, _) in enumerate(entries, start=1):
        if code == map_code:
            return index
    return None


def _forge_capacity(planning: dict, resource: str):
    watch = (planning or {}).get("resource_watch") or {}
    for row in watch.get("resources") or []:
        if isinstance(row, dict) and row.get("resource") == resource:
            return row.get("forge_capacity")
    return None


def _koban_short(planning: dict) -> bool:
    watch = (planning or {}).get("koban_watch") or {}
    try:
        if watch.get("available") is not None \
                and float(watch["available"]) <= 0:
            return True
    except (TypeError, ValueError):
        pass
    for goal in (planning or {}).get("goals") or []:
        if (isinstance(goal, dict) and goal.get("resource") == KOBAN
                and goal.get("status") != "done"):
            return True
    for event in (planning or {}).get("events") or []:
        if isinstance(event, dict) and event.get("shortfall"):
            return True
    return False


def shortage_order(planning: dict, n: int) -> list[tuple[str, str]]:
    """缺口榜：[(资源, 来头)]，来头 ∈ limiting / koban / fill，长度 ≥ n。

    limiting 全列（四资源齐平）视为「都不算缺」，后面用 fill 口吻兜底。
    """
    watch = (planning or {}).get("resource_watch") or {}
    limiting = [name for name in (watch.get("limiting") or [])
                if isinstance(name, str)]
    order: list[tuple[str, str]] = []
    seen: set[str] = set()
    if limiting and len(limiting) < len(FORGE_RESOURCES):
        for name in limiting:
            if name not in seen:
                order.append((name, "limiting"))
                seen.add(name)
    if _koban_short(planning) and KOBAN not in seen:
        order.append((KOBAN, "koban"))
        seen.add(KOBAN)
    capacities = []
    for row in watch.get("resources") or []:
        if (isinstance(row, dict)
                and row.get("resource") in FORGE_RESOURCES
                and isinstance(row.get("forge_capacity"), (int, float))
                and row["resource"] not in seen):
            capacities.append((row["forge_capacity"], row["resource"]))
    capacities.sort()
    for _, name in capacities:
        order.append((name, "fill"))
        seen.add(name)
    if KOBAN not in seen:
        order.append((KOBAN, "fill"))
        seen.add(KOBAN)
    if not order:
        order.append((KOBAN, "fill"))
    while len(order) < n:
        order.append((KOBAN, "fill"))
    return order[:n] if n > 0 else []


def _planning_has_data(planning) -> bool:
    if not isinstance(planning, dict):
        return False
    watch = planning.get("resource_watch")
    if not isinstance(watch, dict):
        return False
    return (watch.get("forge_capacity") is not None
            or bool(watch.get("limiting")))


def _level_ok(meta, party) -> bool:
    """队伍等级门槛：有近况就核（total_level 看队伍等级和、level_req 看
    最高等级）；没近况不拦，由 reason 注明。"""
    if not party:
        return True
    rules = meta.get("rules") if isinstance(meta, dict) else None
    total = rules.get("total_level") if isinstance(rules, dict) else None
    if isinstance(total, (int, float)) and total > 0 \
            and party["sum"] < total:
        return False
    req = meta.get("level_req") if isinstance(meta, dict) else None
    if isinstance(req, (int, float)) and req > 0 and party["max"] < req:
        return False
    return True


# ── 建议生成 v2：引擎现算班，不依赖排班投影 ──

SUGGEST_LEAD_MIN = 5          # 建议从 now+5 分钟起排
DAY_END_MIN = 23 * 60 + 59    # 当天 23:59 前排得下才给这班建议


def _reason(resource, tag, team_no, map_code, map_name, rank,
            capacity, party, type_note="") -> str:
    """v2 口吻：缺什么 → 派哪队去哪张图，为什么这队够格。"""
    team = f"部队{TEAM_NAMES.get(team_no, team_no)}"
    if tag == "limiting":
        head = f"{resource}最缺"
        if isinstance(capacity, (int, float)):
            head += f"（就剩{int(capacity)}炉）"
    elif tag == "koban":
        head = f"{resource}有目标缺口"
    else:
        head = f"家底不算缺，顺手攒{resource}"
    where = f"{map_code}「{map_name}」" if map_name and map_name != map_code \
        else map_code
    if rank == 1:
        tail = f"→ 派{team}去{where}，{resource}时薪正是第一"
    elif rank:
        tail = f"→ 派{team}去{where}，{resource}时薪第{rank}"
    else:
        tail = f"→ 派{team}去{where}"
    reason = f"{head}{tail}"
    suffix = "等级合计够格" if party else "队伍等级没核到"
    if type_note:
        suffix += f"，{type_note}"
    reason += f"（{suffix}）"
    return reason


def build_expedition_suggestions(prefs: dict, *,
                                 planning=None, maps: dict | None = None,
                                 situation_path: Path | None = None,
                                 now_min: float = 0.0,
                                 committed_teams=(),
                                 occupied_maps=(),
                                 failed_combos=()) -> dict:
    """玩家驱动的建议：丢 N 队 → 缺口前 N 种资源 → 每种资源配对口图和队。

    - 图：按该资源时薪从高到低试，23:59 前排不下就换次优图，全排不下
      今天不给这班建议（note 说明）。
    - 图排除：occupied_maps 里「今天已有未完结班」的图不入选（游戏机制
      一张图同时只能一队在跑）；本批建议内部也互相去重，两张建议不落同图。
    - 队：在「可丢且还没被派建议、没在外面跑、没已点的班」的队伍里，
      滤图的等级条件（total_level/level_req）和刀种条件
      （required_types「含有」语义 / min_distinct_types，有近况才核），
      都满足时优先番号小的；每队最多一条建议。
    - 黑名单：failed_combos 里「今天同图同队没派成」的组合不再荐
      （failed 会释放图，但同组合拉黑到今天结束），note 如实说明。
    - 多队建议同一起排时刻（now+5min）——不同队伍同时远征是游戏常态。
    返回 {"suggestions": [...], "note": 玩家可看的原因/None}。
    """
    prefs = _normalize_prefs(prefs)
    teams_out = prefs["teams_out"]
    empty = {"suggestions": [], "note": None}
    if teams_out <= 0:
        empty["note"] = "今天不丢队出门；想丢就在上面把队数挑起来。"
        return empty
    if not _planning_has_data(planning):
        empty["note"] = ("还不知道你家底缺什么——先去跑一次盘点/同步，"
                         "回来再点建议。")
        return empty
    if maps is None:
        maps = load_maps()
    if situation_path is None:
        situation_path = STATE_DIR / SITUATION_FILENAME
    party_levels = party_levels_from_situation(situation_path)
    start_min = max(0, int(now_min) + SUGGEST_LEAD_MIN)

    committed = set()
    for team in committed_teams or ():
        try:
            committed.add(int(team))
        except (TypeError, ValueError):
            continue
    free_teams = [t for t in sorted(prefs["available_teams"])
                  if t not in committed]

    occupied = {str(code) for code in occupied_maps or () if code}

    failed = set()
    for combo in failed_combos or ():
        try:
            code, team = combo
            failed.add((str(code), int(team)))
        except (TypeError, ValueError):
            continue

    order = shortage_order(planning, teams_out)
    suggestions = []
    misses = []
    used: set[int] = set()
    for resource, tag in order:
        ranked = sorted(
            (item for item in maps.items()
             if _per_hour(item[1], resource) > 0
             and int(item[1].get("duration_min") or 0) > 0),
            key=lambda item: -_per_hour(item[1], resource))
        placed = False
        miss = {"resource": resource, "fit": False, "level": False,
                "occupied": False, "type": False, "retry": False,
                "detail": ""}
        for map_code, meta in ranked:
            if map_code in occupied:
                miss["occupied"] = True
                continue
            duration = int(meta.get("duration_min") or 0)
            if start_min + duration > DAY_END_MIN:
                miss["fit"] = True
                continue
            candidates = [t for t in free_teams if t not in used]
            # 今天同图同队 failed 过的组合拉黑到今天结束（图本身不拉黑）
            blocked = [t for t in candidates if (map_code, t) in failed]
            if blocked:
                miss["retry"] = True
                candidates = [t for t in candidates if t not in blocked]
            eligible = []
            for team in candidates:
                party = (party_levels or {}).get(team)
                if not _level_ok(meta, party):
                    miss["level"] = True
                    continue
                shortfall = _type_shortfall(meta, party)
                if shortfall is not None:
                    miss["type"] = True
                    if not miss["detail"]:
                        miss["detail"] = (
                            f"{map_code}要{_type_req_text(meta)}，"
                            + _type_block_detail(team, party, shortfall))
                    continue
                eligible.append(team)
            if not eligible:
                continue
            team_no = min(eligible)
            used.add(team_no)
            per_hour = _per_hour(meta, resource)
            rank = _resource_rank(maps, resource, map_code)
            capacity = _forge_capacity(planning, resource)
            party = party_levels.get(team_no) if party_levels else None
            req_text = _type_req_text(meta)
            type_note = ""
            if req_text:
                known = [t for t in party_sword_types(party) if t] \
                    if party else []
                type_note = f"刀种也够格（{req_text}）" if known \
                    else "刀种没核到"
            suggestions.append({
                "kind": "expedition",
                "key": f"suggest:{team_no}:{map_code}",
                "team_no": team_no,
                "map_code": map_code,
                "map_name": str(meta.get("name") or map_code),
                "resource": resource,
                "duration_min": duration,
                "start_min": start_min,
                "reason": _reason(resource, tag, team_no, map_code,
                                  str(meta.get("name") or map_code),
                                  rank if per_hour > 0 else None,
                                  capacity, party, type_note),
            })
            placed = True
            occupied.add(map_code)  # 本批建议内部也去重：一张图一班
            break
        if not placed:
            misses.append(miss)

    notes = []
    if not free_teams and not suggestions:
        notes.append("能丢的队伍今天都已经有安排或还在外面，没队可丢。")
    for miss in misses:
        resource = miss["resource"]
        frags = []
        if miss["occupied"]:
            frags.append("对口图今天都有班在跑或已点上，明天再丢")
        if miss["retry"]:
            frags.append("这班今天没派成，同图同队先拉黑，换队/换图试试")
        if miss["type"]:
            frags.append(f"刀种门槛卡住：{miss['detail']}")
        if miss["fit"]:
            frags.append("对口图 23:59 前排不下，明天早点丢")
        if miss["level"]:
            frags.append("能丢的队伍等级都不够对口图")
        if frags:
            notes.append(f"{resource}：" + "；".join(frags) + "。")
        else:
            notes.append(f"{resource}今天排不出班（图太晚或没队够格）。")
    if suggestions and len(suggestions) < teams_out:
        notes.append(f"想丢 {teams_out} 队，只排得出 {len(suggestions)} 班。")
    return {"suggestions": suggestions,
            "note": "；".join(notes) if notes else None}
