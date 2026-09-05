"""获取途径知识库：回答「这东西在哪弄」。

一期只覆盖八种账本资源：远征收益从 expedition_maps.json 按大成功
时薪动态排名，日课/活动来源是 acquisition_sources.json 里写死的
规则文案。以后加刀剑、极化套装等新目标类型：往数据文件录新条目 +
给进度来源接识别即可，本模块结构不变。

纯函数模块：不碰 FastAPI、不碰游戏画面。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .gameplay_planning import load_gameplay_card

_DATA_DIR = Path(__file__).resolve().parent / "data"
_MAPS_FILE = _DATA_DIR / "expedition_maps.json"
_SOURCES_FILE = _DATA_DIR / "acquisition_sources.json"

_EXPEDITION_CAVEAT = "按大成功收益排的，实际看远征手气；括号里是队伍等级要求。"
# 掉率出处见 gameplay_meta.json 的 note：日服玩家实测，样本混着加倍期，国服待核
_FRAGMENT_RATE_SOURCE = ("掉率来自日服玩家实测，样本还混着加倍活动期，国服实际可能更低；"
                         "自家实测攒够数据后会换成自家的。")


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


# ── 异去碎片：「要哪件碎片，刷哪张图」 ──


def fragment_catalog() -> dict:
    """异去碎片清单：每种碎片一张途径卡（各图掉率排名，掉率高的在前）。

    键是碎片名。数据卡没收录碎片信息时返回空 dict——不知道就是不知道。
    """
    maps = (load_gameplay_card("异去") or {}).get("maps") or {}
    names: set[str] = set()
    for meta in maps.values():
        if isinstance(meta, dict):
            names.update((meta.get("fragments") or {}).keys())
    catalog = {}
    for name in sorted(names):
        entries = []
        for map_no, meta in maps.items():
            if not isinstance(meta, dict):
                continue
            rate = (meta.get("fragments") or {}).get(name)
            if not isinstance(rate, (int, float)) or rate <= 0:
                continue
            try:
                entries.append({"map_no": int(map_no),
                                "label": str(meta.get("label") or map_no),
                                "rate": float(rate)})
            except (TypeError, ValueError):
                continue
        entries.sort(key=lambda e: (-e["rate"], e["map_no"]))
        catalog[name] = {"fragment": name, "maps": entries,
                         "best_map": entries[0] if entries else None}
    return catalog


def fragment_notes(*, now: datetime | None = None) -> dict:
    """碎片玩法的公共备注：掉率出处、累计圈数里程碑、进行中的加倍活动。"""
    card = load_gameplay_card("异去") or {}
    campaign = card.get("campaign")
    if isinstance(campaign, dict):
        campaign = dict(campaign)
        try:
            start = datetime.fromisoformat(str(campaign.get("start_at")))
            end = datetime.fromisoformat(str(campaign.get("end_at")))
            moment = now or datetime.now(start.tzinfo)
            campaign["active"] = start <= moment <= end
        except (ValueError, TypeError):
            campaign["active"] = None
    else:
        campaign = None
    return {"rate_source": _FRAGMENT_RATE_SOURCE,
            "milestones": card.get("milestones") or [],
            "campaign": campaign}
