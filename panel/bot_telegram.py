"""
Telegram Bot —— 接收 TG 消息 → Agent 网关 → 狐之助回复

依赖：pip install python-telegram-bot
"""

import asyncio
import json
import threading
from pathlib import Path

from touken.runtime_paths import PANEL_CONFIG_PATH

from .agent import AgentGateway

_HERE = Path(__file__).resolve().parent
_PANEL_CONFIG = PANEL_CONFIG_PATH


def _read_config() -> dict:
    """读 panel_config.json，兼容老的扁平结构（bot.token）和新嵌套结构（bot.telegram.token）"""
    try:
        d = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8"))
        bot = d.get("bot", {})
        # 兼容：旧的 token/allowed_users 在 bot 顶层，新的挪到 bot.telegram
        if "token" in bot and "telegram" not in bot:
            bot["telegram"] = {"token": bot.pop("token", ""),
                               "allowed_users": bot.pop("allowed_users", [])}
        return bot
    except Exception:
        return {}


class TelegramBot:
    """Telegram Bot 实例，长轮询模式"""

    def __init__(self, agent_gateway: AgentGateway):
        self._agent = agent_gateway
        self._app = None
        self._thread = None
        self._running = False

    def start(self):
        cfg = _read_config()
        tg = cfg.get("telegram", {})
        token = tg.get("token", "")
        allowed = tg.get("allowed_users", [])

        if not token:
            print("[TG Bot] 没配 token，不启动")
            return

        try:
            from telegram import Update
            from telegram.ext import Application, MessageHandler, filters
        except ImportError:
            print("[TG Bot] python-telegram-bot 没装，pip install 一下")
            return

        # 构建 Application
        app = Application.builder().token(token).build()
        allowed_set = set(allowed)

        async def handle_message(update: Update, _ctx):
            if not update.message or not update.message.text:
                return
            user_id = update.effective_user.id if update.effective_user else None
            user_name = update.effective_user.full_name if update.effective_user else "未知"

            # 用户白名单检查
            if allowed_set and user_id not in allowed_set:
                await update.message.reply_text("（狐之助歪了歪头：唔…我不认识你呀）")
                return

            # 显示"正在输入"
            async def send_typing():
                while True:
                    try:
                        await update.message.chat.send_action("typing")
                        await asyncio.sleep(3)
                    except Exception:
                        break
            typing_task = asyncio.create_task(send_typing())

            try:
                # 走 Agent 网关
                reply = self._agent.process(
                    update.message.text,
                    channel="telegram",
                )
            except Exception as exc:
                reply = f"（狐之助耳朵耷拉下来：脑子冒烟了 — {exc}）"

            typing_task.cancel()
            await update.message.reply_text(reply)

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        self._app = app

        # 后台线程跑 bot
        def _run():
            try:
                print(f"[TG Bot] 🚀 启动，已授权用户: {list(allowed_set) if allowed_set else '所有人'}")
                app.run_polling(drop_pending_updates=True)
            except Exception as exc:
                print(f"[TG Bot] 💀 挂了: {exc}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        self._running = True

    def stop(self):
        if self._app and self._running:
            try:
                self._app.stop()
                self._running = False
                print("[TG Bot] 已停止")
            except Exception as exc:
                print(f"[TG Bot] 停止异常: {exc}")


def start_bot(agent_gateway: AgentGateway):
    """便捷入口：启动 bot（先检查配置再决定启不启）"""
    cfg = _read_config()
    platform = cfg.get("platform", "").lower()
    enabled = cfg.get("enabled", False)

    if not enabled:
        print(f"[Bot] 未启用（panel_config.json → bot.enabled = false），跳过")
        return None

    # 平台为 telegram 时启 TG bot；为 qq 时 QQ webhook 已在 server.startup 里挂好
    if platform == "telegram":
        bot = TelegramBot(agent_gateway)
        bot.start()
        return bot
    elif platform == "qq":
        # QQ 用 HTTP webhook，配置改了需要重启面板才能重挂载（webhook 路由不能动态卸）
        print(f"[Bot] QQ 模式：webhook 在 server.startup 挂载，改了 panel_config.json 需重启面板")
        return None
    else:
        print(f"[Bot] 不支持的平台: {platform}")
        return None


def stop_bot(bot_instance):
    """停止 bot"""
    if bot_instance:
        bot_instance.stop()
