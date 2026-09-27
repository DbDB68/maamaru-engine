"""玩家选定的今日联队战时段。这里只记计划，不启动任务。"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from touken.runtime_paths import STATE_DIR

PLAN_PATH = STATE_DIR / "day_plan.json"


def load_plan(path: Path = PLAN_PATH) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return None
    blocks = raw.get("blocks")
    if (not isinstance(blocks, list) or not 1 <= len(blocks) <= 2
            or any(not isinstance(block, dict)
                   or type(block.get("start_min")) is not int
                   or type(block.get("runs")) is not int
                   for block in blocks)):
        return None
    return raw


def review_plan(plan: dict, timeline: dict) -> list[str]:
    """用当前时间表重审已保存的安排；旧安排不会被静默改写。"""
    issues = []
    activity = timeline.get("activity") or {}
    blocks = plan.get("blocks")
    if plan.get("day_start") != timeline.get("day_start"):
        issues.append("这不是今天的安排")
    if not activity or activity.get("name") != "联队战":
        issues.append("当前没有可核对的联队战进度")
    elif plan.get("event_end_at") != activity.get("event_end_at"):
        # 活动结束时间由当前卡片和墙钟反推，允许秒级读数误差。
        try:
            changed = abs(float(plan.get("event_end_at") or 0) - float(activity["event_end_at"])) > 60
        except (TypeError, ValueError, OverflowError):
            changed = True
        if changed:
            issues.append("活动时间已变化，请重新安排")
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 2:
        return issues + ["请安排一至两个时段"]
    pace = int(activity.get("seconds_per_loop") or 0)
    if pace <= 0:
        return issues + ["还没有可靠的本期圈速"]
    spans = []
    total = 0
    now_min = math.ceil((timeline["now"] - timeline["day_start"]) / 60)
    deadline = min(1440, math.floor((activity["event_end_at"] - timeline["day_start"]) / 60) - 5)
    for i, block in enumerate(blocks, 1):
        if not isinstance(block, dict) or type(block.get("start_min")) is not int or type(block.get("runs")) is not int:
            issues.append(f"第{i}段的时间或圈数不正确")
            continue
        start, runs = block["start_min"], block["runs"]
        if not 0 <= start < 1440 or not 1 <= runs <= 99:
            issues.append(f"第{i}段需要填写今天的时间和 1–99 圈")
            continue
        total += runs
        end = start + math.ceil(runs * pace / 60)
        spans.append((start, end))
        if start < now_min:
            issues.append(f"第{i}段的开工时间已经过去")
        if end > deadline:
            issues.append(f"第{i}段预计赶不上今天的收摊时间")
        for occupied in activity.get("occupied", []):
            if start < occupied["end_min"] and end > occupied["start_min"]:
                issues.append(f"第{i}段会撞上{occupied['label']}")
                break
    if total > int(activity.get("remaining_runs") or 0):
        issues.append("安排的圈数超过本期剩余圈数")
    if len(spans) == 2 and spans[0][0] > spans[1][0]:
        issues.append("请按开工时间排列时段")
    if len(spans) == 2 and spans[0][1] > spans[1][0]:
        issues.append("两个时段互相重叠")
    return issues


def save_plan(day_start: float, event_end_at: float, blocks: list[dict],
              path: Path = PLAN_PATH) -> dict:
    """原子替换；写入失败时原安排保持完整。"""
    plan = {"version": 1, "day_start": day_start,
            "event_end_at": event_end_at, "blocks": blocks}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temporary.replace(path)
    return plan
