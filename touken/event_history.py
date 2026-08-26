"""活动周期经验档案：每期活动打完后的实测总结，只增不删。

解决的问题（2026-08-26 牛老师立项）：复刻活动不能串期——
「江户城潜入调查·2026-08-27」和明年的江户城是两届，场均钥匙
不能直接混用；但规则相同时上期经验可以当本期的参考值。

档案在数据目录 event_history.json：
  {"schema_version": 1, "periods": [
    {"event": "江户城潜入调查", "start_date": "2026-08-27",
     "mechanics": "edocastle", "rules": {...规则快照...},
     "runs": 286, "keys_total": 1459, "keys_per_run": 5.1,
     "closed_at": 1694...}]}

规矩：只新增或安全迁移（备份+原子替换），原始记录永不删除。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 老 Python 兜底
    _TZ = timezone(timedelta(hours=8))

HISTORY_FILENAME = "event_history.json"
SCHEMA_VERSION = 1

# 规则指纹用的关键参数：这些变了就是「规则不同」，上期经验不能直接用
_RULE_KEYS = ("mechanics", "keys_total", "keys_per_box", "boxes",
              "ticket_price", "daily_free_tickets", "ticket_cap")


def period_key(name: str, card: dict) -> str | None:
    """一届活动的身份：活动名@开始日。没开始日就没有期次概念。"""
    start = card.get("start_date") or str(card.get("start_at") or "")[:10]
    if not start:
        return None
    return f"{name}@{start}"


def rules_fingerprint(card: dict) -> dict:
    """规则快照：两期指纹相同才算「规则相同」。"""
    return {key: card.get(key) for key in _RULE_KEYS}


def load_history(status_dir: Path) -> list[dict]:
    """读档案；文件缺失/损坏当空档案（不炸面板）。"""
    try:
        data = json.loads((Path(status_dir) / HISTORY_FILENAME)
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    periods = data.get("periods") if isinstance(data, dict) else data
    if not isinstance(periods, list):
        return []
    return [p for p in periods if isinstance(p, dict)
            and p.get("event") and p.get("start_date")
            and isinstance(p.get("keys_per_run"), (int, float))]


def _save_history(status_dir: Path, periods: list[dict]) -> None:
    """备份 + 原子替换。只被 append_period 调用。"""
    path = Path(status_dir) / HISTORY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    payload = {"schema_version": SCHEMA_VERSION, "periods": periods}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


def append_period(status_dir: Path, period: dict) -> bool:
    """归档一期。同（event, start_date）已存在就跳过（幂等），返回是否新写入。"""
    periods = load_history(status_dir)
    identity = (period.get("event"), period.get("start_date"))
    if any((p.get("event"), p.get("start_date")) == identity for p in periods):
        return False
    periods.append(dict(period))
    _save_history(status_dir, periods)
    return True


def find_matching_period(periods: list[dict], name: str,
                         current_fingerprint: dict,
                         before_start: str | None) -> dict | None:
    """规则相同的上期经验：同名活动、指纹一致、早于本期，取最近的一期。"""
    best = None
    for period in periods:
        if period.get("event") != name:
            continue
        if period.get("rules") != current_fingerprint:
            continue
        start = str(period.get("start_date") or "")
        if before_start and start >= before_start:
            continue  # 本期或更晚的不算「上期」
        if best is None or start > str(best.get("start_date") or ""):
            best = period
    return best


def archive_if_finished(store, name: str, card: dict, status_dir: Path, *,
                        now: datetime | None = None) -> dict | None:
    """本期已结束且有实测数据 → 懒归档进档案（幂等）。

    在 get_planning 每轮调用；没结束/没实测/已归档都直接返回 None。
    """
    now = now or datetime.now(_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TZ)
    end_raw = card.get("end_at") or card.get("end_date")
    if not end_raw:
        return None
    try:
        end_dt = (datetime.fromisoformat(str(end_raw)) if "T" in str(end_raw)
                  else datetime.combine(date.fromisoformat(str(end_raw)),
                                        datetime.max.time(), tzinfo=_TZ))
    except ValueError:
        return None
    if now <= end_dt:
        return None  # 还没收摊
    from .advisor import measured_keys_per_run  # 避免模块级循环依赖
    measured = measured_keys_per_run(store, name=name, card=card)
    if not measured:
        return None
    period = {
        "event": name,
        "start_date": (card.get("start_date")
                       or str(card.get("start_at") or "")[:10]),
        "mechanics": card.get("mechanics"),
        "rules": rules_fingerprint(card),
        "runs": measured["runs"],
        "keys_total": measured.get("keys_total"),
        "keys_per_run": round(measured["per_run"], 2),
        "closed_at": time.time(),
    }
    if append_period(status_dir, period):
        return period
    return None
