"""
脚本执行器 —— 在后台线程跑 stream generator，消息同时三路走：
  1. 持久化到 SQLite
  2. 推 SSE 广播队列
  3. 打印 stdout（终端也能看）

支持中途停止（调 stop() 设置标志位，generator 的下一次 iteration 会捕获）。
"""

import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Generator

from .log_store import get_store


# —— 可注册的脚本清单 ——
# 每个条目：(名字, 显示名, 描述, 调用函数, 参数表单schema)
# 调用函数签名：(config_path, params: dict) -> Generator[str, None, None]
# 参数表单schema：字段列表，前端照着渲染：
#   {"key":"team_no","type":"select","label":"部队","options":[["1","部队一"],...],"default":"3"}
#   {"key":"rounds","type":"number","label":"圈数","default":3,"min":1,"max":99}
#   {"key":"steps","type":"checks","label":"要干的活","options":["签到",...],"default":[...]}

_SCRIPTS: dict[str, dict] = {}


def register_script(name: str, label: str, desc: str,
                    runner_fn: Callable[[str, dict], Generator[str, None, None]],
                    params: list | None = None):
    _SCRIPTS[name] = {"label": label, "desc": desc, "fn": runner_fn,
                      "params": params or []}


def list_scripts() -> dict:
    return {k: {"label": v["label"], "desc": v["desc"], "params": v["params"]}
            for k, v in _SCRIPTS.items()}


# —— 运行时状态 ——

class ScriptRunner:
    """在后台线程跑一个 stream generator"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._current_run_id: str | None = None
        self._current_script: str | None = None
        self._lock = threading.Lock()
        self._on_message = None  # callback(message_dict)

    # noinspection PyAttributeOutsideInit
    def set_message_callback(self, cb):
        self._on_message = cb

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_script(self) -> str | None:
        return self._current_script

    def start(self, script_name: str, config_path: str, params: dict | None = None) -> str | None:
        """启动脚本。返回 run_id 或 None（不支持/已在跑）"""
        if self.is_running:
            return None
        if script_name not in _SCRIPTS:
            return None

        run_id = uuid.uuid4().hex[:12]
        self._current_run_id = run_id
        self._current_script = script_name
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run,
            args=(script_name, config_path, run_id, params or {}),
            daemon=True,
        )
        self._thread.start()
        return run_id

    def stop(self):
        """请求停止（设置标志位，下次 yield 时捕获）"""
        self._stop_event.set()

    def _run(self, script_name: str, config_path: str, run_id: str, params: dict):
        info = _SCRIPTS.get(script_name)
        if not info:
            return
        try:
            gen = info["fn"](config_path, params)
            self._stream(gen, run_id, script_name)
        except Exception as exc:
            msg = f"[面板] 脚本崩溃: {exc}"
            self._emit(run_id, script_name, msg)
            print(msg, file=sys.stderr)

    def _stream(self, gen: Generator, run_id: str, script_name: str):
        store = get_store()
        for msg in gen:
            if self._stop_event.is_set():
                final = f"[脚本] 用户请求停止 — run {run_id}"
                store.append(run_id, script_name, final)
                self._emit(run_id, script_name, final)
                print(final)
                break
            store.append(run_id, script_name, msg)
            self._emit(run_id, script_name, msg)
            print(msg, flush=True)

        # generator 自然结束
        final = f"[脚本] 完成 — run {run_id}"
        store.append(run_id, script_name, final)
        self._emit(run_id, script_name, final)
        print(final)

    def _emit(self, run_id: str, script: str, message: str):
        payload = {
            "id": None,  # 由 log_store 分配
            "ts": time.time(),
            "run_id": run_id,
            "script": script,
            "message": message,
        }
        if self._on_message:
            self._on_message(payload)


# 全局单例
_runner: ScriptRunner | None = None
_runner_lock = threading.Lock()


def get_runner() -> ScriptRunner:
    global _runner
    if _runner is None:
        with _runner_lock:
            if _runner is None:
                _runner = ScriptRunner()
    return _runner
