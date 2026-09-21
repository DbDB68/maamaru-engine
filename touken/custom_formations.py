# -*- coding: utf-8 -*-
"""预设编队档案：我们这边存的阵容预设（覆盖游戏内某部队 1-5）。

玩法选中预设时，先把 slots 逐槽应用成游戏内队伍再跑玩法
（formation_editor.apply_preset_formation_stream）。存储 = 用户数据目录
STATE_DIR/custom_formations.json；坏文件改名备份后当空的处理，绝不崩。
"""

import json
import re
import time

from .runtime_paths import STATE_DIR

MAX_FORMATIONS = 5

_ID_RE = re.compile(r"^[a-z0-9]+$")
_SLOT_KEYS = frozenset("123456")


def _formations_path():
    return STATE_DIR / "custom_formations.json"


def load_formations() -> list[dict]:
    """读预设编队；坏 JSON 备份成 .bad-时间戳 后返回空，绝不让调用方崩。"""
    path = _formations_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        try:
            bad = path.with_name(path.name + ".bad-"
                                 + time.strftime("%Y%m%d-%H%M%S"))
            path.replace(bad)
        except OSError:
            pass
        return []
    if not isinstance(data, dict) or not isinstance(data.get("formations"), list):
        return []
    return [f for f in data["formations"] if isinstance(f, dict)]


def save_formations(formations: list[dict]):
    """原子写：先落 .tmp 再 replace（同 data_relocation._write_json 风格）。"""
    path = _formations_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"formations": formations}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    temporary.replace(path)


def validate_formation(record: dict, existing: list[dict] | None = None) -> str | None:
    """校验一条预设；返回错误消息或 None。

    槽位值至少含 sword_catalog_id/name_zh 其一（身份铁律同
    formation_editor：sword_catalog_id 是刀种同位键，name_zh 可过名册
    校正）；slots 允许空 dict（=还没指定人，应用时会如实拦下）。
    """
    if not isinstance(record, dict):
        return "预设记录必须是 dict"
    name = record.get("name")
    if not isinstance(name, str) or not name.strip():
        return "预设名字不能为空"
    if len(name.strip()) > 20:
        return "预设名字最多 20 字"
    team = record.get("target_team")
    if not isinstance(team, int) or isinstance(team, bool) or not 1 <= team <= 5:
        return "目标部队必须是 1~5 的整数"
    slots = record.get("slots")
    if not isinstance(slots, dict):
        return "slots 必须是 dict（槽位号 → 目标条目）"
    if len(slots) > 6:
        return "slots 最多 6 个键"
    for key, entry in slots.items():
        if not isinstance(key, str) or key not in _SLOT_KEYS:
            return f"槽位键必须是 '1'~'6'（收到 {key!r}）"
        if not isinstance(entry, dict):
            return f"槽位 {key} 的目标必须是 dict"
        sid = entry.get("sword_catalog_id")
        nm = entry.get("name_zh")
        has_id = isinstance(sid, str) and bool(sid.strip())
        has_name = isinstance(nm, str) and bool(nm.strip())
        if not has_id and not has_name:
            return f"槽位 {key} 缺身份：sword_catalog_id/name_zh 至少给一样"
    fid = record.get("id")
    if fid is not None:
        if not isinstance(fid, str) or not _ID_RE.match(fid):
            return "id 只能是小写字母和数字（[a-z0-9]+）"
        for other in existing or []:
            if isinstance(other, dict) and other.get("id") == fid:
                return f"id {fid} 已被别的预设占用"
    return None


def new_formation_id(existing) -> str:
    """分配 pf1..pf5 里第一个空位；满了抛 ValueError。"""
    used = {f.get("id") for f in existing or [] if isinstance(f, dict)}
    for i in range(1, MAX_FORMATIONS + 1):
        fid = f"pf{i}"
        if fid not in used:
            return fid
    raise ValueError("预设编队最多 5 套")


def find_formation(formations, fid) -> dict | None:
    for f in formations or []:
        if isinstance(f, dict) and f.get("id") == fid:
            return f
    return None
