"""今天单班远征的跳过选择；与循环排班配置分开保存。"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from touken.runtime_paths import STATE_DIR

CHOICES_PATH = STATE_DIR / "expedition_day_choices.json"
_WRITE_LOCK = threading.Lock()


def load_choices(path: Path = CHOICES_PATH) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict) or value.get("version") != 1:
        return {}
    skipped = value.get("skipped")
    return skipped if isinstance(skipped, dict) else {}


def is_skipped(choices: dict, *, key: str, team_no: int,
               map_code: str, planned_at: float) -> bool:
    """班次键外再核对队伍和地图；前班迟到顺延时仍跳过同一班。"""
    record = choices.get(key)
    return (isinstance(record, dict)
            and record.get("team_no") == team_no
            and record.get("map_code") == map_code)


def set_skipped(*, key: str, team_no: int, map_code: str,
                planned_at: float, skipped: bool,
                path: Path = CHOICES_PATH) -> dict:
    """原子写入并保留上一版，失败时原文件仍在。"""
    with _WRITE_LOCK:
        choices = dict(load_choices(path))
        if skipped:
            choices[key] = {"team_no": team_no, "map_code": map_code,
                            "planned_at": planned_at}
        else:
            choices.pop(key, None)
        payload = {"version": 1, "skipped": choices}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        temporary.replace(path)
        return choices
