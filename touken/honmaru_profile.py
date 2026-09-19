# -*- coding: utf-8 -*-
"""当前本丸共用档案 · 第一版事实层（只读生成，无 UI、无自动决策）。

输入（全在 telemetry 库，不另造事实库）：
  - sword_snapshots / sword_snapshot_rows：所持刀剑盘点（source=owned_inventory）
    与刀帐图鉴扫描（source=album），带 completeness 对账状态；
  - team_roster.observed 事件：五队六槽的编队即时状态。

输出一份档案 dict：
  - candidate_pool：只有「完整」的所持刀剑盘点（对账可信）才能晋升成当前
    候选池；较新的 partial/failed/album 一律不覆盖上一份可信完整档案；
  - roster：编队即时状态分层保存，槽位只在证据唯一时链接到候选行。

铁律：
  - 一振一行，同名多振保留，绝不按名字或 sword_catalog_id 去重；
  - sword_catalog_id 只是刀种目录，不是本丸实例 ID；observation_id =
    "{snapshot_id}:{row_id}" 只在该快照内有效，跨快照不伪造永久身份；
  - 同名多振或字段不足时输出 ambiguous/unknown + 候选集合，绝不拿
    第一把同名刀顶替；
  - unknown_fields / 识别状态 / 观测时间 / 来源全部保留，让未来规划器
    能解释「为什么能选 / 为什么不能确认」。
"""

import time
from datetime import datetime

PROFILE_SCHEMA_VERSION = 1

# 机器形态结论的人读标签（人工改判证据里「原识别=」用）：
# kiwame→极、normal→普通、ambiguous→存疑、unknown→未识别
_FORM_STATUS_LABELS = {"kiwame": "极", "normal": "普通",
                       "ambiguous": "存疑", "unknown": "未识别"}

# 候选行里参与 unknown_fields 盘点的可空字段
_ENTRY_NULLABLE_FIELDS = ("level", "tou_level", "survival", "survival_max",
                          "fatigue", "fatigue_max", "kiwame_date", "locked")


def build_candidate_pool(store) -> dict:
    """从刀帐快照晋升当前候选池。

    晋升规则：最新一份 source=owned_inventory 且 completeness=complete
    的盘点才当选——走 SQL 无窗口查询，较新的残缺/图鉴/来源不明快照
    攒得再多也挤不掉可信档案；它们记进 skipped_newer_snapshots 留证
    （展示证据，保留最近 200 条窗口）。
    """
    chosen = store.latest_sword_snapshot(source="owned_inventory",
                                         completeness="complete")
    recent = store.recent_sword_snapshots(limit=200)
    if chosen:
        skipped = [{"snapshot_id": s["id"], "captured_at": s.get("captured_at"),
                    "source": s.get("source") or "unknown",
                    "completeness": s.get("completeness") or "unknown"}
                   for s in recent
                   if (s.get("captured_at") or 0, s["id"])
                      > (chosen["captured_at"], chosen["id"])]
    else:
        skipped = [{"snapshot_id": s["id"], "captured_at": s.get("captured_at"),
                    "source": s.get("source") or "unknown",
                    "completeness": s.get("completeness") or "unknown"}
                   for s in recent]
    if not chosen:
        return {"done": False,
                "reason": "没有可信的完整所持刀剑盘点（只有残缺/图鉴/来源不明）",
                "source": None, "observed_at": None, "entries": [],
                "skipped_newer_snapshots": skipped}

    detail = store.sword_snapshot_detail(chosen["id"]) or {}
    entries = [_pool_entry(row, chosen) for row in detail.get("swords", [])]
    _apply_human_confirmations(entries, _human_annotations(store))
    return {"done": True,
            "completeness": "complete",
            "source": {"snapshot_id": chosen["id"],
                       "source": "owned_inventory",
                       "completeness": "complete"},
            "observed_at": chosen.get("captured_at"),
            "owned": chosen.get("owned"),
            "entry_count": len(entries),
            "entries": entries,
            "skipped_newer_snapshots": skipped}


def _stored_form_status(row: dict) -> str:
    """落盘形态结论：只信 kiwame/normal 正面结论，其余一律 unknown。"""
    fact = row.get("form_fact") or {}
    status = fact.get("status")
    return status if status in ("kiwame", "normal") else "unknown"


def _stored_form_evidence(row: dict) -> list:
    """落盘形态证据（仅正面结论附人读证据；unknown 不挂证据）。"""
    if _stored_form_status(row) == "unknown":
        return []
    fact = row.get("form_fact") or {}
    detail = "、".join(str(e) for e in fact.get("evidence") or [] if e)
    return [f"刀帐盘点徽章直读（{detail}）" if detail else "刀帐盘点徽章直读"]


def _pool_entry(row: dict, head: dict) -> dict:
    """一振一行。行身份 = snapshot_id:row_id（本次观察内有效）。"""
    unknown = []
    if not row.get("sword_id"):
        unknown.append("identity")
    for field in _ENTRY_NULLABLE_FIELDS:
        if row.get(field) is None:
            unknown.append(field)
    if not row.get("stats"):
        unknown.append("stats")
    form_status = _stored_form_status(row)
    return {
        "observation_id": f"{head['id']}:{row['row_id']}",
        "row_no": row.get("row_id"),  # 行在库里的序号，仅配合 snapshot_id 使用
        "sword_catalog_id": row.get("sword_id") or None,
        # 同队互斥键：目录里普通/极化共用一条记录（127 条无重名实测），
        # 同位刀（普通+极化、或同名多振）不能同队。取 sword_catalog_id；
        # 未知身份保持 None，绝不拿名字/徽章颜色硬猜。
        "same_team_exclusion_key": row.get("sword_id") or None,
        "name_zh": row.get("name_zh") or None,
        "level": row.get("level"),
        "tou_level": row.get("tou_level"),
        "survival": row.get("survival"),
        "survival_max": row.get("survival_max"),
        "fatigue": row.get("fatigue"),
        "fatigue_max": row.get("fatigue_max"),
        "stats": row.get("stats") or {},
        # 注意：这个字段历史名字叫 kiwame_date，实际读的是「显现日期」
        # （获得日期），每振刀都有——绝不是极化证据，形态结论只看
        # form_status/form_evidence（_annotate_form_conclusions 落）。
        "kiwame_date": row.get("kiwame_date"),
        # 形态事实来自盘点快照落盘的 form_fact（一览行徽章刀种+花数同帧
        # 观测，规则与编队页同一套）；老快照没有该列 → unknown，不猜。
        "form_status": form_status,
        "machine_form_status": None,  # 人工改判机器结论时回填机器原值
        "form_overridden": False,
        "form_evidence": _stored_form_evidence(row),
        "locked": row.get("locked"),
        "page_no": row.get("page_no"),
        "unknown_fields": unknown,
        "observed_at": head.get("captured_at"),
        "source_snapshot_id": head["id"],
    }


def _human_annotations(store) -> list:
    """刀帐人工标注（sword_annotations）；取不到按没有处理，不拖垮档案。"""
    fetch = getattr(store, "sword_annotations", None)
    if fetch is None:
        return []
    try:
        return fetch() or []
    except Exception:
        return []


def _annotation_index(annotations: list) -> dict:
    """有效标注按指纹 (sword_catalog_id, kiwame_date) 归组。

    候选池合并与刀帐档案（sword_archive）共用这套挂接规则：指纹是标注
    挂到具体某一振的唯一依据（显现日期终身不变），撞组的不自动裁决。
    """
    index = {}
    for ann in annotations or []:
        if not ann or ann.get("revoked"):
            continue
        key = (ann.get("sword_catalog_id"), ann.get("kiwame_date"))
        index.setdefault(key, []).append(ann)
    return index


def _confirm_day(updated_at) -> str | None:
    try:
        return datetime.fromtimestamp(float(updated_at)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _apply_human_confirmations(entries: list, annotations: list) -> None:
    """人工标注合并进候选池（原地标注）：
    - 形态：机器 unknown + 人工确认 → 以人工为准，证据追加
      「人工确认（日期）」；机器 kiwame/normal/ambiguous + 人工确认且
      与机器不同 → 人工改判，以人工为准（form_overridden=True，机器原值
      留在 machine_form_status，机器证据保留，追加「人工改判（日期）：
      原识别=极/普通/存疑」）；人工与机器一致不算改判，只追加确认证据；
    - 等级：只补空缺，永不覆盖机器读数（等级会随练级涨，人填的会过期）。
      机器 level 读不出（None）才用人工确认值，并把 "level" 从
      unknown_fields 里摘掉。

    只有指纹唯一命中（一标注对一行、一行对一标注）才合并；同名多振同日
    显现等撞车情形保持原样，交给刀帐档案标 stale/duplicate 让人处理。
    """
    if not entries or not annotations:
        return
    index = _annotation_index(annotations)
    row_counts = {}
    for entry in entries:
        key = (entry.get("sword_catalog_id"), entry.get("kiwame_date"))
        row_counts[key] = row_counts.get(key, 0) + 1
    for entry in entries:
        key = (entry.get("sword_catalog_id"), entry.get("kiwame_date"))
        anns = index.get(key) or []
        if len(anns) != 1 or row_counts.get(key, 0) != 1:
            continue
        form = anns[0].get("form_confirmed")
        machine_form = entry.get("form_status") or "unknown"
        if form in ("kiwame", "normal"):
            day = _confirm_day(anns[0].get("updated_at"))
            if machine_form == "unknown":
                entry["form_status"] = form
                entry["form_evidence"] = (entry.get("form_evidence") or []) + [
                    f"人工确认（{day}）" if day else "人工确认"]
            elif form != machine_form:
                # 人工改判机器结论：以人工为准；机器原值留在
                # machine_form_status，机器证据原样保留，追加改判记录
                label = _FORM_STATUS_LABELS.get(machine_form, machine_form)
                entry["form_status"] = form
                entry["machine_form_status"] = machine_form
                entry["form_overridden"] = True
                entry["form_evidence"] = (entry.get("form_evidence") or []) + [
                    f"人工改判（{day}）：原识别={label}" if day
                    else f"人工改判：原识别={label}"]
            else:
                # 人工与机器一致：不算改判，只追加确认证据
                entry["form_evidence"] = (entry.get("form_evidence") or []) + [
                    f"人工确认（{day}）" if day else "人工确认"]
        level = anns[0].get("level_confirmed")
        if entry.get("level") is None and level is not None:
            entry["level"] = level
            unknown = entry.get("unknown_fields") or []
            if "level" in unknown:
                entry["unknown_fields"] = [f for f in unknown if f != "level"]


def build_roster(store, entries: list[dict]) -> dict:
    """编队即时状态层：每队取最新一条 team_roster.observed，逐槽链接候选池。

    entries 为空（候选池不可用）时照样保留原始观察，链接全部落 unknown，
    reason 说明为什么确认不了。
    """
    events = store.recent_events(limit=200,
                                 event_type="team_roster.observed")
    latest_by_team = {}
    for ev in events:  # 最新在前
        team_no = (ev.get("payload") or {}).get("team_no")
        if isinstance(team_no, int) and team_no not in latest_by_team:
            latest_by_team[team_no] = ev

    teams = []
    for team_no in (1, 2, 3, 4, 5):
        ev = latest_by_team.get(team_no)
        if ev is None:
            teams.append({"team_no": team_no, "observation_status": "unknown",
                          "observed_at": None, "source_event_id": None,
                          "slots": []})
            continue
        payload = ev.get("payload") or {}
        teams.append({
            "team_no": team_no,
            "observation_status": payload.get("observation_status") or "unknown",
            "observed_at": ev.get("ts"),
            "source_event_id": ev.get("id"),
            "slots": [_link_slot(slot, entries)
                      for slot in payload.get("slots") or []],
        })
    return {"teams": teams}


def _link_slot(slot: dict, entries: list[dict]) -> dict:
    """单个编队槽 → 候选池链接。证据唯一才 linked，否则如实报原因。"""
    out = {"slot": slot.get("slot"),
           "slot_status": slot.get("slot_status") or "unknown",
           "link_status": "unknown",
           "observation_id": None,
           # 同队互斥键随链接输出暴露给未来规划器；确认不了就 None
           "same_team_exclusion_key": slot.get("sword_catalog_id") or None,
           "candidate_ids": [],
           "match_basis": "none",
           "link_reason": None,
           "observed": slot}
    if slot.get("slot_status") != "occupied":
        # 空位/读不出：不链接是正常状态，不是缺证据
        out["link_status"] = "not_applicable"
        out["link_reason"] = "槽位未占用或状态未知，无需链接候选池"
        return out
    if not entries:
        out["link_reason"] = "候选池不可用（没有可信的完整所持刀剑盘点）"
        return out

    catalog_id = slot.get("sword_catalog_id")
    name = slot.get("name")
    if catalog_id:
        candidates = [e for e in entries
                      if e.get("sword_catalog_id") == catalog_id]
        out["match_basis"] = "sword_catalog_id"
    elif name:
        candidates = [e for e in entries if e.get("name_zh") == name]
        out["match_basis"] = "name"
    else:
        out["link_reason"] = "编队页没读出身份（目录 id 和名字都没有）"
        return out

    out["candidate_ids"] = [e["observation_id"] for e in candidates]
    if len(candidates) == 1:
        out["link_status"] = "linked"
        out["observation_id"] = candidates[0]["observation_id"]
        out["link_reason"] = "候选池内证据唯一"
    elif candidates:
        out["link_status"] = "ambiguous"
        out["link_reason"] = (f"同名/同目录候选 {len(candidates)} 振，"
                              "本版不裁决是哪一振")
    else:
        out["link_reason"] = ("候选池里没有这把刀"
                              "（候选池过期、来源不明或该刀未盘点进池）")
    return out


def formation_conflicts(entries: list[dict]) -> list[dict]:
    """同队互斥校验（纯函数）：给定拟选条目，返回冲突组。

    规则（老大补充的游戏机制）：同一位刀的普通/极化形态不能同队，
    同名多振普通刀同样不能同队——目录里普通/极化共用
    sword_catalog_id，所以互斥键就是它。
    只报冲突，不做选人/换人。空 key（身份未知）不参与判定，
    绝不把「认不出」伪判成「不冲突」或「冲突」。

    Returns:
        [{"exclusion_key": 键, "observation_ids": [冲突条目...]}]，
        无冲突返回 []。
    """
    groups = {}
    for entry in entries:
        key = (entry or {}).get("same_team_exclusion_key")
        if not key:
            continue
        groups.setdefault(key, []).append((entry or {}).get("observation_id"))
    return [{"exclusion_key": key, "observation_ids": ids}
            for key, ids in groups.items() if len(ids) > 1]


def _annotate_form_conclusions(entries: list[dict], roster: dict,
                               store) -> None:
    """候选形态结论（原地标注）。纪律与编队页同一套（team_roster）：
    没有可靠证据就 unknown（前端显示「形态未确认」），绝不默认极/普通。

    证据强弱三级：
      1. 实例级（落盘）——一览盘点同帧徽章直读：刀种+花数 vs 名册基线，
         结论随快照存在 form_fact，_pool_entry 已挂上；
      2. 实例级（在线）——编队页槽位直读：该振被唯一链接到在队槽位，且槽位的
         刀种+花数/白樱花通道给出了 kiwame/normal 结论 → 采用；与落盘结论
         一致则证据叠加，冲突则降级 ambiguous（两处直读打架，存疑）；
      3. 种级——刀帐图鉴「极」字标（只取正向命中，漏读/未扫不算反证）：
         该刀种图鉴有极化记录，但分不清候选池里哪一振 → ambiguous。
    """
    if not entries:
        return
    by_oid = {e["observation_id"]: e for e in entries if e.get("observation_id")}
    for team in (roster or {}).get("teams") or []:
        for slot in team.get("slots") or []:
            if slot.get("link_status") != "linked":
                continue
            entry = by_oid.get(slot.get("observation_id"))
            if entry is None:
                continue
            ks = (slot.get("observed") or {}).get("kiwame_status")
            if ks not in ("kiwame", "normal"):
                continue
            ev = (slot.get("observed") or {}).get("kiwame_evidence") or []
            detail = "、".join(str(x.get("raw_value")) for x in ev
                               if isinstance(x, dict) and x.get("raw_value"))
            roster_ev = (f"编队页{team.get('team_no')}队{slot.get('slot')}号位直读"
                         + (f"（{detail}）" if detail else ""))
            prior = entry["form_status"]
            if prior in ("kiwame", "normal"):
                if prior == ks:
                    # 两处直读一致：证据叠加
                    entry["form_evidence"] = entry["form_evidence"] + [roster_ev]
                else:
                    # 盘点徽章与编队页直读打架：降级存疑，两条证据都摆出来
                    entry["form_status"] = "ambiguous"
                    entry["form_evidence"] = entry["form_evidence"] + [
                        roster_ev, "两处直读结论冲突，分不清，存疑"]
            else:
                entry["form_status"] = ks
                entry["form_evidence"] = [roster_ev]
    marked = _album_kiwame_names(store)
    for entry in entries:
        if entry["form_status"] != "unknown":
            continue
        if entry.get("name_zh") and entry["name_zh"] in marked:
            entry["form_status"] = "ambiguous"
            entry["form_evidence"] = [
                "刀帐图鉴有这振刀的极化记录，档案分不清是不是这一振"]


def _album_kiwame_names(store) -> set:
    """最新图鉴快照里带「极」字标的刀名集合（正向证据，异常即空集）。"""
    try:
        head = store.latest_sword_snapshot(source="album")
        if not head:
            return set()
        detail = store.sword_snapshot_detail(head["id"]) or {}
        return {row.get("name_zh") for row in detail.get("swords", [])
                if (row.get("stats") or {}).get("极化") and row.get("name_zh")}
    except Exception:
        return set()


def build_honmaru_profile(store) -> dict:
    """生成完整档案（纯函数，不写库）。"""
    pool = build_candidate_pool(store)
    entries = pool["entries"] if pool.get("done") else []
    roster = build_roster(store, entries)
    _annotate_form_conclusions(entries, roster, store)
    return {"schema_version": PROFILE_SCHEMA_VERSION,
            "generated_at": time.time(),
            "candidate_pool": pool,
            "roster": roster}


def get_honmaru_profile(store=None) -> dict:
    """后端消费者稳定入口：默认取全局 telemetry 库。
    档案生成失败不拖垮调用方——返回 done=False 的骨架并注明错误。"""
    if store is None:
        from .telemetry import get_telemetry_store
        store = get_telemetry_store()
    try:
        return build_honmaru_profile(store)
    except Exception as exc:
        return {"schema_version": PROFILE_SCHEMA_VERSION,
                "generated_at": time.time(),
                "done": False, "error": str(exc),
                "candidate_pool": {"done": False, "entries": []},
                "roster": {"teams": []}}
