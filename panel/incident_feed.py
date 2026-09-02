# -*- coding: utf-8 -*-
"""
异常与通知中心 · 消息检测器

和 broadcaster 一样挂在 server._on_script_message 上，但职责不同：
broadcaster 负责「开口说话」，这里负责「立案归档」——把值得追踪的异常
写成统一格式的事故单（发生了什么 / 可能原因 / 现在该做什么 /
是否必须人工接管 / 对应任务入口 / 去重编号），供面板通知中心展示。

这一期只立案，不改任何 QQ/ntfy 播报行为；收敛通知轰炸是下一步的事。
"""

from __future__ import annotations

import json

from touken.incidents import report_incident, resolve_incidents
from touken.runtime_paths import STATE_DIR


def _script_label(script: str) -> str:
    try:
        from .script_runner import list_scripts
        return list_scripts().get(script, {}).get("label", script or "脚本")
    except Exception:
        return script or "脚本"


def feed(payload: dict) -> None:
    """消息管道喂进来的每一条。检测挂了不许拖累日志管道。"""
    try:
        _feed(payload)
    except Exception:
        pass


def _feed(payload: dict) -> None:
    script = str(payload.get("script") or "")
    msg = str(payload.get("message") or "")
    run_id = payload.get("run_id")
    if not run_id or script == "scheduler":
        return

    if "脚本崩溃" in msg:
        label = _script_label(script)
        report_incident(
            f"crash:{script}",
            severity="urgent",
            title=f"{label}半路崩溃",
            cause="可能是画面识别卡住、模拟器抖了一下，也可能是脚本本身有 bug",
            action="去「本丸」页翻成绩单和日志最后几行；重启任务再观察，复发就找懂行的人看诊断包",
            needs_human=True,
            entry={"tab": "report"},
        )
        return

    if msg.startswith("[看门狗]"):
        label = _script_label(script)
        report_incident(
            f"watchdog:{script}",
            severity="urgent",
            title=f"{label}卡死被看门狗强杀",
            cause="工人进程长时间一行输出都没有，多半是 ADB 或模拟器卡住了",
            action="重启模拟器再跑；反复卡死就导出诊断包找人看",
            needs_human=True,
            entry={"tab": "report"},
        )
        return

    if msg.startswith("[脚本] 完成") and script == "daily":
        _check_daily_report()


def _check_daily_report() -> None:
    """日课收工读落盘成绩单：有翻车项立案（不必须人工），全绿则销案。"""
    try:
        report = json.loads((STATE_DIR / "latest_report.json").read_text(encoding="utf-8"))
    except Exception:
        return
    fails = []
    for step in report.get("steps", []):
        status = str(step.get("status", ""))
        if status.startswith("✓"):
            continue
        detail = status.lstrip("✗⚠ ")
        fails.append(f"{step.get('name', '?')}（{detail}）" if detail else str(step.get("name", "?")))
    if not fails:
        resolve_incidents("daily-fail")
        return
    report_incident(
        "daily-fail",
        severity="warning",
        title=f"一键日课有 {len(fails)} 项没跑好",
        cause="、".join(fails[:3]),
        action="去「本丸」页看成绩单里标 ✗ 的项；偶发可以不管，天天翻同一项就得查配置了",
        needs_human=False,
        entry={"tab": "report"},
    )
