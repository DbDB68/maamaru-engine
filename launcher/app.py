"""Friendly WebView launcher for non-technical users."""

import base64
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

from touken.diagnostics import create_diagnostic_bundle
from touken.emulator_discovery import auto_configure_emulator, configure_mumu_from_folder
from touken.data_relocation import (
    cleanup_previous_data,
    pending_relocation_cleanup,
    relocate_user_data,
    suggested_data_root,
)
from touken.runtime_paths import DATA_ROOT, LOG_DIR, UPDATES_DIR, ensure_runtime_data
from .health import has_blocker, run_checks
from .update_apply import consume_result, prepare_apply
from .updater import UpdateError, download_installer, select_installer
from .version import CURRENT_VERSION


HTML = r"""
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--ink:#332b23;--muted:#82766a;--paper:#f3ecdf;--card:#fffaf1;--line:#ddd0bb;--gold:#d99d08;--gold-deep:#a96f00;--gold-pale:#fff0bd;--green:#3f8f69;--red:#b74b44;--orange:#c77a1e}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;user-select:none}button{font:inherit;cursor:pointer}
header{height:108px;padding:13px max(28px,calc((100% - 1120px)/2));background:linear-gradient(115deg,#29231f 0,#44352a 64%,#5f4020 100%);color:white;border-bottom:4px solid var(--gold);box-shadow:0 3px 12px #4b321c33}
.brand{display:flex;height:78px;align-items:center;gap:17px}.brand img{width:76px;height:76px;object-fit:contain;image-rendering:auto}.brand-copy{min-width:0}.brand h1{margin:0;font-size:27px;letter-spacing:.04em}.brand p{margin:4px 0 0;color:#eadfcf;font-size:13px}.version{margin-left:auto;padding:6px 10px;color:#f7df9c;background:#ffffff12;border:1px solid #ffffff28;border-radius:999px;font-size:12px}
main{width:min(1120px,calc(100% - 44px));margin:0 auto;padding:22px 0 18px}.hero{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:22px;align-items:center;padding:22px 24px;background:linear-gradient(125deg,var(--card),#fff5d7);border:1px solid #dac9ab;border-left:5px solid var(--gold);border-radius:15px;box-shadow:0 7px 20px #705a3314}
.eyebrow{display:block;margin-bottom:7px;color:var(--gold-deep);font-size:12px;font-weight:700;letter-spacing:.12em}.hero h2{margin:0;font-size:28px;line-height:1.25}.hero p{margin:8px 0 0;color:var(--muted);font-size:14px;line-height:1.6}.hero-state{display:flex;align-items:center;gap:13px}.state-mark{display:grid;width:48px;height:48px;flex:0 0 48px;place-items:center;color:white;background:var(--gold);border-radius:50%;font-size:24px;font-weight:800}.hero.blocked{border-left-color:var(--red)}.hero.blocked .state-mark{background:var(--red)}.hero.ready .state-mark{background:var(--green)}
.start{width:100%;height:58px;border:0;border-radius:11px;color:white;background:linear-gradient(#e6aa0b,#ce8c00);box-shadow:0 4px 0 #855900,0 8px 14px #a56e1630;font-size:18px;font-weight:800}.start:hover{filter:brightness(1.04)}.start:active{transform:translateY(2px);box-shadow:0 2px 0 #855900}.start:disabled{cursor:not-allowed;filter:grayscale(.65);opacity:.66}
.launch-progress{display:none;margin-top:13px;grid-template-columns:repeat(3,1fr);gap:5px}.launch-progress.show{display:grid}.launch-progress span{padding-top:7px;color:#a49483;border-top:3px solid #ddcfb9;font-size:11px;text-align:center}.launch-progress span.active{color:var(--gold-deep);border-color:var(--gold);font-weight:700}.launch-progress span.done{color:var(--green);border-color:var(--green)}
.checks{margin-top:18px;padding:18px 20px;background:var(--card);border:1px solid var(--line);border-radius:14px}.checks-head{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin-bottom:12px}.checks-head h3{margin:0;font-size:18px}.checks-head p{margin:3px 0 0;color:var(--muted);font-size:12px}.checks-count{color:var(--muted);font-size:12px}.issues{display:grid;gap:8px}.issue{display:grid;grid-template-columns:28px 118px 1fr;gap:8px;align-items:center;padding:11px 12px;border:1px solid #ecd4a8;border-radius:9px;background:#fff8e7}.issue.error{border-color:#e5b6b2;background:#fff0ee}.issue .mark{display:grid;width:22px;height:22px;place-items:center;color:white;background:var(--orange);border-radius:50%;font-size:13px;font-weight:800}.issue.error .mark{background:var(--red)}.issue b{font-size:14px}.issue small{color:var(--muted);font-size:12px;line-height:1.45}
.healthy{margin-top:9px;border-top:1px dashed #e2d7c5}.healthy summary{padding:11px 2px 3px;color:var(--green);cursor:pointer;font-size:12px;font-weight:700}.healthy-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:7px}.healthy-row{display:grid;grid-template-columns:21px 96px 1fr;gap:5px;padding:8px 10px;background:#f7f2e8;border-radius:8px;font-size:12px}.healthy-row i{color:var(--green);font-style:normal;font-weight:800}.healthy-row span{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.loading{padding:44px 0;color:var(--muted);text-align:center}.tools{display:flex;align-items:center;gap:8px;margin-top:14px}.tools-label{margin-right:auto;color:var(--muted);font-size:12px}.tools button{min-height:36px;padding:7px 12px;color:#554b40;background:transparent;border:1px solid #d3c5af;border-radius:8px}.tools button:hover{background:var(--card);border-color:#b99e72}.tools button:disabled{cursor:not-allowed;opacity:.55}.note{margin:12px 2px 0;color:#918579;font-size:11px}
@media(max-width:940px){header{padding-inline:24px}main{width:calc(100% - 30px)}.hero{grid-template-columns:1fr}.hero-action{display:grid;grid-template-columns:minmax(230px,320px) 1fr;gap:14px;align-items:start}.launch-progress{margin-top:0}.healthy-grid{grid-template-columns:1fr}.tools{flex-wrap:wrap}.tools-label{width:100%;flex-basis:100%}}
</style></head><body>
<header><div class="brand"><img src="__ICON_URI__" alt=""><div class="brand-copy"><h1>まあ丸</h1><p>本丸近侍启动器 · 狐之助已经替你看过一遍</p></div><span class="version">v__VERSION__</span></div></header>
<main>
<section id="hero" class="hero"><div class="hero-state"><span id="stateMark" class="state-mark">…</span><div><span class="eyebrow">启动状态</span><h2 id="stateTitle">正在整理启动环境</h2><p id="stateCopy">稍等一下，狐之助正在确认程序、面板与模拟器。</p></div></div><div class="hero-action"><button id="start" class="start" onclick="startApp()" disabled>正在检查…</button><div id="launchProgress" class="launch-progress"><span>整理环境</span><span>启动面板</span><span>打开本丸</span></div></div></section>
<section class="checks"><div class="checks-head"><div><h3>启动前检查</h3><p>只把需要你留意的事情摆在外面。</p></div><span id="checksCount" class="checks-count">正在检查…</span></div><div id="checks"><div class="loading">狐之助正在巡查……</div></div></section>
<div class="tools"><span class="tools-label">启动器工具</span><button onclick="refresh()">↻ 重新检查</button><button onclick="repair()">🔧 修复环境</button><button onclick="chooseEmulator(this)">🖥️ 选择模拟器</button><button onclick="update()">⬆ 检查更新</button><button id="feedbackButton" onclick="exportFeedback(this)">📦 反馈错误</button><button id="issueButton" style="display:none" onclick="openIssue()">↗ 去 Issue</button><button onclick="openData()">📁 数据目录</button><button id="migrateDataButton" onclick="migrateData(this)">🗂️ 迁移数据</button><button id="cleanupDataButton" style="display:none" onclick="cleanupOldData(this)">🧹 清理旧副本</button></div>
<p class="note">QQ 协议端是可选功能，请在面板“系统 → QQ”中配置。</p>
</main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stateIcon={error:'×',warn:'!',info:'i',ok:'✓'};
const issueUrl='https://github.com/DbDB68/maamaru-engine/issues/new';let feedbackFailures=0;let feedbackResetTimer=0;const feedbackLines={1:'导出失败？问问上天',2:'还失败？去issue骂作者',4:'干嘛不去？',5:'你是不是想骂连错误处理系统都做不好？',6:'噫吁嚱，惶恐滩头说惶恐，零丁洋里叹零丁。',7:'面包店里卖面包，蛋糕店里卖蛋糕。',8:'你还点',9:'？',10:'我没有日志，你也不去issue，你到底想让我怎样'};
function setState(kind,title,copy,mark){const hero=document.querySelector('#hero');hero.className='hero '+kind;document.querySelector('#stateTitle').textContent=title;document.querySelector('#stateCopy').textContent=copy;document.querySelector('#stateMark').textContent=mark}
function renderChecks(items){
 const issues=items.filter(x=>x.state==='error'||x.state==='warn');const healthy=items.filter(x=>x.state!=='error'&&x.state!=='warn');
 const issueHtml=issues.length?`<div class="issues">${issues.map(x=>`<div class="issue ${x.state}"><span class="mark">${stateIcon[x.state]}</span><b>${esc(x.label)}</b><small>${esc(x.detail)}</small></div>`).join('')}</div>`:'';
 const healthyHtml=`<details class="healthy" ${issues.length?'':'open'}><summary>${healthy.length} 项检查正常${issues.length?' · 展开查看':''}</summary><div class="healthy-grid">${healthy.map(x=>`<div class="healthy-row"><i>${stateIcon[x.state]}</i><b>${esc(x.label)}</b><span title="${esc(x.detail)}">${esc(x.detail)}</span></div>`).join('')}</div></details>`;
 document.querySelector('#checks').innerHTML=issueHtml+healthyHtml;document.querySelector('#checksCount').textContent=`${items.length} 项 · ${issues.length?issues.length+' 项提醒':'全部通过'}`;
 return issues;
}
async function refresh(){
 setState('','正在整理启动环境','稍等一下，狐之助正在确认程序、面板与模拟器。','…');const start=document.querySelector('#start');start.disabled=true;start.textContent='正在检查…';document.querySelector('#checks').innerHTML='<div class="loading">狐之助正在巡查……</div>';
 const data=await pywebview.api.check();if(data.update_result){alert(data.update_result.ok?data.update_result.message:(data.update_result.message+(data.update_result.rolled_back?'\n旧版程序已经恢复。':'')))}const cleanup=document.querySelector('#cleanupDataButton');cleanup.style.display=data.data_cleanup?'inline-block':'none';cleanup.dataset.token=data.data_cleanup?.token||'';cleanup.dataset.source=data.data_cleanup?.source||'';
 const issues=renderChecks(data.items);const warnings=issues.filter(x=>x.state==='warn').length;
 if(data.blocked){setState('blocked','还差一步','先处理下方红色项目，处理完成后再重新检查。','×');start.textContent='暂时无法启动'}
 else if(warnings){setState('ready','可以启动',`${warnings} 项提醒不会阻止打开面板，需要时再处理。`,'✓');start.textContent='启动まあ丸';start.disabled=false}
 else{setState('ready','准备好了','程序与运行环境均已就绪，可以安心开工。','✓');start.textContent='启动まあ丸';start.disabled=false}
}
function setLaunchStep(index){const steps=[...document.querySelectorAll('#launchProgress span')];document.querySelector('#launchProgress').classList.add('show');steps.forEach((step,i)=>step.className=i<index?'done':i===index?'active':'')}
async function startApp(){const b=document.querySelector('#start');b.disabled=true;b.textContent='正在启动…';setState('','正在打开本丸','这次不需要你盯着黑窗口。','…');setLaunchStep(0);const timer=setTimeout(()=>setLaunchStep(1),500);const r=await pywebview.api.start();clearTimeout(timer);if(!r.ok){document.querySelector('#launchProgress').classList.remove('show');setState('blocked','启动没有完成','错误已经留在启动记录中，可以修复后重试。','×');alert('启动失败：'+r.message);b.disabled=false;b.textContent='重新启动'}else{setLaunchStep(2);b.textContent='✓ 已启动';setState('ready','本丸已经打开','启动器的工作完成了，接下来交给まあ丸。','✓')}}
async function repair(){setState('','正在修复环境','狐之助正在补齐可以自动恢复的项目。','…');const r=await pywebview.api.repair();alert(r.message);await refresh()}
async function update(){setState('','正在检查更新','正在向まあ丸的 GitHub 发布页确认最新版。','…');const r=await pywebview.api.check_update();if(r.update_available&&r.download_ready){if(confirm(r.message+'\n\n要现在安全下载到更新暂存区吗？')){setState('','正在下载更新','安装包下载后还会校验大小和 SHA-256。','…');const d=await pywebview.api.download_update();alert(d.message);if(d.ok&&confirm('安装包已经校验完成。\n\n要关闭まあ丸并打开安装向导吗？')){const a=await pywebview.api.apply_update();if(!a.ok)alert(a.message)}}}else if(r.update_available&&r.url){if(confirm(r.message+'\n\n暂时无法自动下载，要打开发布页面吗？'))await pywebview.api.open_url(r.url)}else{alert(r.message)}await refresh()}
async function exportFeedback(button){if(button.disabled)return;button.disabled=true;button.textContent='正在整理…';let r;try{r=await pywebview.api.export_diagnostics()}catch(_){r={ok:false}}if(r.ok){alert(r.message);feedbackFailures=0;document.querySelector('#issueButton').style.display='none';button.disabled=false;button.textContent='📦 反馈错误';return}feedbackFailures+=1;if(feedbackFailures===3){document.querySelector('#issueButton').style.display='inline-block'}else if(feedbackFailures>=11){button.textContent='狐之助已下班';clearTimeout(feedbackResetTimer);feedbackResetTimer=setTimeout(()=>{feedbackFailures=0;button.disabled=false;button.textContent='📦 反馈错误';document.querySelector('#issueButton').style.display='none'},3000);return}else{alert(feedbackLines[feedbackFailures]||'导出失败')}button.disabled=false;button.textContent='📦 反馈错误'}
async function openIssue(){await pywebview.api.open_url(issueUrl)}
async function openData(){await pywebview.api.open_data()}
async function chooseEmulator(button){button.disabled=true;const r=await pywebview.api.choose_emulator();if(r.message)alert(r.message);button.disabled=false;if(r.ok)await refresh()}
async function migrateData(button){button.disabled=true;let chosen;try{chosen=await pywebview.api.choose_data_location()}catch(_){chosen={ok:false,message:'没能打开目录选择器'}}if(!chosen.ok){button.disabled=false;if(chosen.message)alert(chosen.message);return}if(!confirm(`まあ丸会先完整复制并校验用户数据，再让下次启动改用：\n\n${chosen.target}\n\n原目录暂时保留，确认新目录可用后可在启动器清理。现在开始吗？`)){button.disabled=false;return}button.textContent='正在迁移…';const r=await pywebview.api.migrate_data(chosen.selected);alert(r.message);button.disabled=false;button.textContent='🗂️ 迁移数据';if(r.ok){alert('请关闭并重新打开まあ丸。新目录通过启动检查后，会出现“清理旧副本”按钮。')}}
async function cleanupOldData(button){const source=button.dataset.source;if(!confirm(`新目录已经通过校验。确定永久删除旧数据副本吗？\n\n${source}\n\n此操作无法撤销。`))return;button.disabled=true;const r=await pywebview.api.cleanup_old_data(button.dataset.token);alert(r.message);if(r.ok){button.style.display='none'}else{button.disabled=false}}
window.addEventListener('pywebviewready',refresh);
</script></body></html>
"""


class Api:
    def __init__(self):
        self._pending_update = None

    def check(self):
        ensure_runtime_data()
        auto_configure_emulator()
        checks = run_checks()
        cleanup = pending_relocation_cleanup()
        return {
            "blocked": has_blocker(checks),
            "items": [item.__dict__ for item in checks],
            "update_result": consume_result(),
            "data_root": str(DATA_ROOT),
            "data_cleanup": ({
                "token": cleanup["token"],
                "source": cleanup["source"],
            } if cleanup else None),
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

    def choose_data_location(self):
        try:
            selected = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            if not selected:
                return {"ok": False, "message": ""}
            folder = selected[0] if isinstance(selected, (list, tuple)) else selected
            return {
                "ok": True,
                "selected": str(folder),
                "target": str(suggested_data_root(folder)),
            }
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": f"没能选择新目录：{exc}"}

    def choose_emulator(self):
        try:
            selected = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            if not selected:
                return {"ok": False, "message": ""}
            folder = selected[0] if isinstance(selected, (list, tuple)) else selected
            found = configure_mumu_from_folder(folder)
            if found is None:
                return {
                    "ok": False,
                    "message": "这个目录里没有同时找到 MuMu 的 ADB 和管理器。\n"
                               "请选择 MuMu 的安装目录，而不是桌面快捷方式所在的目录。",
                }
            return {
                "ok": True,
                "message": f"已设置 MuMu 模拟器：\n{found.manager_path}",
            }
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": f"没能设置模拟器：{exc}"}

    def migrate_data(self, selected_folder):
        try:
            result = relocate_user_data(selected_folder)
            size_mb = result["bytes"] / (1024 * 1024)
            return {
                "ok": True,
                "message": (
                    f"用户数据已复制并校验完成：{result['files']} 个文件，"
                    f"约 {size_mb:.1f} MB。\n\n新目录：{result['target']}\n"
                    "原目录尚未删除，重新启动まあ丸后再确认清理。"
                ),
            }
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": f"迁移没有完成：{exc}\n原目录未删除。"}

    def cleanup_old_data(self, confirmation_token):
        try:
            result = cleanup_previous_data(str(confirmation_token or ""))
            return {
                "ok": True,
                "message": f"旧数据副本已清理：{result['source']}\n当前数据仍保存在：{result['target']}",
            }
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": f"旧副本没有删除：{exc}"}

    def export_diagnostics(self):
        try:
            path = create_diagnostic_bundle()
            try:
                subprocess.Popen(
                    ["explorer.exe", "/select,", str(path)],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError:
                os.startfile(path.parent)
            return {"ok": True, "message": f"错误反馈包已经生成，并在文件夹中替你选好了。\n\n{path.name}"}
        except Exception as exc:
            _write_launcher_log(traceback.format_exc())
            return {"ok": False, "message": f"暂时没能生成错误反馈包：{exc}"}


def main():
    ensure_runtime_data()
    html = HTML.replace("__VERSION__", CURRENT_VERSION).replace(
        "__ICON_URI__", _launcher_icon_data_uri())
    webview.create_window("まあ丸启动器", html=html,
                          js_api=Api(), width=1080, height=720,
                          min_size=(860, 640), resizable=True)
    webview.start(debug=False, icon=str(_launcher_icon_path()))


def _launcher_icon_path() -> Path:
    return _project_root() / "launcher" / "assets" / "maamaru-launcher.ico"


def _launcher_icon_data_uri() -> str:
    path = _launcher_icon_path().with_name("maamaru-launcher-header.png")
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


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
