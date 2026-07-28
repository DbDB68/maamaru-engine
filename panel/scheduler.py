# -*- coding: utf-8 -*-
"""
远征时刻表 —— MAA 基建排班那种：用户自己排"几时几分，部队x 去 x-x"

数据在 panel/expedition_schedule.json：
  {"entries": [{"time":"06:40", "team_no":5, "map_code":"E2",
                "enabled":true, "last_fired":"2026-07-28"}, ...]}

调度线程每 30 秒看一眼：到点、启用中、今天没派过、当前没别的脚本在跑
→ 用 ScriptRunner 起一次 "dispatch" 脚本（日志走面板正常管道）。
面板关着就不会派（跟 MAA 一样，程序得开着）。
"""

import json
import threading
import time
from pathlib import Path

_SCHED_PATH = Path(__file__).resolve().parent / "expedition_schedule.json"
_MAPS_PATH = (Path(__file__).resolve().parent.parent
              / "touken" / "data" / "expedition_maps.json")


def load_entries() -> list:
    try:
        if _SCHED_PATH.exists():
            d = json.loads(_SCHED_PATH.read_text(encoding="utf-8"))
            return list(d.get("entries", []))
    except Exception:
        pass
    return []


def save_entries(entries: list):
    _SCHED_PATH.write_text(
        json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8")


def map_options() -> list:
    """给前端下拉用：全部远征图（按时代、卡位排序）"""
    try:
        d = json.loads(_MAPS_PATH.read_text(encoding="utf-8"))
        out = []
        for code, m in d.get("maps", {}).items():
            dur = int(m.get("duration_min", 0))
            out.append({
                "code": code,
                "era": m["era"],
                "slot": m["slot"],
                "name": m.get("name") or code,
                "duration_text": f"{dur // 60}h{dur % 60:02d}分" if dur >= 60 else f"{dur}分",
            })
        out.sort(key=lambda x: (x["era"], x["slot"]))
        return out
    except Exception:
        return []


def find_map(code: str):
    for m in map_options():
        if m["code"] == code:
            return m
    return None


def start_scheduler(config_path: str, emit_fn):
    """起后台调度线程。emit_fn(script, message) 负责把日志送进面板管道"""
    def _loop():
        from .script_runner import get_runner
        runner = get_runner()
        while True:
            try:
                hhmm = time.strftime("%H:%M")
                today = time.strftime("%Y-%m-%d")
                entries = load_entries()
                changed = False
                for e in entries:
                    if not e.get("enabled", True):
                        continue
                    if e.get("time") != hhmm:
                        continue
                    if e.get("last_fired") == today:
                        continue
                    if runner.is_running:
                        continue  # 同一分钟里下个 tick 再试
                    run_id = runner.start("dispatch", config_path, {
                        "team_no": str(e.get("team_no", 2)),
                        "map_code": e.get("map_code", ""),
                    })
                    if run_id:
                        e["last_fired"] = today
                        changed = True
                        emit_fn("scheduler",
                                f"🕐 到点啦！派部队{e.get('team_no')} 去 "
                                f"{e.get('map_code')}「{e.get('map_name', '')}」")
            except Exception as exc:  # noqa: BLE001 - 调度线程不许死
                print(f"[时刻表] 异常: {exc}", flush=True)
            time.sleep(30)

    t = threading.Thread(target=_loop, daemon=True, name="exp-scheduler")
    t.start()
    return t
