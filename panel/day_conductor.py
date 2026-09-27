"""今天的联队战安排：在任务流外守时，到点只启动已授权的单段流程。"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import threading
import time
from pathlib import Path

from touken.runtime_paths import STATE_DIR

from . import day_timeline, scheduler, workflow
from .day_plan import load_plan, review_plan


STATE_PATH = STATE_DIR / "day_conductor.json"
BUILTIN_ID = "builtin-scheduled-raid"
START_GRACE_SEC = 60
_LOCK = threading.RLock()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")).hexdigest()


def load_state(path: Path = STATE_PATH) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(raw, dict) or raw.get("version") != 1
            or not isinstance(raw.get("blocks"), list)):
        return None
    if any(not isinstance(block, dict)
           or type(block.get("start_min")) is not int
           or type(block.get("runs")) is not int
           or block.get("status") not in {"pending", "running", "ended",
                                           "interrupted", "missed", "blocked"}
           for block in raw["blocks"]):
        return None
    return raw


def _save(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temp.replace(path)


def _plan_signature(plan: dict) -> str:
    return _digest({key: plan.get(key) for key in
                    ("day_start", "event_end_at", "blocks")})


def _preset(workflow_id: str) -> dict:
    if workflow_id == BUILTIN_ID:
        return {"id": BUILTIN_ID, "name": "按联队战设置开工",
                "nodes": [{"type": "raid", "params": {}, "on_error": "stop"}],
                "after": "none", "daily_mode": False}
    preset = workflow.find_preset(workflow_id)
    if not preset:
        raise ValueError("这份任务流已经找不到了")
    return preset


def _eligible(preset: dict) -> bool:
    try:
        nodes = workflow.normalize_nodes(preset.get("nodes"))
    except workflow.WorkflowError:
        return False
    return (len(nodes) == 1 and nodes[0]["type"] == "raid"
            and nodes[0]["on_error"] == "stop"
            and preset.get("after", "none") == "none"
            and not preset.get("daily_mode", False))


def options() -> list[dict]:
    presets = [_preset(BUILTIN_ID), *workflow.list_presets()]
    return [{"id": p["id"], "name": p["name"]} for p in presets if _eligible(p)]


def workflow_spec(workflow_id: str, raid_settings: dict | None = None) -> dict:
    preset = _preset(workflow_id)
    if not _eligible(preset):
        raise ValueError("定时安排目前只支持单个联队战步骤、翻车即停的任务流")
    source_node = workflow.normalize_nodes(preset["nodes"])[0]
    saved = raid_settings if isinstance(raid_settings, dict) else {}
    effective = {**saved, **source_node["params"]}
    node = {**source_node, "params": effective}
    raw_team = effective.get("team_no", "3")
    if isinstance(raw_team, str) and raw_team.startswith("preset:"):
        from touken.custom_formations import load_formations
        formation = next((item for item in load_formations()
                          if item.get("id") == raw_team[7:]), None)
        raw_team = formation.get("target_team") if formation else None
    try:
        team_no = int(raw_team)
    except (TypeError, ValueError):
        team_no = 0
    if team_no not in (1, 2, 3, 4, 5):
        raise ValueError("这份任务流的出阵部队还没认清，请先检查联队战设置")
    signature_payload = {"raid_settings": saved, "team_no": team_no}
    source_signature = _digest({**signature_payload, "nodes": [source_node]})
    effective_signature = _digest({**signature_payload, "nodes": [node]})
    return {"name": preset["name"], "team_no": team_no, "nodes": [node],
            "signature": source_signature,
            "compatible_signatures": {source_signature, effective_signature}}


def _for_team(timeline: dict, team_no: int) -> dict:
    result = {**timeline}
    activity = timeline.get("activity")
    if activity:
        result["activity"] = {**activity, "occupied": day_timeline._occupied_segments(
            timeline.get("expeditions", []), scheduler.load_config(), team_no)}
    return result


def _block_issues(block: dict, timeline: dict) -> list[str]:
    activity = timeline.get("activity") or {}
    if activity.get("name") != "联队战":
        return ["当前没有可核对的联队战进度"]
    pace = int(activity.get("seconds_per_loop") or 0)
    if pace <= 0:
        return ["还没有可靠的本期圈速"]
    start, runs = block["start_min"], block["runs"]
    end = start + math.ceil(runs * pace / 60)
    deadline = min(1440, math.floor(
        (activity["event_end_at"] - timeline["day_start"]) / 60) - 5)
    issues = []
    if end > deadline:
        issues.append("预计赶不上今天的收摊时间")
    if runs > int(activity.get("remaining_runs") or 0):
        issues.append("安排圈数超过本期剩余圈数")
    for occupied in activity.get("occupied", []):
        if start < occupied["end_min"] and end > occupied["start_min"]:
            issues.append(f"会撞上{occupied['label']}")
            break
    return issues


def arm(plan: dict, timeline: dict, workflow_id: str, raid_settings: dict,
        path: Path = STATE_PATH) -> dict:
    with _LOCK:
        old = load_state(path)
        if old and any(b.get("status") == "running" for b in old["blocks"]):
            raise ValueError("已有一段正在执行，等它收工后再改大总管")
        spec = workflow_spec(workflow_id, raid_settings)
        issues = review_plan(plan, _for_team(timeline, spec["team_no"]))
        if issues:
            raise ValueError("；".join(issues))
        state = {"version": 1, "enabled": True,
                 "day_start": plan["day_start"],
                 "plan_signature": _plan_signature(plan),
                 "workflow_id": workflow_id,
                 "workflow_name": spec["name"],
                 "workflow_signature": spec["signature"],
                 "blocks": [{**block, "status": "pending"} for block in plan["blocks"]]}
        _save(state, path)
        return state


def disarm(path: Path = STATE_PATH) -> dict | None:
    with _LOCK:
        state = load_state(path)
        if state and state.get("enabled"):
            state["enabled"] = False
            _save(state, path)
        return state


def projection(plan: dict | None, timeline: dict, raid_settings: dict,
               path: Path = STATE_PATH) -> dict:
    state = load_state(path)
    result = {"enabled": False, "workflow_id": BUILTIN_ID,
              "workflow_name": "按联队战设置开工", "blocks": [],
              "issues": [], "options": options()}
    if not state or state.get("day_start") != timeline.get("day_start"):
        return result
    result.update({key: state.get(key) for key in
                   ("enabled", "workflow_id", "workflow_name", "blocks")})
    if not state.get("enabled"):
        return result
    if not plan or _plan_signature(plan) != state.get("plan_signature"):
        result["issues"].append("今天的安排改过了，请重新开启大总管")
        return result
    try:
        spec = workflow_spec(state["workflow_id"], raid_settings)
    except ValueError as exc:
        result["issues"].append(str(exc))
        return result
    if spec["signature"] != state.get("workflow_signature"):
        result["issues"].append("联队战设置或任务流改过了，请重新开启大总管")
        return result
    if timeline.get("activity") or not any(
            block.get("status") == "running" for block in state["blocks"]):
        adjusted = _for_team(timeline, spec["team_no"])
        for block in state["blocks"]:
            if block.get("status") == "pending":
                result["issues"].extend(_block_issues(block, adjusted))
    return result


def tick(now: float, runner, timeline_fn, raid_settings_fn, config_path: str,
         emit_fn, path: Path = STATE_PATH, plan_path: Path | None = None) -> None:
    """巡检一次；错过、受阻或中断均不补跑，单段最多启动一次。"""
    with _LOCK:
        state = load_state(path)
        if not state:
            return
        changed = False
        for block in state["blocks"]:
            if block.get("status") != "running":
                continue
            if runner.is_running and runner.current_run_id == block.get("run_id"):
                continue
            last_run_id, last_status = runner.last_run_result
            block["status"] = ("ended" if last_run_id == block.get("run_id")
                               and last_status == "completed" else "interrupted")
            block["finished_at"] = now
            if block["status"] == "interrupted":
                state["enabled"] = False
                block["reason"] = ("任务流失败，后续已停用" if last_run_id == block.get("run_id")
                                   and last_status in {"failed", "stopped", "watchdog"}
                                   else "执行状态不明，后续已停用")
            changed = True
            emit_fn("conductor", "[大总管] 联队战时段已结束，请到成绩单看实际圈数"
                    if block["status"] == "ended" else
                    f"[大总管] {block['reason']}")
        if not state.get("enabled"):
            if changed:
                _save(state, path)
            return
        plan = load_plan(plan_path) if plan_path else load_plan()
        if (not plan or _plan_signature(plan) != state.get("plan_signature")
                or not state["day_start"] <= now < state["day_start"] + 86400):
            state["enabled"] = False
            changed = True
            emit_fn("conductor", "[大总管] 今日安排变了或已经换日，自动开工已停用")
        else:
            try:
                spec = workflow_spec(state["workflow_id"], raid_settings_fn())
                if spec["signature"] != state.get("workflow_signature"):
                    raise ValueError("联队战设置或任务流已修改")
            except ValueError as exc:
                state["enabled"] = False
                changed = True
                emit_fn("conductor", f"[大总管] {exc}，自动开工已停用")
        if not state.get("enabled"):
            _save(state, path)
            return
        if any(b.get("status") == "running" for b in state["blocks"]):
            if changed:
                _save(state, path)
            return
        for block in state["blocks"]:
            if block.get("status") != "pending":
                continue
            due = float(state["day_start"]) + block["start_min"] * 60
            if now < due:
                break
            if now > due + START_GRACE_SEC:
                block["status"] = "missed"
                changed = True
                emit_fn("conductor", "[大总管] 联队战开工时间已错过，本段不会补跑")
                continue
            if runner.is_running:
                break  # 只等 60 秒；远征或其他任务优先，不抢运行位置
            timeline = timeline_fn()
            adjusted = _for_team(timeline, spec["team_no"])
            issues = _block_issues(block, adjusted)
            if (not adjusted.get("activity") or abs(float(plan["event_end_at"])
                    - float(adjusted["activity"]["event_end_at"])) > 60):
                issues.append("活动时间已变化")
            if issues:
                block["status"] = "blocked"
                block["reason"] = "；".join(issues)
                changed = True
                emit_fn("conductor", f"[大总管] 本段没有开工：{block['reason']}")
                continue
            run_id = runner.start("workflow", config_path, {
                "workflow_id": state["workflow_id"],
                "scheduled_raid_runs": block["runs"],
                "scheduled_workflow_signature": state["workflow_signature"],
            })
            if run_id:
                block.update(status="running", run_id=run_id, started_at=now)
                changed = True
                emit_fn("conductor", f"[大总管] 联队战开工，安排 {block['runs']} 圈")
            break
        if changed:
            _save(state, path)


def start_conductor(config_path: str, runner, timeline_fn, raid_settings_fn,
                    emit_fn):
    def _loop():
        while True:
            try:
                tick(time.time(), runner, timeline_fn, raid_settings_fn,
                     config_path, emit_fn)
            except Exception as exc:
                print(f"[大总管] 巡检异常: {exc}", flush=True)
            time.sleep(5)

    thread = threading.Thread(target=_loop, daemon=True, name="day-conductor")
    thread.start()
    return thread
