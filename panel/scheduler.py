# -*- coding: utf-8 -*-
"""远征计划：常用安排、攻略预设与自定义时刻表。"""

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from touken.runtime_paths import SCHEDULE_PATH

_SCHED_PATH = SCHEDULE_PATH
_MAPS_PATH = (Path(__file__).resolve().parent.parent
              / "touken" / "data" / "expedition_maps.json")

TEAM_NAMES = {1: "部队一", 2: "部队二", 3: "部队三", 4: "部队四", 5: "部队五"}
PRESET_TOTALS = {
    "木炭": "木炭 3195 · 玉钢 1860 · 冷却材 2340 · 砥石 2640 · 小判 2500 · 委托符 13",
    "玉钢": "木炭 1710 · 玉钢 4995 · 冷却材 1125 · 砥石 1830 · 小判 1600 · 加速符 3/8",
    "冷却材": "木炭 2385 · 玉钢 1995 · 冷却材 6615 · 砥石 1620 · 小判 2000 · 委托符 13 · 加速符 8",
    "砥石": "木炭 825 · 玉钢 2025 · 冷却材 270 · 砥石 6375 · 小判 3900 · 加速符 3/1",
    "小判": "木炭 1425 · 玉钢 1860 · 冷却材 2100 · 砥石 3900 · 小判 6100",
    "加速符": "木炭 960 · 玉钢 3435 · 冷却材 1185 · 砥石 4395 · 小判 700 · 加速符 15 · 委托符 2",
    "委托符": "木炭 2745 · 玉钢 2580 · 冷却材 3240 · 砥石 1980 · 小判 1100 · 委托符 19 · 加速符 1",
}

# 每条 lane 是从开始时间起依次执行的地图。地图时长来自 expedition_maps.json。
PRESETS = {
    "木炭": [
        ["B3"] * 8 + ["D4"],
        ["C1"] * 4 + ["C4"],
        ["D4", "D4", "D1", "C3"],
    ],
    "玉钢": [
        ["D2", "D2", "D2", "A4", "C4"],
        ["B4"] * 5 + ["A4", "C3"],
        ["C1", "C1", "C1", "E1"],
    ],
    "冷却材": [
        ["B1"] * 8 + ["E1"],
        ["B3"] * 7 + ["C3"],
        ["D1"] * 6 + ["D3"],
    ],
    "砥石": [
        ["B2"] * 5 + ["A4", "D4"],
        ["D4", "D4", "A4", "B1", "B1", "D2"],
        ["C4", "C4", "C4"],
    ],
    "小判": [
        ["D4", "D4", "B2", "D4"],
        ["D2", "B2", "D2", "C3"],
        ["B1"] * 10 + ["D2"],
    ],
    "加速符": [
        ["B4"] * 6 + ["C4"],
        ["C2"] * 5 + ["A4", "D4"],
        ["C4", "B3", "B3", "E1"],
    ],
    "委托符": [
        ["B3"] * 8 + ["C4"],
        ["D1"] * 7 + ["C3"],
        ["C1"] * 4 + ["D4"],
    ],
}


def _defaults() -> dict:
    return {
        "version": 2,
        "common_plan": [
            {"team_no": n, "map_code": "E2", "enabled": False}
            for n in range(1, 6)
        ],
        "automation": {
            "enabled": False,
            "mode": "preset",
            "preset": "小判",
            "start_time": "08:00",
            "teams": [2, 3, 4],
            "capitalist": False,
            "paused_until": "",
            "last_runs": {},
            "lane_shifts": {},
        },
        "entries": [],
    }


def load_config() -> dict:
    cfg = _defaults()
    try:
        if _SCHED_PATH.exists():
            raw = json.loads(_SCHED_PATH.read_text(encoding="utf-8"))
            # 兼容旧文件 {"entries": [...]}
            if isinstance(raw, dict):
                cfg.update({k: v for k, v in raw.items() if k in cfg})
                if isinstance(raw.get("automation"), dict):
                    merged = _defaults()["automation"]
                    merged.update(raw["automation"])
                    cfg["automation"] = merged
    except Exception:
        pass
    return cfg


def save_config(cfg: dict):
    _SCHED_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def load_entries() -> list:
    return list(load_config().get("entries", []))


def save_entries(entries: list):
    cfg = load_config()
    cfg["entries"] = entries
    save_config(cfg)


def map_options() -> list:
    try:
        d = json.loads(_MAPS_PATH.read_text(encoding="utf-8"))
        out = []
        for code, m in d.get("maps", {}).items():
            dur = int(m.get("duration_min", 0))
            out.append({
                "code": code, "era": m["era"], "slot": m["slot"],
                "name": m.get("name") or code, "duration_min": dur,
                "duration_text": f"{dur // 60}h{dur % 60:02d}分" if dur >= 60 else f"{dur}分",
            })
        out.sort(key=lambda x: (x["era"], x["slot"]))
        return out
    except Exception:
        return []


def find_map(code: str):
    return next((m for m in map_options() if m["code"] == code), None)


def preset_payload() -> dict:
    maps = {m["code"]: m for m in map_options()}
    result = {}
    for name, lanes in PRESETS.items():
        rendered = []
        for lane in lanes:
            minute = 0
            parts = []
            for code in lane:
                m = maps.get(code)
                if not m:
                    continue
                parts.append({"offset_min": minute, "map_code": code,
                              "duration_min": m["duration_min"]})
                minute += m["duration_min"]
            rendered.append(parts)
        result[name] = {"lanes": rendered, "totals": PRESET_TOTALS.get(name, "")}
    return result


def _minute_of_day(hhmm: str) -> int:
    try:
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m
    except Exception:
        return 480


def _emulator_ready(config_path: str) -> bool:
    """只检查 ADB；绝不调用 ensure_emulator，避免擅自启动模拟器。"""
    try:
        from touken.emulator import adb_alive
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return adb_alive(cfg.get("adb_path", ""), cfg.get("adb_address", ""))
    except Exception:
        return False


def _preset_due(cfg: dict, now_min: int, today: str) -> list:
    auto = cfg["automation"]
    preset = preset_payload().get(auto.get("preset"), {})
    lanes = preset.get("lanes", [])
    teams = auto.get("teams", [2, 3, 4])
    start = _minute_of_day(auto.get("start_time", "08:00"))
    elapsed = (now_min - start) % 1440
    cycle_day = datetime.now().date()
    if now_min < start:
        cycle_day -= timedelta(days=1)
    cycle_label = cycle_day.isoformat()
    grace = 10
    out = []
    for idx, lane in enumerate(lanes[:3]):
        if idx >= len(teams):
            continue
        shift_key = f"{cycle_label}:lane:{idx}"
        shift = int(auto.get("lane_shifts", {}).get(shift_key, 0))
        current = None
        for part in lane:
            actual_offset = part["offset_min"] + shift
            if actual_offset <= elapsed < actual_offset + part["duration_min"]:
                current = part
                break
        if not current:
            continue
        late = elapsed - (current["offset_min"] + shift)
        if late > grace and not auto.get("capitalist", False):
            continue
        key = f"{cycle_label}:preset:{idx}:{current['offset_min']}"
        if auto.get("last_runs", {}).get(key):
            continue
        out.append({"key": key, "team_no": int(teams[idx]),
                    "map_code": current["map_code"], "late_min": late,
                    "shift_key": shift_key,
                    "apply_shift": late if auto.get("capitalist") and not shift and late > grace else 0})
    return out


def _custom_due(cfg: dict, now_min: int, today: str) -> list:
    auto = cfg["automation"]
    grace = 10
    out = []
    for idx, e in enumerate(cfg.get("entries", [])):
        if not e.get("enabled", True):
            continue
        due = _minute_of_day(e.get("time", "08:00"))
        if now_min < due:
            continue
        late = (now_min - due) % 1440
        if late > grace and not auto.get("capitalist", False):
            continue
        key = f"{today}:custom:{idx}:{e.get('time')}"
        if auto.get("last_runs", {}).get(key):
            continue
        out.append({"key": key, "team_no": int(e.get("team_no", 2)),
                    "map_code": e.get("map_code", ""), "late_min": late})
    return out


def start_scheduler(config_path: str, emit_fn):
    """30 秒巡检；先预告 15 秒，再接管游戏。"""
    def _loop():
        from .script_runner import get_runner
        runner = get_runner()
        pending = {}
        while True:
            try:
                cfg = load_config()
                auto = cfg.get("automation", {})
                if not auto.get("enabled"):
                    pending.clear()
                    time.sleep(5)
                    continue
                paused = auto.get("paused_until", "")
                if paused and paused > time.strftime("%Y-%m-%d %H:%M:%S"):
                    pending.clear()
                    time.sleep(5)
                    continue
                now = time.time()
                now_min = int(time.strftime("%H")) * 60 + int(time.strftime("%M"))
                today = time.strftime("%Y-%m-%d")
                due = (_preset_due(cfg, now_min, today)
                       if auto.get("mode") == "preset"
                       else _custom_due(cfg, now_min, today))
                ready = _emulator_ready(config_path)
                if runner.is_running or not ready:
                    pending.clear()
                elif due:
                    job = due[0]
                    if job["key"] not in pending:
                        pending[job["key"]] = now
                        emit_fn("scheduler",
                                f"⏳ 15 秒后接管游戏：{TEAM_NAMES[job['team_no']]} → "
                                f"{job['map_code']}（可在远征配置里暂停）")
                    elif now - pending[job["key"]] >= 15:
                        run_id = runner.start("dispatch", config_path, {
                            "team_no": str(job["team_no"]),
                            "map_code": job["map_code"],
                        })
                        if run_id:
                            auto.setdefault("last_runs", {})[job["key"]] = time.strftime(
                                "%Y-%m-%d %H:%M:%S")
                            if job.get("apply_shift"):
                                auto.setdefault("lane_shifts", {})[job["shift_key"]] = job["apply_shift"]
                            cfg["automation"] = auto
                            save_config(cfg)
                            pending.pop(job["key"], None)
                            emit_fn("scheduler",
                                    f"🕐 开始派遣 {TEAM_NAMES[job['team_no']]} → {job['map_code']}")
                active_keys = {j["key"] for j in due}
                pending = {k: v for k, v in pending.items() if k in active_keys}
            except Exception as exc:
                print(f"[时刻表] 异常: {exc}", flush=True)
            time.sleep(5)

    t = threading.Thread(target=_loop, daemon=True, name="exp-scheduler")
    t.start()
    return t
