# -*- coding: utf-8 -*-
"""
まあ丸 客户端 —— pywebview 套壳面板

原理：后台线程起 FastAPI 面板服务，原生窗口（Edge WebView2）打开它。
就是「换个地方看网页」，但有图标有标题栏，没有浏览器边框。
关掉窗口 = 程序退出（服务是守护线程，跟着一起死）。
"""

import socket
import sys
import threading
import time
from pathlib import Path

# 保证能 import panel 包（PyInstaller 打包后 cwd 可能不在项目根）
sys.path.insert(0, str(Path(__file__).resolve().parent))

HOST = "127.0.0.1"
PORT = 8080
URL = f"http://{HOST}:{PORT}"


def _log(*args):
    """pythonw / 打包后可能没有控制台，print 翻车不许影响启动"""
    try:
        print(*args)
    except Exception:
        pass


def _port_alive(host: str, port: int) -> bool:
    """端口上是不是已经有面板在跑了"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _run_server():
    import uvicorn
    from panel.server import app
    # 单机启动器只服务自己的原生窗口。绑定本机地址可以避开防火墙、
    # 公共网络策略以及部分新装 Windows 对全网监听的限制。
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main():
    if _port_alive(HOST, PORT):
        # 已经有面板在跑（比如开了终端版），直接开窗看现成的
        _log("[まあ丸] 检测到面板已在运行，直接开窗")
    else:
        t = threading.Thread(target=_run_server, daemon=True)
        t.start()
        # 等服务把端口监听上，最多等 10 秒
        for _ in range(100):
            if _port_alive(HOST, PORT):
                break
            time.sleep(0.1)
        else:
            _log("[まあ丸] 面板服务起不来，看看 8080 端口是不是被占了")
            return

    import webview
    webview.create_window(
        "まあ丸 — 本丸近侍面板",
        URL,
        width=1100,
        height=800,
        min_size=(420, 600),
        text_select=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
