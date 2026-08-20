"""Friendly WebView launcher for non-technical users."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

import webview

from touken.runtime_paths import DATA_ROOT, LOG_DIR, UPDATES_DIR, ensure_runtime_data
from .health import has_blocker, run_checks
from .update_apply import consume_result, prepare_apply
from .updater import UpdateError, download_installer, select_installer
from .version import CURRENT_VERSION


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
<header><h1>🦊 まあ丸</h1><p>本丸近侍启动器 · 不懂电脑也能用版 · v__VERSION__</p></header>
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
 if(data.update_result){alert(data.update_result.ok?data.update_result.message:(data.update_result.message+(data.update_result.rolled_back?'\n旧版程序已经恢复。':'')))}
 document.querySelector('#checks').innerHTML=data.items.map(x=>`<div class="row"><span class="dot ${x.state}">●</span><span class="label">${esc(x.label)}</span><span class="detail">${esc(x.detail)}</span></div>`).join('');
 const summary=document.querySelector('#summary');summary.textContent=data.blocked?'需要修复':'可以启动';summary.className='summary '+(data.blocked?'error':'ok');document.querySelector('#start').disabled=data.blocked;
}
async function startApp(){const b=document.querySelector('#start');b.disabled=true;b.textContent='正在启动…';const r=await pywebview.api.start();if(!r.ok){alert('启动失败：'+r.message);b.disabled=false;b.textContent='▶　启动まあ丸';}else{b.textContent='✓ 已启动';document.querySelector('#summary').textContent='面板已打开';}}
async function repair(){
 const summary=document.querySelector('#summary');summary.textContent='正在修复…';summary.className='summary info';
 const r=await pywebview.api.repair();alert(r.message);await refresh();
}
async function update(){
 const summary=document.querySelector('#summary');summary.textContent='正在检查 GitHub…';summary.className='summary info';
 const r=await pywebview.api.check_update();
 if(r.update_available&&r.download_ready){
  if(confirm(r.message+'\n\n要现在安全下载到更新暂存区吗？')){
   summary.textContent='正在下载并校验安装包…';
   const d=await pywebview.api.download_update();alert(d.message);
   if(d.ok&&confirm('安装包已经校验完成。\n\n要关闭まあ丸并打开安装向导吗？')){
    const a=await pywebview.api.apply_update();if(!a.ok)alert(a.message);
   }
  }
 }else if(r.update_available&&r.url){if(confirm(r.message+'\n\n暂时无法自动下载，要打开发布页面吗？'))await pywebview.api.open_url(r.url)}else{alert(r.message)}
 await refresh();
}
async function openData(){await pywebview.api.open_data()}
window.addEventListener('pywebviewready',refresh);
</script></body></html>
"""


class Api:
    def __init__(self):
        self._pending_update = None

    def check(self):
        ensure_runtime_data()
        checks = run_checks()
        return {
            "blocked": has_blocker(checks),
            "items": [item.__dict__ for item in checks],
            "update_result": consume_result(),
        }

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
                return {"ok": False, "message": f"面板服务没有成功启动：{detail}\n错误记录：{LOG_DIR / 'launcher.log'}"}

            # pywebview 的 JS 正在等待本次 API 调用返回；此时同步换页会互相等待。
            # 稍后从独立线程切换，先让“启动”调用顺利结束。
            def open_panel():
                time.sleep(0.15)
                window = webview.windows[0]
                window.load_url("http://127.0.0.1:8080")

            threading.Thread(target=open_panel, daemon=True).start()
            return {"ok": True, "message": "まあ丸已启动"}
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": str(exc)}

    def repair(self):
        try:
            repaired = _repair_runtime_files()
            ensure_runtime_data()
            checks = run_checks()
            runtime = next((item for item in checks if item.key == "runtime"), None)
            if runtime and runtime.state == "error" and not getattr(sys, "frozen", False):
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", str(_project_root())],
                    capture_output=True,
                    timeout=300,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode == 0:
                    repaired.append("重新安装了缺失的 Python 依赖")
                else:
                    detail = (result.stderr or result.stdout or "未知错误").strip().splitlines()[-1]
                    repaired.append(f"Python 依赖安装失败：{detail}")
                checks = run_checks()

            blockers = [item.detail for item in checks if item.state == "error"]
            warnings = [item.detail for item in checks if item.state == "warn"]
            lines = repaired or ["本地配置和数据目录无需修复"]
            if blockers:
                lines.append("仍需处理：" + "；".join(blockers))
                lines.append("若程序文件缺失，请重新下载最新版启动器。")
            elif warnings:
                lines.append("环境已可启动。提示：" + "；".join(warnings))
            else:
                lines.append("环境已恢复并通过全部检查。")
            return {"ok": not blockers, "message": "\n".join(lines)}
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": f"修复失败：{exc}"}

    def check_update(self):
        try:
            request = urllib.request.Request(
                "https://api.github.com/repos/DbDB68/maamaru-engine/releases/latest",
                headers={"User-Agent": "MaamaruLauncher/0.1"})
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.load(response)
            tag = data.get("tag_name") or "未知版本"
            latest = tag.removeprefix("v")
            comparison = (_version_tuple(latest) > _version_tuple(CURRENT_VERSION)) - (
                _version_tuple(latest) < _version_tuple(CURRENT_VERSION)
            )
            update_available = comparison > 0
            self._pending_update = None
            if comparison > 0:
                message = f"发现新版本 {tag}\n当前版本：v{CURRENT_VERSION}"
                try:
                    self._pending_update = select_installer(data)
                except UpdateError as exc:
                    message += f"\n自动下载暂不可用：{exc}"
            elif comparison == 0:
                message = f"已经是最新版 v{CURRENT_VERSION}。\nGitHub 最新版本：{tag}"
            else:
                message = f"当前是待发布版本 v{CURRENT_VERSION}。\nGitHub 已发布版本：{tag}"
            return {
                "ok": True,
                "message": message,
                "update_available": update_available,
                "download_ready": self._pending_update is not None,
                "url": data.get("html_url") or "https://github.com/DbDB68/maamaru-engine/releases/latest",
            }
        except Exception:
            self._pending_update = None
            return {"ok": False, "message": "暂时连不上 GitHub，稍后再试。", "update_available": False}

    def download_update(self):
        if self._pending_update is None:
            return {"ok": False, "message": "请先重新检查更新。"}
        try:
            result = download_installer(self._pending_update)
            action = "已找到此前校验完成的安装包" if result["reused"] else "安装包已下载并通过安全校验"
            return {"ok": True, "message": f"{action}。\n位置：{result['path']}"}
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": f"更新下载失败：{exc}"}

    def apply_update(self):
        if self._pending_update is None:
            return {"ok": False, "message": "请先重新检查并下载更新。"}
        installer = UPDATES_DIR / self._pending_update["version"] / self._pending_update["name"]
        try:
            prepare_apply(installer, self._pending_update["digest"].removeprefix("sha256:"),
                          self._pending_update["version"])
            threading.Thread(target=lambda: (time.sleep(0.3), webview.windows[0].destroy()), daemon=True).start()
            return {"ok": True, "message": "まあ丸即将退出并打开安装向导。"}
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": f"无法开始安装：{exc}"}

    def open_updates(self):
        UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(UPDATES_DIR)
        return {"ok": True}

    def open_url(self, url):
        if isinstance(url, str) and url.startswith("https://github.com/DbDB68/maamaru-engine/"):
            os.startfile(url)
            return {"ok": True}
        return {"ok": False}

    def open_data(self):
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        os.startfile(DATA_ROOT)
        return {"ok": True}


def main():
    ensure_runtime_data()
    webview.create_window("まあ丸启动器", html=HTML.replace("__VERSION__", CURRENT_VERSION),
                          js_api=Api(), width=1360, height=900,
                          min_size=(900, 700), resizable=True)
    webview.start(debug=False, icon=str(_launcher_icon_path()))


def _launcher_icon_path() -> Path:
    return _project_root() / "launcher" / "assets" / "maamaru-launcher.ico"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _repair_runtime_files() -> list[str]:
    """Restore writable JSON defaults without overwriting healthy user data."""
    repaired = []
    for target, source, label in _runtime_defaults():
        if not target.exists():
            continue
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            backup = target.with_suffix(target.suffix + f".broken-{time.strftime('%Y%m%d-%H%M%S')}")
            target.replace(backup)
            if source.is_file():
                target.write_bytes(source.read_bytes())
            else:
                target.write_text("{}\n", encoding="utf-8")
            repaired.append(f"已备份并重建损坏的{label}")
    ensure_runtime_data()
    return repaired


def _runtime_defaults():
    from touken.runtime_paths import CONFIG_PATH, PANEL_CONFIG_PATH, SCHEDULE_PATH

    return (
        (CONFIG_PATH, _project_root() / "touken_config.example.json", "本丸配置"),
        (PANEL_CONFIG_PATH, _project_root() / "panel" / "panel_config.example.json", "面板配置"),
        (SCHEDULE_PATH, _project_root() / "panel" / "expedition_schedule.json", "远征排班"),
    )


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for segment in value.split("."):
        digits = "".join(char for char in segment if char.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


def _port_alive() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=0.5):
            return True
    except OSError:
        return False


def _write_launcher_log(content: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / "launcher.log"
        # The panel startup hook writes the original exception before Uvicorn
        # converts it to SystemExit(3).  Append here instead of erasing it.
        with path.open("a", encoding="utf-8") as stream:
            if path.stat().st_size:
                stream.write("\n\n--- launcher ---\n")
            stream.write(content)
    except OSError:
        pass
