# -*- coding: utf-8 -*-
"""可解释的远征纸面规划器 v1（纯函数，无 UI、不换人、不派遣）。

输入（全部显式传入，不另造事实库）：
  - profile：当前本丸共用档案（touken/honmaru_profile.build_honmaru_profile），
    含候选池与五队 roster 链接层；
  - member_facts：近侍/修行/手入事实。事实层目前没有这三项的观察入口，
    由调用方申报；缺申报不等于「无人受限」——整卷降级 needs_confirmation；
  - weights：目标权重（有序列表或 {资源: 权重}），默认 加速符 > 小判 >
    当前最缺的基础资源（老大个人偏好，可覆盖，不是所有玩家的规则）；
  - allow_all_teams_away：默认保留至少一支队在家打日课；显式 True 才五队全出。

硬规则（牛老师工单 2026-09-15 口径）：
  - 每张图验：最低人数（若规则已知）、全队等级合计、指定刀种「至少包含」；
    规则不全的图只给 rule_incomplete，不输出伪安全方案；
  - 修行中/手入中的具体刀不能远征；受伤（含重伤）不影响远征资格，只如实展示；
  - 近侍只扣那一振具体刀：同名/同形态多振用等价候选容量（多重集）表达——
    组内观察 n 振、近侍占 1 名额 → 可用 n-1，文案写「另一振」，绝不伪造
    一号机/二号机身份；n=1 时容量为 0；关联不可靠 → uncertain，不连坐
    整个同位刀家族，也不伪判安全；
  - same_team_exclusion_key 只管「同位刀不能同队」（复用
    honmaru_profile.formation_conflicts），与近侍约束是两套独立规则；
  - 樱吹雪阈值：fatigue >= 50（49 是自然恢复上限，不算花）；
    大成功是概率优化不是硬门槛，没有可靠概率数据，只输出
    「更有利/无法精确估算」，绝不编造精确数字。
"""

import time
from pathlib import Path

from . import sword_db
from .honmaru_profile import build_honmaru_profile, formation_conflicts

PLAN_SCHEMA_VERSION = 1

_MAPS_FILE = Path(__file__).parent / "data" / "expedition_maps.json"
BASE_RESOURCES = ("木炭", "玉钢", "冷却材", "砥石")
YIELD_RESOURCES = BASE_RESOURCES + ("委托符", "加速符", "小判")
SAKURA_FATIGUE_MIN = 50
# 档案/roster 观测超过这么久就提示陈旧（不硬拦截）
STALE_HOURS = 24

# 默认目标：老大个人偏好（加速符 > 小判 > 最缺的基础资源），可覆盖
_DEFAULT_GOALS = ("加速符", "小判", "most_lacking_base")

_CONFIDENCE_RANK = {"infeasible": 0, "rule_incomplete": 1,
                    "needs_confirmation": 2, "executable": 3}


def load_maps(path=None) -> dict:
    """读远征地图表（含 rules 子结构）。Returns: {map_code: map_info}。"""
    import json
    with open(path or _MAPS_FILE, encoding="utf-8") as f:
        return json.load(f)["maps"]


def latest_inventory_resources(store) -> dict | None:
    """最新一次 inventory.captured 的 resources（没有就 None）。"""
    events = store.recent_events(limit=1, event_type="inventory.captured")
    if not events:
        return None
    resources = (events[0].get("payload") or {}).get("resources")
    return resources if isinstance(resources, dict) else None


def most_lacking_base_resource(resources: dict | None):
    """四种基础资源里当前最少的一种；读不出/并列无法裁决时如实 None。"""
    if not resources:
        return None
    known = {r: resources.get(r) for r in BASE_RESOURCES
             if isinstance(resources.get(r), (int, float))}
    if not known:
        return None
    floor = min(known.values())
    leaders = sorted(r for r, v in known.items() if v == floor)
    if len(leaders) > 1:
        return None  # 并列最缺，不替玩家拍板
    return leaders[0]


def normalize_goals(weights, resources) -> tuple[list[dict], list[str]]:
    """目标权重归一成 [(resource, weight)]，按位次赋分（第 1 名权重最高）。

    weights=None → 默认偏好（加速符>小判>最缺基础资源）；
    有序 list → 按顺序；dict → 显式权重。返回 (goals, notes)。
    """
    notes = []
    if weights is None:
        lacking = most_lacking_base_resource(resources)
        ordered = []
        for g in _DEFAULT_GOALS:
            if g == "most_lacking_base":
                if lacking:
                    ordered.append(lacking)
                else:
                    notes.append("当前最缺基础资源算不出（库存快照缺失或并列），"
                                 "第三目标空缺")
            else:
                ordered.append(g)
        goals = [{"resource": r, "weight": float(len(ordered) - i)}
                 for i, r in enumerate(ordered)]
        notes.append("使用默认目标偏好：" + " > ".join(r["resource"] for r in goals))
        return goals, notes
    if isinstance(weights, dict):
        goals = [{"resource": r, "weight": float(w)}
                 for r, w in weights.items() if w]
        goals.sort(key=lambda g: -g["weight"])
        return goals, notes
    ordered = list(weights)
    return ([{"resource": r, "weight": float(len(ordered) - i)}
             for i, r in enumerate(ordered)], notes)


# ---------------------------------------------------------------- 成员视图

def _entry_form(entry: dict) -> str:
    """盘点行的形态：有极化显现日期 → kiwame，否则 normal（名册语义：
    显现块只有极化刀才有）。kiwame_date 缺失的证据强度记在 unknown_fields，
    本版按 normal 处理并在降级说明里保留原始字段。"""
    return "kiwame" if entry.get("kiwame_date") else "normal"


def _entry_group(entry: dict):
    """等价候选多重集组键：(catalog_id, 形态)。身份未知不分组。"""
    catalog_id = entry.get("sword_catalog_id")
    if not catalog_id:
        return None
    return (catalog_id, _entry_form(entry))


def _slot_form(slot: dict) -> str:
    status = slot.get("kiwame_status")
    return status if status in ("kiwame", "normal") else "unknown"


def _normalize_facts(member_facts) -> tuple[list[dict], list[str], bool]:
    """调用方申报的近侍/修行/手入事实 → (占用声明, 警告, 事实完整?)。

    每条声明 {"kind": attendant/training/repair, "sword_catalog_id":...,
    "form": kiwame/normal/None}。form=None 表示申报方也不知道形态，
    占用会落在该 catalog 的所有形态组上（不确定占用）。

    事实完整性（facts_complete）=False 的情形：没申报、或近侍身份未知。
    近侍必定存在（本丸看板），不存在「没有近侍」的申报——attendant
    不是带 sword_catalog_id 的 dict 就按未知处理，整卷降级。
    """
    claims, warnings = [], []
    if not member_facts:
        warnings.append("未提供近侍/修行/手入事实——这不等于无人受限："
                        "所有方案按 needs_confirmation 降级，派遣前请人工核对")
        return claims, warnings, False
    complete = True
    att = member_facts.get("attendant")
    if isinstance(att, dict) and att.get("sword_catalog_id"):
        claims.append({"kind": "attendant",
                       "sword_catalog_id": att["sword_catalog_id"],
                       "form": att.get("form")})
    else:
        complete = False
        warnings.append("近侍身份未申报/未知：各队「不含近侍本人」无法确认，"
                        "方案降级 needs_confirmation")
    for kind in ("training", "repair"):
        for item in member_facts.get(kind) or []:
            if isinstance(item, dict) and item.get("sword_catalog_id"):
                claims.append({"kind": kind,
                               "sword_catalog_id": item["sword_catalog_id"],
                               "form": item.get("form")})
    return claims, warnings, complete


_KIND_LABEL = {"attendant": "近侍", "training": "修行中", "repair": "手入中"}


def _group_capacities(entries, claims):
    """每组等价候选的可用容量。

    Returns:
        sizes: {group: 观察振数}
        occupied_definite: {group: 确定占用数}（形态明确的声明）
        occupied_possible: {group: 不确定占用数}（形态未知的声明可能落在这组）
        occ_kinds: {group: {占用来历...}}（attendant/training/repair）
        unmatched_claims: 候选池里找不到对应组的声明（档案可能过期）
    """
    sizes, occ_def, occ_pos, occ_kinds = {}, {}, {}, {}

    def _occupy(group, claim, bucket):
        bucket[group] = bucket.get(group, 0) + 1
        occ_kinds.setdefault(group, set()).add(claim["kind"])

    for entry in entries:
        group = _entry_group(entry)
        if group:
            sizes[group] = sizes.get(group, 0) + 1
    unmatched = []
    for claim in claims:
        if claim.get("form") in ("kiwame", "normal"):
            group = (claim["sword_catalog_id"], claim["form"])
            if group in sizes:
                _occupy(group, claim, occ_def)
            else:
                unmatched.append(claim)
        else:
            groups = [g for g in sizes if g[0] == claim["sword_catalog_id"]]
            if not groups:
                unmatched.append(claim)
            for group in groups:
                _occupy(group, claim, occ_pos)
    return sizes, occ_def, occ_pos, occ_kinds, unmatched


def _member_view(slot: dict, entries_by_id: dict) -> dict:
    """一个编队槽 → 规划用成员视图（保留原始观察，不补默认值）。"""
    observed = slot.get("observed") or {}
    entry = entries_by_id.get(slot.get("observation_id"))
    candidates = [entries_by_id[oid] for oid in slot.get("candidate_ids") or []
                  if oid in entries_by_id]
    level = observed.get("level")
    level_basis = "roster"
    if level is None and entry and entry.get("level") is not None:
        level = entry["level"]
        level_basis = "candidate_pool"  # 盘点值，可能比编队页旧
    form = _slot_form(observed)
    if form == "unknown" and entry:
        form = _entry_form(entry)
    groups = set()
    if slot.get("link_status") == "linked" and entry:
        group = _entry_group(entry)
        if group:
            groups.add(group)
    else:
        for cand in candidates:
            group = _entry_group(cand)
            if group and (form == "unknown" or group[1] == form):
                groups.add(group)
    return {
        "slot": slot.get("slot"),
        "name": observed.get("name"),
        "sword_catalog_id": observed.get("sword_catalog_id"),
        "sword_type": observed.get("sword_type"),
        "level": level, "level_basis": level_basis,
        "fatigue": observed.get("fatigue"),
        "injury": observed.get("injury"),
        "kiwame_status": observed.get("kiwame_status"),
        "form": form,
        "link_status": slot.get("link_status"),
        "observation_id": slot.get("observation_id"),
        "candidate_ids": list(slot.get("candidate_ids") or []),
        "identity_groups": sorted(groups),
        "unknown_fields": list(observed.get("unknown_fields") or []),
    }


def _team_availability(members, sizes, occ_def, occ_pos, occ_kinds):
    """近侍/修行/手入占用检查（多重集容量，三套约束共用一套机制）。

    对每组 g：确定占用 occ_def、不确定占用 occ_pos。
      min_available = size - occ_def - occ_pos（最坏情况）
      max_available = size - occ_def（最好情况）
    队伍从 g 确定抽 d 振（linked）、可能抽 p 振（ambiguous 候选含 g）：
      d > max_available      → blocked（一定带上了被占用的人）
      d + p <= min_available → clear（备注「另一振」，不伪造号机身份）
      其余                   → uncertain（可能是另一振，也可能就是本人）
    """
    definite, possible = {}, {}
    for m in members:
        groups = m["identity_groups"]
        if m["link_status"] == "linked" and len(groups) == 1:
            definite[groups[0]] = definite.get(groups[0], 0) + 1
        else:
            for g in groups:
                possible[g] = possible.get(g, 0) + 1

    blocked, uncertain, notes = [], [], []
    for group in set(definite) | set(possible):
        size = sizes.get(group, 0)
        d = definite.get(group, 0)
        p = possible.get(group, 0)
        od = occ_def.get(group, 0)
        op = occ_pos.get(group, 0)
        if not od and not op:
            continue
        label = _group_label(group)
        kinds = "、".join(_KIND_LABEL[k] for k in
                          sorted(occ_kinds.get(group) or ()))
        max_avail = size - od
        min_avail = size - od - op
        if d > max_avail:
            blocked.append(f"{label}：名额已全被{kinds}占用"
                           f"（观察 {size} 振，占用 {od + op}）")
        elif d + p <= min_avail:
            notes.append(f"{label}：组内 {size} 振、{kinds}占 {od + op} 名额，"
                         "本队用的是另一振（多重集容量足够）")
        else:
            uncertain.append(
                f"{label}：组内 {size} 振、{kinds}占 {od + op} 名额，"
                "无法确认本队成员是不是被占用的那一振")
    return blocked, uncertain, notes


def _group_label(group) -> str:
    catalog_id, form = group
    info = sword_db.all_swords().get(catalog_id) or {}
    name = info.get("name_zh") or info.get("name") or catalog_id
    suffix = {"kiwame": "（极化）", "normal": "（普通）"}.get(form, "")
    return f"{name}{suffix}"


# ---------------------------------------------------------------- 地图条件

def check_map_eligibility(map_code: str, map_info: dict,
                          members: list[dict]) -> dict:
    """单队单图硬条件检查（纯函数）。

    members：_member_view 列表（只含占用槽）。
    Returns: {eligible, confidence, passed, failures, unknowns}
      confidence: executable / needs_confirmation / rule_incomplete / infeasible
    """
    rules = map_info.get("rules") or {}
    passed, failures, unknowns = [], [], []

    # 最低人数：null = 不知道，不是「没有要求」
    # （slot_status=unknown 的槽不在 members 里，队伍构成的不确定性
    #   由调用方在队伍层降级，这里只数确认占用的）
    min_members = rules.get("min_members")
    n = len(members)
    if isinstance(min_members, int):
        if n >= min_members:
            passed.append(f"在队 {n} 振 ≥ 最低 {min_members} 振")
        else:
            failures.append(f"在队 {n} 振 < 最低 {min_members} 振")

    # 总等级
    req_level = rules.get("total_level")
    if isinstance(req_level, int):
        known_sum = sum(m["level"] for m in members
                        if isinstance(m["level"], (int, float)))
        n_no_level = sum(1 for m in members
                         if not isinstance(m["level"], (int, float)))
        if n_no_level == 0:
            if known_sum >= req_level:
                passed.append(f"全队等级合计 {known_sum} ≥ {req_level}")
            else:
                failures.append(f"全队等级合计 {known_sum} < {req_level}")
        else:
            if known_sum >= req_level:
                passed.append(f"已确认等级合计 {known_sum} ≥ {req_level}"
                              f"（{n_no_level} 振等级未知，按 0 计也够）")
            else:
                unknowns.append(f"{n_no_level} 振等级读不出，已确认合计 "
                                f"{known_sum} / 要求 {req_level}，无法确认")

    # 指定刀种「至少包含」
    required_types = rules.get("required_types") or {}
    for type_name, need in sorted(required_types.items()):
        have = sum(1 for m in members if m["sword_type"] == type_name)
        maybe = sum(1 for m in members if m["sword_type"] is None)
        if have >= need:
            passed.append(f"含{type_name} {have} 振 ≥ {need} 振")
        elif have + maybe >= need:
            unknowns.append(f"确认含{type_name} {have} 振 < {need} 振，"
                            f"{maybe} 振刀种未知，无法确认")
        else:
            failures.append(f"需要至少 {need} 振{type_name}，"
                            f"全队确认只有 {have} 振")

    confidence = "executable"
    if failures:
        confidence = "infeasible"
    elif unknowns:
        confidence = "needs_confirmation"
    if confidence != "infeasible" and rules.get("completeness") != "complete":
        unknown_aspects = rules.get("unknown_aspects") or ["未知面未标注"]
        confidence = "rule_incomplete"
        unknowns.append(f"该图规则不完整（{'、'.join(unknown_aspects)}无依据），"
                        "以上通过项不构成可执行保证")
    return {"map_code": map_code, "eligible": not failures,
            "confidence": confidence,
            "passed": passed, "failures": failures, "unknowns": unknowns}


# ---------------------------------------------------------------- 方案生成

def _per_hour_yields(map_info: dict) -> dict:
    duration = map_info.get("duration_min") or 0
    if duration <= 0:
        return {}
    hours = duration / 60.0
    return {r: round((map_info.get(r) or 0) / hours, 3) for r in YIELD_RESOURCES}


def _score(map_info: dict, goals: list[dict],
           max_per_hour: dict) -> float | None:
    """按时薪加权打分；时长或收益缺失 → None（不参与排名）。

    各资源时薪先按全图表内的最高时薪归一（该资源最好的图=1.0），
    再加权求和——不同资源量级差几个数量级（小判几百 vs 加速符个位），
    不归一的话名义上的「优先加速符」会被绝对数值架空。
    """
    per_hour = _per_hour_yields(map_info)
    if not per_hour:
        return None
    total = 0.0
    for g in goals:
        peak = max_per_hour.get(g["resource"]) or 0
        if peak > 0:
            total += g["weight"] * per_hour.get(g["resource"], 0) / peak
    return total


def _max_per_hour(maps: dict) -> dict:
    peak = {}
    for info in maps.values():
        for r, v in _per_hour_yields(info).items():
            peak[r] = max(peak.get(r, 0), v)
    return peak


def _great_success_note(members) -> dict:
    """樱吹雪只按 fatigue>=50；没有可靠概率数据，只给定性结论。"""
    occupied = members
    if not occupied:
        return {"status": "unknown", "note": "没有成员事实，无法评估"}
    bloomed = [m for m in occupied
               if isinstance(m["fatigue"], (int, float))
               and m["fatigue"] >= SAKURA_FATIGUE_MIN]
    unknown = [m for m in occupied
               if not isinstance(m["fatigue"], (int, float))]
    if unknown:
        return {"status": "unknown",
                "note": f"{len(unknown)} 振疲劳读不出，大成功条件无法评估；"
                        "飘花只影响大成功概率，不影响普通成功"}
    if len(bloomed) == len(occupied):
        return {"status": "favored",
                "note": "全员樱吹雪（疲劳≥50），大成功更有利"
                        "（概率无可靠数据，无法精确估算）"}
    return {"status": "not_favored",
            "note": f"{len(bloomed)}/{len(occupied)} 振飘花，"
                    "不影响普通成功；大成功概率无法精确估算"}


def _sacrifices(map_info: dict) -> list[str]:
    duration = map_info.get("duration_min") or 0
    out = []
    if duration:
        hours = duration / 60.0
        out.append(f"该队约 {hours:.1f} 小时内无法出阵/内番/演练")
    return out


def _assignment(team: dict, members: list[dict], maps: dict,
                goals: list[dict], now: float, next_online,
                max_per_hour: dict):
    """一队选一张图。

    Returns: (assignment 或 None, rejections)
      rejections = [{"map_code", "failures", "unknowns"}]——每张没选上的图
      为什么不行，可行性审计要用；None 时调用方靠它解释「为什么哪都去不了」。
    """
    options, rejections = [], []
    for code, info in maps.items():
        check = check_map_eligibility(code, info, members)
        if not check["eligible"]:
            rejections.append({"map_code": code,
                               "map_name": info.get("name") or "",
                               "failures": check["failures"],
                               "unknowns": check["unknowns"]})
            continue
        score = _score(info, goals, max_per_hour)
        duration = info.get("duration_min") or 0
        return_at = now + duration * 60 if duration else None
        return_note = None
        if return_at is not None and next_online and return_at > next_online:
            return_note = "预计归来晚于下次上线时间"
        yields = {r: info.get(r) or 0 for r in YIELD_RESOURCES}
        options.append({
            "team_no": team["team_no"], "map_code": code,
            "map_name": info.get("name") or "",
            "confidence": check["confidence"],
            "why_eligible": check["passed"],
            "uncertainties": check["unknowns"],
            "score": score,
            "members": [_member_brief(m) for m in members],
            "duration_min": duration,
            "expected_return_at": return_at,
            "expected_return_text": (time.strftime("%Y-%m-%d %H:%M:%S",
                                     time.localtime(return_at))
                                     if return_at else "未知"),
            "return_note": return_note,
            "yields": yields,
            "yields_per_hour": _per_hour_yields(info),
            "great_success": _great_success_note(members),
            "sacrifices": _sacrifices(info),
        })
    if not options:
        return None, rejections
    # 可执行优先，其次分数；分数缺失的排最后
    options.sort(key=lambda o: (-_CONFIDENCE_RANK[o["confidence"]],
                                -(o["score"] if o["score"] is not None else -1)))
    best = dict(options[0])
    best["alternatives"] = [{"map_code": o["map_code"],
                             "map_name": o["map_name"],
                             "confidence": o["confidence"],
                             "score": o["score"]}
                            for o in options[1:]]
    best["rejected_maps"] = rejections
    return best, rejections


def _member_brief(m: dict) -> dict:
    return {"slot": m["slot"], "name": m["name"], "level": m["level"],
            "sword_type": m["sword_type"], "fatigue": m["fatigue"],
            "injury": m["injury"], "link_status": m["link_status"],
            "observation_id": m["observation_id"]}


def plan_expeditions(profile=None, *, store=None, member_facts=None,
                     weights=None, allow_all_teams_away=False,
                     now=None, next_online=None, maps=None,
                     inventory="__from_store__") -> dict:
    """远征纸面规划主入口（纯函数，不写库、不触碰游戏）。

    Args:
        profile: honmaru_profile 档案；None 时从 store/全局库现生成。
        store: TelemetryStore（profile/inventory 缺省时的数据来源）。
        member_facts: {"attendant": {"sword_catalog_id":..., "form":...} | None,
                       "attendant_known": bool,
                       "training": [...], "repair": [...]}；
                      None = 完全没申报（整卷降级 needs_confirmation）。
        weights: 目标权重（有序 list 或 dict）；None = 默认偏好。
        allow_all_teams_away: True 才允许五队全出（带醒目警告）。
        now/next_online: epoch 秒；next_online 只标注不拦截。
        maps: 地图表（默认 data/expedition_maps.json）。
        inventory: 资源 dict；"__from_store__" 时从 store 读最新库存。
    """
    now = now if now is not None else time.time()
    if store is None:
        from .telemetry import get_telemetry_store
        store = get_telemetry_store()
    if profile is None:
        profile = build_honmaru_profile(store)
    maps = maps or load_maps()
    max_per_hour = _max_per_hour(maps)
    if inventory == "__from_store__":
        inventory = latest_inventory_resources(store)

    warnings, explanation = [], []
    pool = profile.get("candidate_pool") or {}
    entries = pool.get("entries") or []
    entries_by_id = {e["observation_id"]: e for e in entries}
    if not pool.get("done"):
        warnings.append(f"候选池不可用：{pool.get('reason') or '原因未知'}——"
                        "编队成员无法对账，所有方案降级")
    goals, goal_notes = normalize_goals(weights, inventory)
    explanation.extend(goal_notes)
    if inventory is None:
        warnings.append("没有库存快照，「最缺基础资源」目标按空缺处理")

    claims, fact_warnings, facts_complete = _normalize_facts(member_facts)
    warnings.extend(fact_warnings)
    sizes, occ_def, occ_pos, occ_kinds, unmatched = _group_capacities(
        entries, claims)
    for claim in unmatched:
        warnings.append(
            f"{_KIND_LABEL[claim['kind']]}申报的刀（{claim['sword_catalog_id']}）"
            "不在候选池里：档案可能过期，相关约束无法确认，方案降级")

    # 陈旧提示（不硬拦截）
    for label, ts in (("所持刀剑盘点", pool.get("observed_at")),):
        if ts and now - ts > STALE_HOURS * 3600:
            warnings.append(f"{label}观测于 {time.strftime('%m-%d %H:%M', time.localtime(ts))}"
                            f"，超过 {STALE_HOURS} 小时，可能陈旧")

    teams_out = []       # (team, members, blocked, uncertain, avail_notes)
    for team in (profile.get("roster") or {}).get("teams") or []:
        team_no = team.get("team_no")
        obs_status = team.get("observation_status")
        if obs_status in (None, "unknown") and not team.get("slots"):
            explanation.append(f"部队{team_no}：无编队观测，不参与规划")
            continue
        if obs_status == "failed":
            warnings.append(f"部队{team_no}：编队观测失败，不参与规划")
            continue
        slots = [s for s in team.get("slots") or []
                 if s.get("slot_status") == "occupied"]
        unknown_slots = [s for s in team.get("slots") or []
                         if s.get("slot_status") == "unknown"]
        members = [_member_view(s, entries_by_id) for s in slots]
        blocked, uncertain, avail_notes = _team_availability(
            members, sizes, occ_def, occ_pos, occ_kinds)
        if unknown_slots:
            uncertain.append(f"{len(unknown_slots)} 个槽位状态读不出，"
                             "队伍构成无法完全确认")
        # 同队互斥（独立于近侍约束）：游戏本身不允许同位刀同队，
        # 观测到冲突=数据可疑，如实拦下。复用 formation_conflicts，
        # 键取槽位输出的 same_team_exclusion_key（身份未知=None 不判）。
        slot_entries = [{"observation_id": f"slot{s.get('slot')}",
                         "same_team_exclusion_key": s.get("same_team_exclusion_key")}
                        for s in slots]
        conflicts = formation_conflicts(slot_entries)
        if conflicts:
            blocked.append("队内存同位刀互斥冲突（观测数据可疑）："
                           + "；".join(f"键 {c['exclusion_key']} ×"
                                       f"{len(c['observation_ids'])}"
                                       for c in conflicts))
        teams_out.append((team, members, blocked, uncertain, avail_notes,
                          obs_status))

    assignments, infeasible = [], []
    for team, members, blocked, uncertain, avail_notes, obs_status in teams_out:
        team_no = team["team_no"]
        if not members:
            infeasible.append({"team_no": team_no,
                               "reasons": ["队伍为空或全部槽位未占用"]})
            continue
        if blocked:
            infeasible.append({"team_no": team_no, "reasons": blocked})
            continue
        pick, rejections = _assignment(team, members, maps, goals, now,
                                       next_online, max_per_hour)
        if pick is None:
            reasons = ["所有远征图的硬条件都不满足或无法确认"]
            for r in rejections:
                for f in r["failures"]:
                    reasons.append(f"{r['map_code']} {r['map_name']}：{f}")
            infeasible.append({"team_no": team_no, "reasons": reasons,
                               "rejected_maps": rejections})
            continue
        if uncertain:
            pick["uncertainties"] = list(pick["uncertainties"]) + uncertain
            if pick["confidence"] == "executable":
                pick["confidence"] = "needs_confirmation"
        if obs_status == "partial":
            pick["uncertainties"].append("该队编队观测本身是 partial")
            if pick["confidence"] == "executable":
                pick["confidence"] = "needs_confirmation"
        if avail_notes:
            pick["availability_notes"] = avail_notes
        pick["injury_note"] = _injury_note(members)
        assignments.append(pick)

    staying, all_away_warning = None, None
    if assignments and not allow_all_teams_away and len(assignments) > 1:
        # 默认保留至少一支队在家：留下贡献最低的那支（它的备选进 infeasible 不丢）
        worst = min(assignments,
                    key=lambda a: (a["score"] is not None, a["score"] or 0))
        assignments = [a for a in assignments if a is not worst]
        staying = {"team_no": worst["team_no"],
                   "best_option_if_sent": {"map_code": worst["map_code"],
                                           "score": worst["score"]},
                   "reason": "默认保留至少一支可出阵队伍在家（打日课）；"
                             "如需全出请显式 allow_all_teams_away=True"}
    elif assignments and not allow_all_teams_away and len(assignments) == 1:
        staying = {"team_no": assignments[0]["team_no"],
                   "best_option_if_sent": None,
                   "reason": "只有一支队可派，保留在家（未派出）"}
        assignments = []
    if allow_all_teams_away and assignments:
        all_away_warning = "⚠️ 本丸将暂时没有可出阵队伍（五队全出）"

    plan_confidence = "executable"
    if not assignments:
        plan_confidence = "infeasible"
    else:
        plan_confidence = min((a["confidence"] for a in assignments),
                              key=lambda c: _CONFIDENCE_RANK[c])
    # 事实不完整（没申报/近侍未知/申报的刀不在池里）：硬资格不确定，
    # 任何方案都不得伪装成可直接执行
    if plan_confidence == "executable" and (not facts_complete or unmatched):
        plan_confidence = "needs_confirmation"

    return {"schema_version": PLAN_SCHEMA_VERSION,
            "generated_at": now,
            "inputs": {
                "profile_observed_at": pool.get("observed_at"),
                "pool_snapshot": pool.get("source"),
                "member_facts_status": ("provided" if member_facts
                                        else "missing"),
                "goals": goals,
                "allow_all_teams_away": bool(allow_all_teams_away),
                "now": now, "next_online": next_online,
            },
            "plan": {"confidence": plan_confidence,
                     "assignments": assignments,
                     "staying_home": staying,
                     "all_away_warning": all_away_warning},
            "infeasible": infeasible,
            "warnings": warnings,
            "explanation": explanation}


def _injury_note(members) -> str | None:
    """受伤不剔除，只如实展示。"""
    injured = [(m["name"], m["injury"]) for m in members
               if m["injury"] in ("light", "medium", "heavy")]
    if not injured:
        return None
    label = {"light": "轻伤", "medium": "中伤", "heavy": "重伤"}
    return ("带伤出征不影响远征资格："
            + "、".join(f"{n or '?'}({label[i]})" for n, i in injured))
