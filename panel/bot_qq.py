"""
QQ Bot —— 通过 SnowLuma (OneBot API) 收消息 → Agent 网关 → 回复

两种用法：
  1. NoneBot 插件：直接把本文件丢进 maibot 的 plugins/ 目录
  2. 独立运行：python -m panel.bot_qq（依赖 SnowLuma HTTP API）
"""

import asyncio
import json
import threading
import time
from pathlib import Path

import httpx

from .agent import AgentGateway

_HERE = Path(__file__).resolve().parent
_PANEL_CONFIG = _HERE / "panel_config.json"

BOT_CONFIG = {
    "snowluma_http": "http://127.0.0.1:5500",       # SnowLuma HTTP API（本地跑，默认 5500）
    "admin_qq": [],                                   # 管理员 QQ 号（空=谁都能用）
    "agent_url": "http://127.0.0.1:8080/api/agent",  # 面板 Agent 网关（本地）
    "poll_interval": 1.5,                             # 轮询间隔（秒）
}


def _read_config() -> dict:
    """从 panel_config.json 读覆盖设置"""
    try:
        d = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8"))
        return d.get("bot", {}).get("qq", {})
    except Exception:
        return {}


class QQBot:
    """SnowLuma OneBot 适配 Bot"""

    def __init__(self, agent: AgentGateway, config: dict = None):
        # 默认配置 + panel_config.json 覆盖 + 手动传参覆盖
        overrides = {**_read_config(), **(config or {})}
        self._cfg = {**BOT_CONFIG, **overrides}
        self._running = False
        self._thread = None
        self._last_msg_id = 0
        self._client = httpx.Client(base_url=self._cfg["snowluma_http"], timeout=10)
        self._admins = set(self._cfg.get("admin_qq", []))

    def start(self):
        # 测试连接
        try:
            r = self._client.get("/get_status", timeout=5)
            if r.status_code != 200:
                print(f"[QQ Bot] ⚠️ SnowLuma 连接测试失败（{r.status_code}），试试启动")
        except Exception:
            print(f"[QQ Bot] ⚠️ SnowLuma 连不上（{self._cfg['snowluma_http']}），确认地址对不对")

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f"[QQ Bot] 🚀 启动，轮询 {self._cfg['snowluma_http']}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        print("[QQ Bot] 已停止")

    def _poll_loop(self):
        while self._running:
            try:
                self._poll_once()
            except Exception as exc:
                print(f"[QQ Bot] 轮询异常: {exc}")
            time.sleep(self._cfg["poll_interval"])

    def _poll_once(self):
        """拉一条消息 -> 走 Agent -> 回复"""
        r = self._client.get("/get_messages", params={"limit": 1}, timeout=5)
        if r.status_code != 200:
            return
        data = r.json()
        msgs = data.get("data", data.get("messages", [])) if isinstance(data, dict) else []
        if not msgs:
            return

        msg = msgs[0]
        msg_id = msg.get("message_id", 0)
        if msg_id <= self._last_msg_id:
            return
        self._last_msg_id = msg_id

        # 只处理文本消息
        text = msg.get("message", "")
        if not text:
            return

        user_id = msg.get("user_id", 0)

        # 管理员白名单
        if self._admins and user_id not in self._admins:
            self._send_reply(user_id, "(狐之助歪了歪头：唔…我不认识你呀)")
            return

        print(f"[QQ Bot] ← {user_id}: {text[:50]}")

        # 走 Agent
        try:
            reply = self._agent.process(text, channel="qq")
        except Exception as exc:
            reply = f"(狐之助耳朵耷拉下来：脑子冒烟了 — {exc})"

        self._send_reply(user_id, reply)

    def _send_reply(self, user_id: int, text: str):
        """通过 SnowLuma API 发私聊"""
        try:
            self._client.post("/send_private_msg", json={
                "user_id": user_id,
                "message": text,
            }, timeout=5)
            print(f"[QQ Bot] → {user_id}: {text[:50]}")
        except Exception as exc:
            print(f"[QQ Bot] 发送失败: {exc}")


# ── NoneBot 插件模式 ──
# 如果你的 maibot 用 NoneBot，在 bot.py 里加这几行：

"""
from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
import httpx

maamaru = on_message()

@maamaru.handle()
async def _(event: MessageEvent):
    if not event.get_plaintext():
        return
    text = event.get_plaintext().strip()
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                "http://127.0.0.1:8080/api/agent",
                json={"message": text, "channel": "qq"},
                timeout=30,
            )
            reply = resp.json().get("reply", "")
        except Exception:
            reply = "(狐之助信号不好，主君稍等)"
    await maamaru.finish(reply)
"""

# ── 独立启动 ──

def start_bot(agent_gateway: AgentGateway, config: dict = None):
    bot = QQBot(agent_gateway, config)
    bot.start()
    return bot


if __name__ == "__main__":
    # 独立运行测试：python -m panel.bot_qq
    print("🦊 QQ Bot 独立模式（测试用）")
    agent = AgentGateway(str(_PANEL_CONFIG))
    bot = start_bot(agent)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bot.stop()
        print("已停止")
