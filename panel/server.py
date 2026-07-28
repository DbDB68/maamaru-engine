"""
まあ丸 控制面板 —— FastAPI 服务
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

# 确保能找到 touken 包（开发模式）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .log_store import get_store
from .script_runner import get_runner, list_scripts, register_script, ScriptRunner
from .chat_ai import get_ai

# ── 路径 ──
_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"
_PROJECT = _HERE.parent
_CONFIG_PATH = _PROJECT / "touken_config.json"
_PANEL_CONFIG = _HERE / "panel_config.json"

# 默认 ADB 配置（从 test_daily.py 继承）
_DEFAULT_ADB_PATH = r"D:\MUMU\MuMuPlayer\nx_device\12.0\shell\adb.exe"
_DEFAULT_ADB_ADDR = "127.0.0.1:16384"

# ── App ──
app = FastAPI(title="まあ丸 近侍面板")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# SSE 广播队列（全局，所有订阅者共享）
_broadcast_queue: asyncio.Queue | None = None


def _start_broadcast():
    global _broadcast_queue
    if _broadcast_queue is None:
        _broadcast_queue = asyncio.Queue()


def _on_script_message(payload: dict):
    """脚本消息回调：从工作线程推到 asyncio 队列"""
    if _broadcast_queue is not None:
        try:
            # 在非 async 上下文推入 async 队列
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(_broadcast_queue.put_nowait, payload)
            else:
                loop.run_until_complete(_broadcast_queue.put(payload))
        except RuntimeError:
            pass  # 没有事件循环时静默丢弃


# ── 注册脚本 ──

def _make_maa(config_path):
    """创建 MAAAdapter（优先读配置，fallback 到 test_daily.py 里的硬编码路径）"""
    from touken import MAAAdapter
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return MAAAdapter(
        adb_path=cfg.get("adb_path", _DEFAULT_ADB_PATH),
        adb_address=cfg.get("adb_address", _DEFAULT_ADB_ADDR),
        resource_dir=str(_PROJECT / "resource" / "base"),
        project_root=str(_PROJECT),
        manager_path=cfg.get("emulator_manager"),
        emulator_instance=int(cfg.get("emulator_instance", 0)),
    )


def _make_agent(config_path):
    from touken import ToukenAgent
    maa = _make_maa(config_path)
    if not maa.init():
        raise RuntimeError("MAA 初始化失败，检查 ADB 连接 / 模拟器是不是关了")
    return ToukenAgent(str(config_path), maa)


def _i(params, key, default):
    """参数转 int，空串/None 用默认"""
    v = params.get(key)
    if v in (None, ""):
        return default
    return int(v)


# ── 参数表单零件 ──
_TEAM_OPTIONS = [["1", "部队一"], ["2", "部队二"], ["3", "部队三"],
                 ["4", "部队四"], ["5", "部队五"]]
_DAILY_STEPS = ["登录", "签到", "万屋", "演练", "远征", "内番",
                "锻刀", "刀解", "合成", "出阵", "任务奖励", "库存快照"]


def _team_field(default="3"):
    return {"key": "team_no", "type": "select", "label": "部队",
            "options": _TEAM_OPTIONS, "default": default}


# ── 各脚本 builder（签名统一：(config_path, params) -> generator）──

def _build_daily(config_path, params):
    steps = params.get("steps") or None   # 空列表=全跑
    after = params.get("after") or "none"
    # 出阵安排：面板选的覆盖配置文件里的默认
    mode = params.get("sortie_mode") or "none"
    if mode == "raid":
        sortie_plan = {"mode": "raid",
                       "rounds": _i(params, "raid_rounds", 3),
                       "team_no": _i(params, "team_no", 3)}
    elif mode == "sortie":
        sortie_plan = {"mode": "sortie",
                       "chapter": _i(params, "chapter", 1),
                       "map_no": _i(params, "map_no", 1),
                       "loops": _i(params, "loops", 1),
                       "team_no": _i(params, "team_no", 3)}
    else:
        sortie_plan = {"mode": "none"}
    yield from _make_agent(config_path).daily_stream(
        only=steps, after=after, sortie_override=sortie_plan)


def _build_raid(config_path, params):
    yield from _make_agent(config_path).raid_stream(
        max_rounds=_i(params, "rounds", 3),
        team_no=_i(params, "team_no", 3))


def _build_sortie(config_path, params):
    yield from _make_agent(config_path).sortie_stream(
        chapter=_i(params, "chapter", 1),
        map_no=_i(params, "map_no", 1),
        team_no=_i(params, "team_no", 3),
        auto_march=True,
        max_loops=_i(params, "loops", 1))


def _build_sakura(config_path, params):
    yield from _make_agent(config_path).sakura_stream(
        team_no=_i(params, "team_no", 1),
        slot=_i(params, "slot", 1))


def _build_forge(config_path, params):
    watch_raw = params.get("watch") or ""
    watch = [w.strip() for w in re.split(r"[，,、;；\s]+", watch_raw) if w.strip()]
    yield from _make_agent(config_path).forge_stream(
        times=_i(params, "times", 3), watch=watch)


def _build_dispatch(config_path, params):
    """手动派遣一支部队去远征（时刻表也走这个）"""
    from .scheduler import find_map
    code = params.get("map_code") or ""
    m = find_map(code)
    if not m:
        yield f"[远征] 不知道图 {code} 是哪张，没派"
        return
    yield from _make_agent(config_path).expedition_stream(
        era=m["era"], map_slot=m["slot"],
        team_no=_i(params, "team_no", 2))


def _build_simple(stream_method_name):
    def _fn(config_path, params):
        agent = _make_agent(config_path)
        method = getattr(agent, stream_method_name, None)
        if method is None:
            raise RuntimeError(f"Agent 没有 {stream_method_name} 方法")
        yield from method()
    return _fn


register_script("daily", "一键日课", "勾选要干的活，一条龙跑完",
                _build_daily,
                params=[{"key": "steps", "type": "checks", "label": "要干的活（不勾的不跑）",
                         "options": _DAILY_STEPS, "default": _DAILY_STEPS},
                        {"key": "sortie_mode", "type": "select", "label": "出阵安排",
                         "options": [["none", "不出阵"],
                                     ["raid", "联队战（活动）"],
                                     ["sortie", "合战场推图"]],
                         "default": "raid"},
                        {"key": "team_no", "type": "select", "label": "出阵部队",
                         "options": _TEAM_OPTIONS, "default": "3",
                         "visibleWhen": {"key": "sortie_mode", "not": "none"}},
                        {"key": "raid_rounds", "type": "number", "label": "联队战圈数",
                         "default": 3, "min": 1, "max": 99,
                         "visibleWhen": {"key": "sortie_mode", "is": "raid"}},
                        {"key": "chapter", "type": "select", "label": "章节",
                         "options": [[str(i), f"{i}章"] for i in range(1, 9)],
                         "default": "1",
                         "visibleWhen": {"key": "sortie_mode", "is": "sortie"}},
                        {"key": "map_no", "type": "select", "label": "小图",
                         "options": [[str(i), f"{i}图"] for i in range(1, 5)],
                         "default": "1",
                         "visibleWhen": {"key": "sortie_mode", "is": "sortie"}},
                        {"key": "loops", "type": "number", "label": "连打几圈",
                         "default": 1, "min": 1, "max": 99,
                         "visibleWhen": {"key": "sortie_mode", "is": "sortie"}},
                        {"key": "after", "type": "select", "label": "跑完后（默认啥也不干）",
                         "options": [["none", "啥也不干"],
                                     ["logout", "退出游戏"],
                                     ["shutdown", "退出游戏 + 关模拟器"],
                                     ["sleep", "退出 + 关模拟器 + 电脑休眠"]],
                         "default": "none"}])
register_script("raid", "联队战", "活动图刷票，默认部队三",
                _build_raid,
                params=[_team_field("3"),
                        {"key": "rounds", "type": "number", "label": "圈数",
                         "default": 3, "min": 1, "max": 99}])
register_script("sortie", "出阵", "普通图：部队x 去打 x-x",
                _build_sortie,
                params=[_team_field("3"),
                        {"key": "chapter", "type": "select", "label": "章节",
                         "options": [[str(i), f"{i}章"] for i in range(1, 9)], "default": "1"},
                        {"key": "map_no", "type": "select", "label": "小图",
                         "options": [[str(i), f"{i}图"] for i in range(1, 5)], "default": "1"},
                        {"key": "loops", "type": "number", "label": "连打几圈",
                         "default": 1, "min": 1, "max": 99}])
register_script("sakura", "刷花", "队长单挑 1-1 刷疲劳到 100，满了自动换人",
                _build_sakura,
                params=[_team_field("1"),
                        {"key": "slot", "type": "select", "label": "位置",
                         "options": [[str(i), f"{i}号位" + ("（队长）" if i == 1 else "")]
                                     for i in range(1, 7)], "default": "1"}])
register_script("practice", "演练", "只认人打软柿子，赢 3 场收工",
                _build_simple("practice_stream"))
register_script("expedition", "远征", "收菜 + 自动再派",
                _build_simple("collect_expedition_stream"))


def _map_select_field():
    from .scheduler import map_options
    opts = [[o["code"], f'{o["code"]} · {o["name"]}（{o["duration_text"]}）']
            for o in map_options()]
    return {"key": "map_code", "type": "select", "label": "远征图",
            "options": opts, "default": opts[0][0] if opts else ""}


register_script("dispatch", "派遣远征", "立刻派一支部队去指定远征图",
                _build_dispatch,
                params=[_team_field("2"), _map_select_field()])
register_script("forge", "锻刀", "选次数+盯目标时长，命中时长手机报喜",
                _build_forge,
                params=[{"key": "times", "type": "number", "label": "锻几炉",
                         "default": 3, "min": 1, "max": 12},
                        {"key": "watch", "type": "text",
                         "label": "目标时长（逗号分隔，限锻刀的时间身份证，不填不盯）",
                         "default": "", "placeholder": "如 03:20:00, 04:00:00"}])
register_script("sugar", "炼糖", "收件箱清狗粮 + 习合循环",
                _build_simple("sugar_stream"))
register_script("snapshot", "库存快照", "刷新看板库存数据",
                _build_simple("status_snapshot_stream"))


# ── 服务端启动 ──

@app.on_event("startup")
async def startup():
    _start_broadcast()
    runner = get_runner()
    runner.set_message_callback(_on_script_message)

    # 远征时刻表调度线程：到点自动派遣（面板关着就不会派）
    from .scheduler import start_scheduler
    from .log_store import get_store as _get_store

    def _sched_emit(script, message):
        _get_store().append("scheduler", script, message)
        _on_script_message({"id": None, "ts": time.time(),
                            "run_id": "scheduler", "script": script,
                            "message": message})

    start_scheduler(str(_CONFIG_PATH), _sched_emit)


# ── 静态文件 ──

@app.get("/")
async def index():
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/favicon.ico")
async def favicon():
    return JSONResponse({"ok": False}, status_code=404)


# ── API：日志 ──

@app.get("/api/logs")
async def get_logs(limit: int = 100, after_id: int = 0):
    store = get_store()
    logs = store.get_recent(limit=limit, after_id=after_id)
    last_id = store.get_last_id()
    return {"logs": logs, "last_id": last_id}


@app.get("/api/logs/stream")
async def stream_logs(request: Request):
    """SSE 日志流"""
    async def event_generator():
        store = get_store()
        last_id = store.get_last_id()
        while True:
            if await request.is_disconnected():
                break
            try:
                # 从广播队列取（实时消息）
                msg = await asyncio.wait_for(_broadcast_queue.get(), timeout=2.0)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                # 新消息检查：取 after_id 之后落盘的日志
                logs = store.get_recent(limit=50, after_id=last_id)
                for log in logs:
                    if log["id"] > last_id:
                        yield f"data: {json.dumps(log, ensure_ascii=False)}\n\n"
                        last_id = log["id"]
                yield ": heartbeat\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── API：脚本 ──

@app.get("/api/scripts")
async def api_scripts():
    runner = get_runner()
    return {
        "scripts": list_scripts(),
        "running": runner.is_running,
        "current": runner.current_script,
    }


@app.post("/api/scripts/run")
async def api_run_script(request: Request):
    body = await request.json()
    script_name = body.get("script", "")
    params = body.get("params", {})
    runner = get_runner()
    run_id = runner.start(script_name, str(_CONFIG_PATH), params=params)
    if run_id is None:
        return JSONResponse({"ok": False, "reason": "不支持或正在运行"}, status_code=400)
    return {"ok": True, "run_id": run_id}


@app.post("/api/scripts/stop")
async def api_stop_script():
    runner = get_runner()
    if not runner.is_running:
        return {"ok": False, "reason": "没有在运行的脚本"}
    runner.stop()
    return {"ok": True}


# ── API：聊天 ──

@app.get("/api/chat/history")
async def api_chat_history():
    store = get_store()
    return {"history": store.get_chat_history()}


@app.post("/api/chat")
async def api_chat(request: Request):
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"reply": "（狐之助歪了歪头：主君，你说什么？）"})

    ai = get_ai(str(_PANEL_CONFIG))
    try:
        reply = ai.chat(message)
    except Exception as exc:
        reply = f"（狐之助耳朵耷拉下来：主君…我脑子冒烟了 — {exc}）"
    return {"reply": reply}


# ── API：Agent 网关（跨渠道 LLM 入口）──

_agent_gateway = None


@app.post("/api/agent")
async def api_agent(request: Request):
    """
    Agent 网关入口：接收任意渠道的消息，LLM 理解意图，调用工具。

    Body: {"message": "...", "channel": "qq"}
    Returns: {"reply": "...", "tool_called": true/false}
    """
    from .agent import AgentGateway
    global _agent_gateway
    if _agent_gateway is None:
        _agent_gateway = AgentGateway(str(_PANEL_CONFIG))

    body = await request.json()
    message = body.get("message", "").strip()
    channel = body.get("channel", "qq")
    if not message:
        return {"reply": "（狐之助歪了歪头：你说什么？）", "tool_called": False}

    try:
        reply = _agent_gateway.process(message, channel=channel)
        return {"reply": reply, "tool_called": True}
    except Exception as exc:
        return {"reply": f"（狐之助耳朵耷拉下来：脑子冒烟了 — {exc}）", "tool_called": False}


# ── API：远征时刻表 ──

@app.get("/api/expedition-schedule")
async def api_get_schedule():
    from .scheduler import load_entries, map_options
    return {"entries": load_entries(), "maps": map_options()}


@app.post("/api/expedition-schedule")
async def api_save_schedule(request: Request):
    from .scheduler import save_entries
    body = await request.json()
    entries = body.get("entries", [])
    # 只留前端该给的字段，别什么都往里塞
    clean = [{
        "time": str(e.get("time", ""))[:5],
        "team_no": int(e.get("team_no", 2)),
        "map_code": str(e.get("map_code", "")),
        "map_name": str(e.get("map_name", "")),
        "enabled": bool(e.get("enabled", True)),
        "last_fired": str(e.get("last_fired", "")),
    } for e in entries if e.get("time") and e.get("map_code")]
    save_entries(clean)
    return {"ok": True, "count": len(clean)}


# ── API：状态 ──

@app.get("/api/status")
async def api_status():
    """读取最新的日课成绩单和库存"""
    status_dir = _PROJECT / "status"
    data = {}
    for fn in ("latest_report.json", "inventory.json"):
        fp = status_dir / fn
        if fp.exists():
            data[fn.replace(".json", "")] = json.loads(fp.read_text(encoding="utf-8"))
    return data


# ── API：保存/加载面板设置 ──

_SETTINGS_FILE = _PROJECT / "status" / "panel_settings.json"


def _load_panel_settings() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_panel_settings(data: dict):
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["_saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/saved-settings")
async def api_get_saved_settings():
    """获取服务器端保存的面板设置（所有脚本的参数记忆）"""
    return _load_panel_settings()


@app.post("/api/saved-settings")
async def api_save_settings(request: Request):
    """保存面板上所有脚本的当前参数到服务器端"""
    body = await request.json()
    # body 格式: {"params": {"daily": {...}, "raid": {...}, ...}}
    params = body.get("params", {})
    # 只保留有内容的条目，空 dict 也保留（表示全默认）
    clean = {k: v for k, v in params.items() if isinstance(v, dict)}
    _save_panel_settings({"params": clean})
    return {"ok": True, "scripts": len(clean)}


# ── 入口 ──

def main():
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="まあ丸 近侍面板")
    parser.add_argument("--host", default="0.0.0.0",
                        help="默认 0.0.0.0 监听全网卡，手机才能连；只想本机用就传 127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--config", default=str(_CONFIG_PATH),
                        help="touken_config.json 路径")
    parser.add_argument("--panel-config", default=str(_PANEL_CONFIG),
                        help="面板配置（AI key 等）")
    args = parser.parse_args()

    print(f"⚡ まあ丸 近侍面板 → http://{args.host}:{args.port}")
    if args.host == "0.0.0.0":
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
            print(f"   📱 手机同一 WiFi 下访问 → http://{lan_ip}:{args.port}")
        except OSError:
            pass
    print(f"   配置: {args.config}")
    print(f"   面板配置: {args.panel_config}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
