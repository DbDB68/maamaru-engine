# -*- coding: utf-8 -*-
"""
异常与通知中心 · 事故单核心

统一格式（一张事故单回答六个问题）：
  code        去重编号（同类事故共用一个编号，重复发生只加次数不刷屏）
  title       发生了什么
  cause       可能原因
  action      现在该做什么
  needs_human 是否必须人工接管
  entry       对应任务入口（前端据此跳转到相关页面）

这一层只管模型、落盘、去重和状态流转，不认识 QQ / ntfy / HTTP。
检测消息、决定要不要喊人，是 panel 层的事（panel/incident_feed.py）。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field

from .runtime_paths import STATE_DIR

_INCIDENTS_FILE = STATE_DIR / "incidents.json"
_MAX_INCIDENTS = 100
_SCHEMA_VERSION = 1

# 同一编号的事故单，冷却期内重复上报只更新计数，不重新激活已确认的工单
_REACTIVATE_COOLDOWN_SEC = 30 * 60

SEVERITIES = ("info", "warning", "urgent")

_lock = threading.Lock()


@dataclass
class Incident:
    code: str                       # 去重编号，如 "crash:daily" / "watchdog:osaka"
    severity: str                   # info / warning / urgent
    title: str                      # 发生了什么
    cause: str                      # 可能原因
    action: str                     # 现在该做什么
    needs_human: bool               # 是否必须人工接管
    entry: dict = field(default_factory=dict)  # 对应任务入口 {"tab": "report", "script": "daily"}
    status: str = "active"          # active / acknowledged / resolved
    first_seen: float = 0.0
    last_seen: float = 0.0
    count: int = 1                  # 重复发生次数

    def to_dict(self) -> dict:
        return asdict(self)


def _load(path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw.get("items")
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _save(path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": _SCHEMA_VERSION, "saved_at": time.time(), "items": items}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def report_incident(
    code: str,
    *,
    severity: str,
    title: str,
    cause: str,
    action: str,
    needs_human: bool,
    entry: dict | None = None,
    path=None,
) -> tuple[dict, bool]:
    """上报一张事故单。返回 (事故单 dict, 是否新激活)。

    去重规则：编号相同且未结案的事故单已存在时，只累加次数和最后发生时间；
    已确认（acknowledged）的事故单在冷却期内复发也不重新激活，避免同一毛病反复喊人。
    """
    if severity not in SEVERITIES:
        severity = "warning"
    path = path or _INCIDENTS_FILE
    now = time.time()
    with _lock:
        items = _load(path)
        for item in items:
            if item.get("code") != code or item.get("status") == "resolved":
                continue
            item["last_seen"] = now
            item["count"] = int(item.get("count", 1)) + 1
            # 冷却期外的复发重新激活（让铃铛再亮一次），冷却期内只记次数
            reactivated = False
            if item.get("status") == "acknowledged" and now - float(item.get("last_seen_ack", 0)) > _REACTIVATE_COOLDOWN_SEC:
                item["status"] = "active"
                reactivated = True
            _save(path, items)
            return item, reactivated
        incident = Incident(
            code=code, severity=severity, title=title, cause=cause, action=action,
            needs_human=needs_human, entry=entry or {},
            first_seen=now, last_seen=now,
        )
        items.insert(0, incident.to_dict())
        del items[_MAX_INCIDENTS:]
        _save(path, items)
        return incident.to_dict(), True


def resolve_incidents(code_prefix: str, *, path=None) -> int:
    """事情自己好了（比如日课全绿）时按编号前缀销案。返回销了几张。"""
    path = path or _INCIDENTS_FILE
    with _lock:
        items = _load(path)
        resolved = 0
        for item in items:
            if item.get("status") != "resolved" and str(item.get("code", "")).startswith(code_prefix):
                item["status"] = "resolved"
                resolved += 1
        if resolved:
            _save(path, items)
    return resolved


def set_status(code: str, status: str, *, path=None) -> dict | None:
    """确认 / 销案指定编号的事故单（含复发历史里最近的一张活跃单）。"""
    if status not in ("active", "acknowledged", "resolved"):
        return None
    path = path or _INCIDENTS_FILE
    with _lock:
        items = _load(path)
        for item in items:
            if item.get("code") == code and item.get("status") != "resolved":
                item["status"] = status
                if status == "acknowledged":
                    item["last_seen_ack"] = time.time()
                _save(path, items)
                return item
    return None


def list_incidents(*, include_resolved: bool = True, path=None) -> list[dict]:
    """面板读取用：活跃的在前，按最后发生时间倒序。"""
    path = path or _INCIDENTS_FILE
    with _lock:
        items = _load(path)
    if not include_resolved:
        items = [item for item in items if item.get("status") != "resolved"]
    items.sort(key=lambda item: (item.get("status") == "resolved", -float(item.get("last_seen", 0))))
    return items
