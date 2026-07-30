# -*- coding: utf-8 -*-
"""
QQ 协议端 —— SnowLuma / NapCat（OneBot v11）HTTP 模式

收消息：OneBot 的 HTTP POST 上报 → 面板的 /onebot/webhook（init_qq 挂到 FastAPI 上）
发消息：OneBot HTTP API /send_private_msg（私聊回复 + 事件播报）

SnowLuma / NapCat 那边要配两条（以面板跑在 8080 为例）：
  HTTP 上报地址：http://127.0.0.1:8080/onebot/webhook
  HTTP API 监听：http://127.0.0.1:5500（本机默认）

设计要点：
- webhook 必须秒回（OneBot 超时会重推），LLM 慢，所以收到消息立刻 200，
  Agent 处理丢后台线程，回话走 send_private_msg 主动发。
- message_id 去重小本本，防止协议端重推导致一句话回两遍。
- 只接私聊（message_type=private）；群消息直接无视，省得被围观群众玩坏。

配置（panel_config.json）：
  "bot": {
    "qq": {
      "enabled": true,
      "snowluma_http": "http://127.0.0.1:5500",
      "admin_qq": [123456789]        // 白名单 + 播报对象；空数组 = 谁都能聊但播报没人收
    }
  }

顺带：maibot（NoneBot）用户也可以在插件里 POST /api/agent，那个入口一直开着。
"""

import json
import threading
from collections import deque
from pathlib import Path

import httpx
from fastapi import FastAPI, Request

_HERE = Path(__file__).resolve().parent
_PANEL_CONFIG = _HERE / "panel_config.json"


def _qq_cfg() -> dict:
    try:
        d = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8"))
        return d.get("bot", {}).get("qq", {})
    except Exception:
        return {}


class QQSender:
    """OneBot HTTP API 发送端（回复 + 主动播报都用它）"""

    def __init__(self, base_url: str):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=10)

    def send_private(self, user_id: int, text: str) -> bool:
        try:
            r = self._client.post("/send_private_msg", json={
                "user_id": int(user_id),
                "message": text,
            })
            ok = r.status_code == 200
            if ok:
                print(f"[QQ] → {user_id}: {text[:40]}", flush=True)
            else:
                print(f"[QQ] 发送失败（{user_id}）: HTTP {r.status_code}", flush=True)
            return ok
        except Exception as exc:
            print(f"[QQ] 发送异常（{user_id}）: {exc}", flush=True)
            return False

    def alive(self) -> bool:
        try:
            return self._client.get("/get_status", timeout=5).status_code == 200
        except Exception:
            return False


def _plain_text(event: dict) -> str:
    """从 OneBot 消息事件里抠纯文本（兼容 string 和 segment 数组两种格式）"""
    raw = event.get("raw_message")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    msg = event.get("message")
    if isinstance(msg, str):
        return msg.strip()
    if isinstance(msg, list):
        parts = [seg.get("data", {}).get("text", "")
                 for seg in msg if isinstance(seg, dict) and seg.get("type") == "text"]
        return "".join(parts).strip()
    return ""


def init_qq(app: FastAPI, get_agent) -> QQSender | None:
    """
    把 /onebot/webhook 挂到 FastAPI app 上。

    Args:
        app:       面板的 FastAPI 实例
        get_agent: 无参 callable，返回 AgentGateway（延迟拿，配置热重载后能用新的）

    Returns:
        QQSender（给播报器当出口）；bot.qq.enabled 没开就返回 None
    """
    cfg = _qq_cfg()
    if not cfg.get("enabled"):
        print("[QQ] bot.qq.enabled 未开，跳过（panel_config.json）", flush=True)
        return None

    sender = QQSender(cfg.get("snowluma_http", "http://127.0.0.1:5500"))
    admins = {int(q) for q in cfg.get("admin_qq", [])}
    if not admins:
        print("[QQ] ⚠️ admin_qq 是空的：谁都能聊，但事件播报没人收", flush=True)

    if sender.alive():
        print("[QQ] 🚀 OneBot 协议端已连接，webhook 挂在 /onebot/webhook", flush=True)
    else:
        print("[QQ] ⚠️ 协议端暂时连不上（SnowLuma 没跑？），webhook 照样挂，后面来了就能收", flush=True)

    seen_ids = deque(maxlen=200)   # 消息去重小本本

    @app.post("/onebot/webhook")
    async def onebot_webhook(request: Request):
        try:
            event = await request.json()
        except Exception:
            return {"status": "ignored"}

        # 只要私聊消息；心跳/生命周期/群消息一律无视
        if event.get("post_type") != "message" or event.get("message_type") != "private":
            return {"status": "ignored"}

        msg_id = event.get("message_id")
        if msg_id is not None and msg_id in seen_ids:
            return {"status": "dup"}
        if msg_id is not None:
            seen_ids.append(msg_id)

        user_id = event.get("user_id")
        if not user_id or user_id == event.get("self_id"):
            return {"status": "ignored"}

        text = _plain_text(event)
        if not text:
            return {"status": "ignored"}

        print(f"[QQ] ← {user_id}: {text[:40]}", flush=True)

        # 白名单：配了 admin_qq 就只认自己人
        if admins and int(user_id) not in admins:
            sender.send_private(user_id, "（狐之助歪了歪头：唔…我不认识你呀）")
            return {"status": "ok"}

        # LLM 慢，丢后台线程慢慢想；webhook 先秒回，协议端别等
        def _reply():
            try:
                reply = get_agent().process(text, channel="qq")
            except Exception as exc:
                reply = f"（狐之助耳朵耷拉下来：脑子冒烟了 — {exc}）"
            sender.send_private(user_id, reply)

        threading.Thread(target=_reply, daemon=True).start()
        return {"status": "ok"}

    return sender


# ── 独立测试：python -m panel.bot_qq（起个迷你 FastAPI 只挂 webhook）──

if __name__ == "__main__":
    import uvicorn
    from .agent import AgentGateway

    _app = FastAPI(title="まあ丸 QQ 协议端（独立测试）")
    _gw = AgentGateway(str(_PANEL_CONFIG))
    init_qq(_app, lambda: _gw)
    uvicorn.run(_app, host="127.0.0.1", port=8081)
