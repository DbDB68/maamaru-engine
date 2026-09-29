"""今天单班远征的跳过/强制选择；与循环排班配置分开保存。

skipped：今天这班别跑（排班开着也跳过）。
forced：今天这班一定要跑（排班总开关关着也单独走状态机）。
两者互斥，后写的赢；forced 不 lifted 自定义排班里被关掉的条目。
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from touken.runtime_paths import STATE_DIR

CHOICES_PATH = STATE_DIR / "expedition_day_choices.json"
_WRITE_LOCK = threading.Lock()


def load_choice_sets(path: Path = CHOICES_PATH) -> tuple[dict, dict]:
    """返回 (skipped, forced) 两个字典；文件坏了都按空处理。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    if not isinstance(value, dict) or value.get("version") != 1:
        return {}, {}
    skipped = value.get("skipped")
    forced = value.get("forced")
    return (skipped if isinstance(skipped, dict) else {},
            forced if isinstance(forced, dict) else {})


def load_choices(path: Path = CHOICES_PATH) -> dict:
    """兼容旧调用：只取 skipped 字典。"""
    return load_choice_sets(path)[0]


def _record_matches(record, *, team_no: int, map_code: str) -> bool:
    return (isinstance(record, dict)
            and record.get("team_no") == team_no
            and record.get("map_code") == map_code)


def is_skipped(choices: dict, *, key: str, team_no: int,
               map_code: str, planned_at: float) -> bool:
    """班次键外再核对队伍和地图；前班迟到顺延时仍跳过同一班。"""
    return _record_matches(choices.get(key), team_no=team_no, map_code=map_code)


def is_forced(forced: dict, *, key: str, team_no: int, map_code: str) -> bool:
    """今日单班强制启用；核对口径同 is_skipped。"""
    return _record_matches(forced.get(key), team_no=team_no, map_code=map_code)


def _write_sets(skipped: dict, forced: dict, path: Path) -> None:
    payload = {"version": 1, "skipped": skipped, "forced": forced}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temporary.replace(path)


def set_skipped(*, key: str, team_no: int, map_code: str,
                planned_at: float, skipped: bool,
                path: Path = CHOICES_PATH) -> dict:
    """原子写入并保留上一版，失败时原文件仍在。记跳过的同时清掉强制。"""
    with _WRITE_LOCK:
        skipped_map, forced_map = load_choice_sets(path)
        if skipped:
            skipped_map[key] = {"team_no": team_no, "map_code": map_code,
                                "planned_at": planned_at}
            forced_map.pop(key, None)
        else:
            skipped_map.pop(key, None)
        _write_sets(skipped_map, forced_map, path)
        return skipped_map


def set_forced(*, key: str, team_no: int, map_code: str,
               planned_at: float, forced: bool,
               path: Path = CHOICES_PATH) -> dict:
    """记强制的同时清掉跳过；排班开关关着就靠它单独跑这一班。"""
    with _WRITE_LOCK:
        skipped_map, forced_map = load_choice_sets(path)
        if forced:
            forced_map[key] = {"team_no": team_no, "map_code": map_code,
                               "planned_at": planned_at}
            skipped_map.pop(key, None)
        else:
            forced_map.pop(key, None)
        _write_sets(skipped_map, forced_map, path)
        return forced_map


def set_slot_intention(*, key: str, team_no: int, map_code: str,
                       planned_at: float, will_run: bool, base_enabled: bool,
                       path: Path = CHOICES_PATH) -> dict:
    """按目标状态一键定下今天这班：will_run=True 时排班开着只清选择、
    关着记 forced；will_run=False 记 skipped。skipped/forced 互斥。"""
    with _WRITE_LOCK:
        skipped_map, forced_map = load_choice_sets(path)
        if will_run:
            skipped_map.pop(key, None)
            if base_enabled:
                forced_map.pop(key, None)
            else:
                forced_map[key] = {"team_no": team_no, "map_code": map_code,
                                   "planned_at": planned_at}
        else:
            forced_map.pop(key, None)
            skipped_map[key] = {"team_no": team_no, "map_code": map_code,
                                "planned_at": planned_at}
        _write_sets(skipped_map, forced_map, path)
        return {"skipped": skipped_map, "forced": forced_map}
