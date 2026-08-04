"""Friendly WebView launcher for non-technical users."""

import json
import os
import socket
import threading
import time
import traceback
import urllib.request

import webview

from touken.runtime_paths import DATA_ROOT, ensure_runtime_data
from .health import has_blocker, run_checks


HTML = r"""
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}body{margin:0;background:#f4efe5;color:#3c3429;font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;user-select:none}
header{height:96px;background:#d79c08;color:white;padding:18px 30px;box-shadow:0 2px 8px #9b711c44}
h1{margin:0;font-size:28px}header p{margin:4px 0;color:#fff4d2;font-size:13px}
main{padding:22px 26px}.title{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.title b{font-size:18px}.summary{font-size:13px;color:#8b8173}
.card{background:#fffaf1;border:1px solid #dfd5c4;border-radius:13px;padding:10px 18px;min-height:282px;box-shadow:0 3px 12px #78664710}
.row{display:grid;grid-template-columns:20px 112px 1fr;gap:8px;align-items:center;padding:11px 0;border-bottom:1px dashed #e7ddcb}.row:last-child{border:0}
.dot{font-size:16px}.label{font-weight:700}.detail{color:#8b8173;font-size:13px}.ok{color:#4d9c78}.warn{color:#d58a2c}.error{color:#c5534e}.info{color:#6b82a8}
button{font:inherit;cursor:pointer}.start{width:100%;margin-top:16px;height:58px;border:0;border-radius:11px;background:#d79c08;color:white;font-size:18px;font-weight:700;box-shadow:0 4px 10px #b67c1744}.start:hover{background:#bd8604}.start:disabled{background:#bdb4a4;cursor:not-allowed}
.actions{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}.actions button{height:39px;border:1px solid #d9cdb9;border-radius:8px;background:#fffaf1;color:#3c3429}.actions button:hover{background:#f8e9bd}
.note{margin:14px 2px 0;color:#8b8173;font-size:12px}.loading{padding:90px 0;text-align:center;color:#8b8173}
</style></head><body>
<header><h1>🦊 まあ丸</h1><p>本丸近侍启动器 · 不懂电脑也能用版</p></header>
<main><div class="title"><b>启动前检查</b><span id="summary" class="summary">正在检查…</span></div>
<div id="checks" class="card"><div class="loading">正在检查运行环境…</div></div>
<button id="start" class="start" onclick="startApp()" disabled>▶　启动まあ丸</button>
<div class="actions"><button onclick="refresh()">↻ 重新检查</button><button onclick="repair()">🔧 修复环境</button><button onclick="update()">⬆ 检查更新</button><button onclick="openData()">📁 数据目录</button></div>
<p class="note">QQ 协议端是可选功能，第一版请在面板“系统 → QQ”中配置。</p></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function refresh(){
 document.querySelector('#summary').textContent='正在检查…';document.querySelector('#start').disabled=true;
 document.querySelector('#checks').innerHTML='<div class="loading">正在检查运行环境…</div>';
 const data=await pywebview.api.check();
 document.querySelector('#checks').innerHTML=data.items.map(x=>`<div class="row"><span class="dot ${x.state}">●</span><span class="label">${esc(x.label)}</span><span class="detail">${esc(x.detail)}</span></div>`).join('');
 const summary=document.querySelector('#summary');summary.textContent=data.blocked?'需要修复':'可以启动';summary.className='summary '+(data.blocked?'error':'ok');document.querySelector('#start').disabled=data.blocked;
}
async function startApp(){const b=document.querySelector('#start');b.disabled=true;b.textContent='正在启动…';const r=await pywebview.api.start();if(!r.ok){alert('启动失败：'+r.message);b.disabled=false;b.textContent='▶　启动まあ丸';}else{b.textContent='✓ 已启动';document.querySelector('#summary').textContent='面板已打开';}}
async function repair(){const r=await pywebview.api.repair();alert(r.message);refresh()}
async function update(){document.querySelector('#summary').textContent='正在检查 GitHub…';const r=await pywebview.api.check_update();alert(r.message);refresh()}
async function openData(){await pywebview.api.open_data()}
window.addEventListener('pywebviewready',refresh);
</script></body></html>
"""


class Api:
    def check(self):
        ensure_runtime_data()
        checks = run_checks()
        return {"blocked": has_blocker(checks), "items": [item.__dict__ for item in checks]}

    def start(self):
        try:
            if not _port_alive():
                from maamaru_app import _run_server
                error = {"traceback": ""}

                def run_server():
                    try:
                        _run_server()
                    except BaseException:
                        error["traceback"] = traceback.format_exc()
                        _write_launcher_log(error["traceback"])

                threading.Thread(target=run_server, daemon=True).start()
                deadline = time.time() + 15
                while time.time() < deadline and not _port_alive() and not error["traceback"]:
                    time.sleep(0.2)
            if not _port_alive():
                detail = error["traceback"].strip().splitlines()[-1] if error["traceback"] else "启动等待超时"
                return {"ok": False, "message": f"面板服务没有成功启动：{detail}\n错误记录：{DATA_ROOT / 'launcher.log'}"}

            # pywebview 的 JS 正在等待本次 API 调用返回；此时同步换页会互相等待。
            # 稍后从独立线程切换，先让“启动”调用顺利结束。
            def open_panel():
                time.sleep(0.15)
                window = webview.windows[0]
                # 启动检查适合小窗，概览面板则按宽屏三栏设计；进入面板时
                # 使用当前屏幕的可用空间，避免任务卡、日志和统计挤成一列。
                window.maximize()
                window.load_url("http://127.0.0.1:8080")

            threading.Thread(target=open_panel, daemon=True).start()
            return {"ok": True, "message": "まあ丸已启动"}
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": str(exc)}

    def repair(self):
        try:
            ensure_runtime_data()
            return {"ok": True, "message": "已补齐数据目录并重新检查核心文件。\n联网重装将在下一版加入。"}
        except Exception as exc:
            return {"ok": False, "message": f"修复失败：{exc}"}

    def check_update(self):
        try:
            request = urllib.request.Request(
                "https://api.github.com/repos/DbDB68/maamaru-engine/releases/latest",
                headers={"User-Agent": "MaamaruLauncher/0.1"})
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.load(response)
            tag = data.get("tag_name") or "未知版本"
            return {"ok": True, "message": f"GitHub 最新版本：{tag}\n\n第一版只检查，不会自动覆盖当前程序。"}
        except Exception:
            return {"ok": False, "message": "暂时连不上 GitHub，稍后再试。"}

    def open_data(self):
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        os.startfile(DATA_ROOT)
        return {"ok": True}


def main():
    ensure_runtime_data()
    webview.create_window("まあ丸启动器", html=HTML, js_api=Api(), width=700, height=660,
                          min_size=(620, 590), resizable=True)
    webview.start(debug=False)


def _port_alive() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=0.5):
            return True
    except OSError:
        return False


def _write_launcher_log(content: str) -> None:
    try:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        (DATA_ROOT / "launcher.log").write_text(content, encoding="utf-8")
    except OSError:
        pass
