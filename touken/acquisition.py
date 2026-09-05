"""获取途径知识库：回答「这东西在哪弄」。

一期只覆盖八种账本资源：远征收益从 expedition_maps.json 按大成功
时薪动态排名，日课/活动来源是 acquisition_sources.json 里写死的
规则文案。以后加刀剑、极化套装等新目标类型：往数据文件录新条目 +
给进度来源接识别即可，本模块结构不变。

纯函数模块：不碰 FastAPI、不碰游戏画面。
"""
from __future__ import annotations

import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"
_MAPS_FILE = _DATA_DIR / "expedition_maps.json"
_SOURCES_FILE = _DATA_DIR / "acquisition_sources.json"

_EXPEDITION_CAVEAT = "按大成功收益排的，实际看远征手气；括号里是队伍等级要求。"


def _load_maps() -> dict:
    try:
        data = json.loads(_MAPS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    maps = data.get("maps")
    return maps if isinstance(maps, dict) else {}


def _load_source_cards() -> dict:
    try:
        data = json.loads(_SOURCES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cards = data.get("resources")
    return cards if isinstance(cards, dict) else {}


def expedition_ranking(resource: str, *, top: int = 3) -> list[dict]:
    """某种资源的远征时薪排名（按大成功收益算）。

    时薪并列时短图优先（周转快、排班灵活），再按等级要求和图编号稳定排序。
    该资源没有远征产出时返回空列表（例如甲州金）。
    """
    entries = []
    for code, meta in _load_maps().items():
        if not isinstance(meta, dict):
            continue
        amount = meta.get(resource)
        duration = meta.get("duration_min")
        if (not isinstance(amount, (int, float)) or amount <= 0
                or not isinstance(duration, (int, float)) or duration <= 0):
            continue
        era = meta.get("era")
        slot = meta.get("slot")
        label = f"{era}-{slot}" if era and slot else str(code)
        level_req = meta.get("level_req")
        entries.append({
            "map": str(code),
            "label": label,
            "name": str(meta.get("name") or ""),
            "duration_min": int(duration),
            "amount": int(amount),
            "per_hour": round(amount / duration * 60, 2),
            "level_req": int(level_req) if isinstance(level_req, (int, float)) else None,
        })
    entries.sort(key=lambda e: (-e["per_hour"], e["duration_min"],
                                e["level_req"] or 0, e["map"]))
    return entries[:top]


def resource_guide(resource: str) -> dict | None:
    """一种资源的获取途径卡。不认识的资源返回 None（前端不渲染）。"""
    cards = _load_source_cards()
    if resource not in cards:
        return None
    card = cards.get(resource) or {}
    expeditions = expedition_ranking(resource)
    return {
        "resource": resource,
        "expeditions": expeditions,
        "expedition_caveat": _EXPEDITION_CAVEAT if expeditions else None,
        "mission": card.get("mission"),
        "event": card.get("event"),
        "note": card.get("note"),
    }
