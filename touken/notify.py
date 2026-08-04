# -*- coding: utf-8 -*-
"""
ntfy.sh 手机推送——日课跑完把成绩单推到手机上

为什么用 ntfy：不用注册账号、不用接微信/QQ（没风控），手机装个 App
订阅同名频道就能收。topic 名即密码，别泄露。

header 只能塞 ASCII（Python http.client 按 latin-1 编码，中文会炸），
所以标题用英文，正文随便中文。表情走 tags 字段。
"""

import json
import urllib.request
from pathlib import Path

from .runtime_paths import CONFIG_PATH

_CONFIG_PATH = CONFIG_PATH


def _load_notify_conf() -> dict:
    try:
        conf = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return conf.get("notify", {})
    except Exception:
        return {}


def notify(message: str, title: str = "Touken Daily", tags: str = "tada",
           priority: str = "default") -> bool:
    """
    发一条 ntfy 推送。失败静默返回 False（推送挂了不许拖累日课）。

    Args:
        message: 正文（中文随便写）
        title:   标题（必须 ASCII）
        tags:    ntfy 表情标签，如 tada / warning / sword（逗号分隔）
        priority: min/low/default/high/urgent
    """
    conf = _load_notify_conf()
    if not conf.get("enabled"):
        return False
    server = conf.get("server", "https://ntfy.sh").rstrip("/")
    topic = conf.get("topic", "")
    if not topic:
        return False
    try:
        req = urllib.request.Request(
            f"{server}/{topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Tags": tags,
                "Priority": priority,
                "Content-Type": "text/plain; charset=utf-8",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def notify_daily_report(payload: dict) -> bool:
    """
    把日课成绩单（latest_report.json 的内容）排版成推送发出去。

    Args:
        payload: {"finished_at": ..., "all_green": bool, "steps": [{name,status}]}
    """
    all_green = payload.get("all_green", False)
    fails = [s["name"] for s in payload.get("steps", [])
             if not str(s.get("status", "")).startswith("✓")]
    lines = [f"跑完时间：{payload.get('finished_at', '?')}"]
    if all_green:
        lines.append("全部步骤 ✓，本丸今天也是模范员工。")
    else:
        lines.append(f"翻车 {len(fails)} 项：{'、'.join(fails)}")
        lines.append("")
        for s in payload.get("steps", []):
            lines.append(f"  {s['name']}: {s['status']}")
    return notify(
        "\n".join(lines),
        title="Touken Daily Report",
        tags="tada" if all_green else "warning",
        priority="default" if all_green else "high",
    )
