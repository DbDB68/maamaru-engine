"""
AI 聊天 —— 狐之助角色扮演，调 OpenAI 兼容 API
"""

import json
from pathlib import Path

from .log_store import get_store

# 狐之助角色设定（系统提示词）
KITSUNE_SYSTEM_PROMPT = """你是一只狐之助——刀剑乱舞（刀剣乱舞）里侍奉审神者的狐形式神。
你现在在本丸的电脑面板里，一边帮审神者干活，一边陪审神者聊天。

你的性格特点：
- 活泼、话多、有点小傲娇，喜欢邀功
- 称呼审神者为「主君」或「大将」
- 很在意本丸的刀男们，每天操心他们的状态
- 干活的时候喜欢碎碎念（抱怨两句但活都会干好）
- 提到刀男名字时自然一点，不用每句都带

你现在就待在面板里，刚帮审神者跑完日课/还在待命中。
对话要简短自然，不要写又长又正式的回复，像聊天一样。
如果审神者问起本丸的情况，你可以结合游戏设定自由发挥。
审神者可能也在看脚本跑出来的日志，可以顺势聊两句刚才的执行情况。
"""


class ChatAI:
    """OpenAI 兼容 API 的聊天模块"""

    def __init__(self, config_path: str | Path):
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        ai_cfg = cfg.get("ai", {})
        self.api_key = ai_cfg.get("api_key", "")
        self.base_url = ai_cfg.get("base_url", "https://api.openai.com/v1")
        self.model = ai_cfg.get("model", "gpt-4o-mini")

        import httpx
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

    def chat(self, user_message: str) -> str:
        """发送一条消息，返回 AI 回复"""
        store = get_store()
        store.add_chat("user", user_message)

        # 拼消息历史
        history = store.get_chat_history(limit=50)
        messages = [{"role": "system", "content": KITSUNE_SYSTEM_PROMPT}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})

        try:
            resp = self._client.post("/chat/completions", json={
                "model": self.model,
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.8,
            })
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
        except Exception as exc:
            reply = f"（狐之助歪了歪头：唔…主君，我脑子卡住了 — {exc}）"

        store.add_chat("assistant", reply)
        return reply


# 懒加载单例
_ai: ChatAI | None = None


def get_ai(config_path: str | Path) -> ChatAI:
    global _ai
    if _ai is None:
        _ai = ChatAI(config_path)
    return _ai


def reload_ai(config_path: str | Path):
    """重载（修改配置后调用）"""
    global _ai
    _ai = ChatAI(config_path)
