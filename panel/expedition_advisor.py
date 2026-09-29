"""远征建议引擎：家底缺什么 → 今天丢哪几队、去哪些图。

玩家每天只做一个决定：丢几队出门（0–5）；"哪些队可以丢"是长期偏好。
建议只投「排班投影里已有的班」——采纳 = 给那班记 forced（排班总开关
关着也单独走状态机），绝不自动执行。

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
    """本丸近况 → {队号: {sum, max, count}}；读不到（没同步过）返回 None。

    有了它才能核远征图的 total_level/level_req；没有就只做收益匹配，
    建议里注明等级没核。
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
        members = [m.get("level") for m in party.get("members") or []
                   if isinstance(m, dict)]
        members = [int(level) for level in members
                   if isinstance(level, (int, float))]
        if not members:
            continue
        levels[team] = {"sum": sum(members), "max": max(members),
                        "count": len(members)}
    return levels or None


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


# ── 建议生成 ──


def _reason(resource, tag, team_no, map_code, per_hour, rank,
            capacity, party) -> str:
    team = f"部队{TEAM_NAMES.get(team_no, team_no)}"
    if tag == "limiting":
        head = f"{resource}最缺"
        if isinstance(capacity, (int, float)):
            head += f"（就剩{int(capacity)}炉）"
    elif tag == "koban":
        head = f"{resource}有目标缺口"
    else:
        head = f"家底不算缺，顺手攒{resource}"
    if per_hour > 0:
        if rank == 1:
            tail = f"→ {map_code}正是{resource}时薪第一"
        else:
            tail = f"→ 这是{team}今天的班里最对口的"
    else:
        tail = f"；但这队今天的班都不产{resource}，点了当攒家底"
    reason = f"{head}{tail}"
    if not party:
        reason += "（队伍等级没核到）"
    return reason


def build_expedition_suggestions(timeline: dict, prefs: dict, *,
                                 planning=None, maps: dict | None = None,
                                 situation_path: Path | None = None) -> dict:
    """投建议淡影：每支可丢队伍挑一班最对口的，采纳前只是建议。

    只从「排班投影里今天还没跑、还能翻案的班」里挑（forced 机制只能给
    既有 slot 翻案，改目的地就得动排班执行链，不在权限内）。
    返回 {"suggestions": [...], "note": 空建议时的原因}。
    """
    prefs = _normalize_prefs(prefs)
    teams_out = prefs["teams_out"]
    empty = {"suggestions": [], "note": None}
    if teams_out <= 0:
        return empty
    if not _planning_has_data(planning):
        empty["note"] = ("还不知道你家底缺什么——先去跑一次盘点/同步，"
                         "回来再点建议。")
        return empty
    if maps is None:
        maps = load_maps()
    expeditions = [item for item in (timeline or {}).get("expeditions") or []
                   if isinstance(item, dict)]
    candidates = [item for item in expeditions
                  if item.get("toggleable") and not item.get("will_run")]
    if situation_path is None:
        situation_path = STATE_DIR / SITUATION_FILENAME
    party_levels = party_levels_from_situation(situation_path)

    order = shortage_order(planning, teams_out)
    suggestions = []
    for team_no in sorted(prefs["available_teams"]):
        if len(suggestions) >= teams_out:
            break
        slots = [slot for slot in candidates
                 if int(slot.get("team_no") or 0) == team_no]
        slots = [slot for slot in slots
                 if _level_ok(maps.get(slot.get("map_code")), 
                              (party_levels or {}).get(team_no))]
        if not slots:
            continue
        resource, tag = order[len(suggestions)]
        capacity = _forge_capacity(planning, resource)

        def _score(slot):
            return (_per_hour(maps.get(slot.get("map_code")), resource),
                    -int(slot.get("time_min") or 0))

        best = max(slots, key=_score)
        map_code = best.get("map_code", "")
        per_hour = _per_hour(maps.get(map_code), resource)
        rank = _resource_rank(maps, resource, map_code) if per_hour > 0 else None
        suggestions.append({
            "kind": "expedition",
            "key": best.get("key", ""),
            "team_no": team_no,
            "map_code": map_code,
            "map_name": str((maps.get(map_code) or {}).get("name") or map_code),
            "resource": resource,
            "duration_min": int(best.get("duration_min") or 0),
            "start_min": int(best.get("time_min") or 0),
            "reason": _reason(resource, tag, team_no, map_code, per_hour,
                              rank, capacity, party_levels.get(team_no)
                              if party_levels else None),
        })
    if not suggestions:
        return {"suggestions": [],
                "note": ("可丢的队伍今天在排班表里没有能点的班——"
                         "去远征配置补个班，或多勾几支队伍。")}
    if len(suggestions) < teams_out:
        return {"suggestions": suggestions,
                "note": (f"想丢 {teams_out} 队，但今天只有 "
                         f"{len(suggestions)} 队有能点的班。")}
    return {"suggestions": suggestions, "note": None}
