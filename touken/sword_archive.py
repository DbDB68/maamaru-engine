# -*- coding: utf-8 -*-
"""刀帐档案：机器盘点 + 人工标注的合并视图（build_sword_archive）。

与「当前本丸共用档案」同一份最新完整盘点做地基；人工标注
（telemetry schema v12 的 sword_annotations）按指纹
(sword_catalog_id, kiwame_date) 挂到具体某一振上，形态合并、要练
标记、待人工清单（attention）都在这里合成。只读生成，不写库。

铁律（与 honmaru_profile 同一套）：
  - 一振一行，同名多振保留；指纹撞车（一标注多行/一行多标注）不自动
    裁决，标 stale/duplicate_fingerprint 交回给人点；
  - 人工确认的 form 只覆盖机器的 unknown；机器 ambiguous（两处直读
    打架/图鉴分不清哪振）不被人工自动覆盖，进 attention 等人在界面上点；
  - 标注匹配不到任何行（刀解了/快照过期）不进 entries，进 attention
    记 stale_annotation。
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from .honmaru_profile import (_annotation_index, _human_annotations,
                              build_honmaru_profile)

ARCHIVE_SCHEMA_VERSION = 1

# attention 排序：同类内按 name_zh
_ATTENTION_PRIORITY = {"form_unknown": 0, "form_ambiguous": 1,
                       "duplicate_fingerprint": 2, "stale_annotation": 3}

_CATALOG_ID_RE = re.compile(r"touken_(\d+)_")
_DAY_RE = re.compile(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})")


def _catalog_info(sword_catalog_id):
    """按目录 id（如 touken_011_...）反查名册 (id, info)；认不出 None。"""
    from . import sword_db
    match = _CATALOG_ID_RE.match(str(sword_catalog_id or ""))
    if not match:
        return None
    try:
        return sword_db.find_by_id(int(match.group(1)))
    except Exception:
        return None


def _catalog_display_name(sword_catalog_id) -> str:
    found = _catalog_info(sword_catalog_id)
    if found:
        return found[1].get("name_zh") or found[1].get("name") \
            or str(sword_catalog_id)
    return str(sword_catalog_id)


def _catalog_type(sword_catalog_id):
    found = _catalog_info(sword_catalog_id)
    return found[1].get("type") if found else None


def _parse_manifest_day(value) -> date | None:
    """显现日期稳健解析（2024/5/1、2024-1-5 都行）；认不出返回 None。"""
    match = _DAY_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    try:
        return date(*[int(part) for part in match.groups()])
    except ValueError:
        return None


def _build_hints(entries: list) -> dict:
    """同名多振组的提示：等级最高（并列都给）/ 显现最早（并列都给）。

    返回 {observation_id: [hint, ...]}；单振组不出提示。日期解析不了就只
    跳过那条日期提示——不出就是不出，不猜。
    """
    groups = {}
    for entry in entries:
        groups.setdefault(entry.get("sword_catalog_id"), []).append(entry)
    hints = {}
    for catalog_id, rows in groups.items():
        if not catalog_id or len(rows) < 2:
            continue
        count = len(rows)
        levels = [r["level"] for r in rows
                  if isinstance(r.get("level"), int)
                  and not isinstance(r.get("level"), bool)]
        # 组内有等级没读出来的行时不出等级提示——缺一振的"最高"会误导人
        if len(levels) == len(rows):
            top = max(levels)
            for row in rows:
                if row.get("level") == top:
                    hints.setdefault(row["observation_id"], []).append(
                        f"同名 {count} 振中等级最高")
        parsed = [(row, _parse_manifest_day(row.get("kiwame_date")))
                  for row in rows]
        parsed = [(row, day) for row, day in parsed if day is not None]
        if parsed:
            earliest = min(day for _, day in parsed)
            for row, day in parsed:
                if day == earliest:
                    hints.setdefault(row["observation_id"], []).append(
                        "同名中显现最早")
    return hints


def build_sword_archive(store) -> dict:
    """生成刀帐档案（纯函数，不写库）。

    机器形态结论直接复用 honmaru_profile 的完整管线（盘点落盘事实 +
    编队页直读 + 图鉴极标），人工合并（unknown ← 人工确认）在候选池
    输出前已完成；本层负责挂 human 字段、stale/duplicate 判定、
    attention 清单与同名提示。
    """
    profile = build_honmaru_profile(store)
    pool = profile.get("candidate_pool") or {}
    if not pool.get("done"):
        return {"done": False, "reason": pool.get("reason"),
                "observed_at": pool.get("observed_at"), "snapshot_id": None,
                "summary": {"total": 0, "human_confirmed": 0,
                            "keepers": 0, "attention_count": 0},
                "entries": [], "attention": []}

    entries = pool.get("entries") or []
    annotations = _human_annotations(store)
    index = _annotation_index(annotations)
    row_counts = Counter(
        (entry.get("sword_catalog_id"), entry.get("kiwame_date"))
        for entry in entries)
    matched_ids = set()
    hints = _build_hints(entries)
    out_entries = []
    attention = []
    for entry in entries:
        key = (entry.get("sword_catalog_id"), entry.get("kiwame_date"))
        anns = index.get(key) or []
        matched_ids.update(ann.get("id") for ann in anns)
        row_hints = hints.get(entry.get("observation_id"), [])
        human = None
        reasons = []
        if anns:
            collision = len(anns) > 1 or row_counts.get(key, 0) > 1
            human = {"id": anns[0].get("id"),
                     "form": anns[0].get("form_confirmed"),
                     "keeper": bool(anns[0].get("keeper")),
                     "note": anns[0].get("note"),
                     "confirmed_at": anns[0].get("updated_at"),
                     "stale": collision}
            if collision:
                reasons.append("duplicate_fingerprint")
        form_status = entry.get("form_status") or "unknown"
        if form_status == "unknown":
            reasons.append("form_unknown")
        elif form_status == "ambiguous":
            reasons.append("form_ambiguous")
        out_entries.append({
            "observation_id": entry.get("observation_id"),
            "sword_catalog_id": entry.get("sword_catalog_id"),
            "name_zh": entry.get("name_zh"),
            "sword_type": _catalog_type(entry.get("sword_catalog_id")),
            "level": entry.get("level"),
            "tou_level": entry.get("tou_level"),
            "kiwame_date": entry.get("kiwame_date"),
            "form_status": form_status,
            "form_evidence": entry.get("form_evidence") or [],
            "unknown_fields": entry.get("unknown_fields") or [],
            "human": human,
            "hints": row_hints,
        })
        if reasons:
            attention.append({
                "observation_id": entry.get("observation_id"),
                "sword_catalog_id": entry.get("sword_catalog_id"),
                "name_zh": entry.get("name_zh"),
                "level": entry.get("level"),
                "kiwame_date": entry.get("kiwame_date"),
                "reasons": reasons,
                "hints": row_hints,
            })
    # 标注没挂到任何行（刀解了/快照过期）：不进 entries，进 attention 等人来认
    for ann in annotations:
        if ann.get("id") in matched_ids:
            continue
        attention.append({
            "observation_id": None,
            "sword_catalog_id": ann.get("sword_catalog_id"),
            "name_zh": _catalog_display_name(ann.get("sword_catalog_id")),
            "level": None,
            "kiwame_date": ann.get("kiwame_date"),
            "reasons": ["stale_annotation"],
            "hints": [],
        })
    attention.sort(key=lambda item: (
        min(_ATTENTION_PRIORITY[r] for r in item["reasons"]),
        item["name_zh"] or "", item["observation_id"] or ""))
    summary = {
        "total": len(out_entries),
        # 撞车（stale）的标注没生效，不算确认下来
        "human_confirmed": sum(1 for e in out_entries
                               if e["human"] and e["human"]["form"]
                               and not e["human"]["stale"]),
        "keepers": sum(1 for e in out_entries
                       if e["human"] and e["human"]["keeper"]
                       and not e["human"]["stale"]),
        "attention_count": len(attention),
    }
    return {"done": True, "reason": None,
            "observed_at": pool.get("observed_at"),
            "snapshot_id": (pool.get("source") or {}).get("snapshot_id"),
            "summary": summary, "entries": out_entries, "attention": attention}


def get_sword_archive(store=None) -> dict:
    """后端消费者稳定入口：默认取全局 telemetry 库。

    档案生成失败不拖垮调用方——返回 done=False 的骨架并注明错误。"""
    if store is None:
        from .telemetry import get_telemetry_store
        store = get_telemetry_store()
    try:
        return build_sword_archive(store)
    except Exception as exc:
        return {"done": False, "reason": f"刀帐档案生成失败：{exc}",
                "observed_at": None, "snapshot_id": None,
                "summary": {"total": 0, "human_confirmed": 0,
                            "keepers": 0, "attention_count": 0},
                "entries": [], "attention": []}
