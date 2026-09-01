# -*- coding: utf-8 -*-
"""
まあ丸账房 —— 独立桌面窗口启动器

后台线程起 FastAPI 账房服务，pywebview 开本地窗口。
"""

import socket
import sys
import threading
import time
from pathlib import Path

# 保证能 import ledger_app 包（PyInstaller 打包后 cwd 可能不在项目根）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HOST = "127.0.0.1"
PREFERRED_PORT = 18083


def _log(*args):
    """pythonw / 打包后可能没有控制台，print 翻车不许影响启动"""
    try:
        print(*args)
    except Exception:
        pass


def _port_alive(host: str, port: int) -> bool:
    """端口上是不是已经有账房服务在跑了"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _available_port(preferred: int) -> int:
    for candidate in (preferred, 0):
        if candidate and _port_alive(HOST, candidate):
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind((HOST, candidate))
                probe.listen(1)
                port = int(probe.getsockname()[1])
        except OSError:
            continue
        if port:
            return port
    raise OSError("找不到可用的本机端口")


def _run_server(port: int):
    import uvicorn
    from ledger_app.server import app
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def main():
    port = _available_port(PREFERRED_PORT)
    url = f"http://{HOST}:{port}"
    if _port_alive(HOST, port):
        _log("[まあ丸账房] 检测到服务已在运行，直接开窗")
    else:
        t = threading.Thread(
            target=_run_server,
            kwargs={"port": port},
            daemon=True,
        )
        t.start()
        # 等服务把端口监听上，最多等 10 秒
        for _ in range(100):
            if _port_alive(HOST, port):
                break
            time.sleep(0.1)
        else:
            _log("[まあ丸账房] 服务起不来，看看 18083 端口是不是被占了")
            return

    import webview
    webview.create_window(
        "まあ丸账房",
        url,
        width=1100,
        height=800,
        min_size=(420, 600),
        text_select=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
