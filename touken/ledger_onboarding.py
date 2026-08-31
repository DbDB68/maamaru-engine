"""空账本首次引导的持久状态与显示判定。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .telemetry import LEDGER_RESOURCES, TelemetryStore, _LEDGER_TZ, _loads


ONBOARDING_SCHEMA_VERSION = 1
ONBOARDING_FILENAME = "ledger_onboarding.json"
_VALID_STATUSES = frozenset(("active", "completed", "dismissed"))
_OBSERVATION_EVENT_TYPES = (
    "inventory.captured", "inventory.peek", "osaka.koban_session", "resource.change",
)


def _load_state(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("status") not in _VALID_STATUSES:
        return {}
    try:
        step = max(1, min(int(data.get("step") or 1), 3))
    except (TypeError, ValueError):
        step = 1
    return {"status": data["status"], "step": step}


def _save_state(path: Path, *, status: str, step: int) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": ONBOARDING_SCHEMA_VERSION,
        "status": status,
        "step": max(1, min(int(step), 3)),
        "updated_at": datetime.now(_LEDGER_TZ).isoformat(timespec="seconds"),
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _payload_has_observation(event_type: str, payload: dict[str, Any]) -> bool:
    if event_type == "inventory.captured":
        resources = payload.get("resources")
        return isinstance(resources, dict) and any(
            name in LEDGER_RESOURCES and _is_number(value)
            for name, value in resources.items()
        )
    if event_type == "inventory.peek":
        return any(_is_number(payload.get(name)) for name in LEDGER_RESOURCES)
    if event_type == "osaka.koban_session":
        return any(_is_number(payload.get(name)) for name in ("before", "after"))
    if event_type == "resource.change":
        return (payload.get("resource") in LEDGER_RESOURCES
                and any(_is_number(payload.get(name))
                        for name in ("before", "after")))
    return False


def has_inventory_observation(store: TelemetryStore) -> bool:
    """判断账房是否曾经见过至少一项真实家底，不受当前统计窗口限制。"""
    marks = ",".join("?" * len(_OBSERVATION_EVENT_TYPES))
    rows = store._conn().execute(
        "SELECT event_type, payload FROM events "
        f"WHERE event_type IN ({marks}) ORDER BY id DESC",
        _OBSERVATION_EVENT_TYPES,
    )
    return any(_payload_has_observation(row["event_type"], _loads(row["payload"], {}))
               for row in rows)


def get_onboarding(store: TelemetryStore, path: Path) -> dict:
    state = _load_state(Path(path))
    has_inventory = has_inventory_observation(store)
    status = state.get("status")
    step = int(state.get("step") or 1)
    if status in {"completed", "dismissed"}:
        return {
            "schema_version": ONBOARDING_SCHEMA_VERSION,
            "visible": False, "status": status, "step": step,
            "has_inventory": has_inventory, "reason": status,
        }
    if status == "active":
        if has_inventory and step == 1:
            step = 2
        return {
            "schema_version": ONBOARDING_SCHEMA_VERSION,
            "visible": True, "status": "active", "step": step,
            "has_inventory": has_inventory, "reason": "active",
        }
    if has_inventory:
        return {
            "schema_version": ONBOARDING_SCHEMA_VERSION,
            "visible": False, "status": "not_needed", "step": 1,
            "has_inventory": True, "reason": "existing_ledger",
        }
    return {
        "schema_version": ONBOARDING_SCHEMA_VERSION,
        "visible": True, "status": "pending", "step": 1,
        "has_inventory": False, "reason": "empty_ledger",
    }


def update_onboarding(store: TelemetryStore, path: Path, action: str,
                      *, step: int | None = None) -> dict:
    current = get_onboarding(store, path)
    if current["status"] in {"completed", "dismissed", "not_needed"}:
        return current
    action = str(action or "").strip().lower()
    if action == "start":
        status, next_step = "active", max(1, int(current["step"]))
    elif action == "advance":
        if step not in {2, 3}:
            raise ValueError("引导步骤不正确")
        status, next_step = "active", max(int(current["step"]), int(step))
    elif action == "complete":
        status, next_step = "completed", 3
    elif action == "dismiss":
        status, next_step = "dismissed", int(current["step"])
    else:
        raise ValueError("不认识的引导操作")
    _save_state(Path(path), status=status, step=next_step)
    return get_onboarding(store, path)
