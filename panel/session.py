"""
会话状态管理器 —— 跨渠道的短期记忆 + 当前任务追踪

存在 status/session_state.json，格式：
{
  "current_task": "远征_第二部队_进行中",
  "user_mood_hint": null,
  "last_error": null,
  "pending_choice": null,
  "short_term_memory": [
    {"role": "user", "content": "...", "channel": "web", "time": "23:15"},
    {"role": "assistant", "content": "...", "channel": "web", "time": "23:15"}
  ]
}
"""

import json
import time
from pathlib import Path

_SESSION_PATH = Path(__file__).resolve().parent.parent / "status" / "session_state.json"
_MAX_MEMORY = 12  # 记住最近 12 轮对话（多了 token 烧钱）


def _default() -> dict:
    return {
        "current_task": None,
        "user_mood_hint": None,
        "last_error": None,
        "pending_choice": None,
        "short_term_memory": [],
    }


def load() -> dict:
    try:
        if _SESSION_PATH.exists():
            d = json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
            # 保证字段完整（手工改 JSON 可能漏）
            defaults = _default()
            defaults.update(d)
            return defaults
    except Exception:
        pass
    return _default()


def save(data: dict):
    _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SESSION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def push_memory(role: str, content: str, channel: str):
    """追加一条对话记忆，超上限自动剪裁"""
    s = load()
    s["short_term_memory"].append({
        "role": role,
        "content": content,
        "channel": channel,
        "time": time.strftime("%H:%M"),
    })
    # 只保留最近 N 条
    if len(s["short_term_memory"]) > _MAX_MEMORY:
        s["short_term_memory"] = s["short_term_memory"][-_MAX_MEMORY:]
    s["last_interaction"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save(s)


def build_context() -> str:
    """拼进 system prompt 的上下文摘要"""
    s = load()
    parts = []
    if s.get("current_task"):
        parts.append(f"当前任务：{s['current_task']}")
    if s.get("user_mood_hint"):
        parts.append(f"用户情绪：{s['user_mood_hint']}")
    if s.get("last_error"):
        parts.append(f"上次错误：{s['last_error']}")
    if s.get("pending_choice"):
        parts.append(f"待用户决定：{s['pending_choice']}")
    mem = s.get("short_term_memory", [])
    if mem:
        entries = []
        for m in mem[-6:]:  # 最近 6 条足够理解当前
            ch = {"web": "面板", "qq": "QQ", "telegram": "Telegram"}.get(m["channel"], m["channel"])
            entries.append(f"  [{ch} {m['time']}] {m['role']}: {m['content']}")
        parts.append("最近对话：\n" + "\n".join(entries))
    return "\n".join(parts) if parts else "暂无上下文"
