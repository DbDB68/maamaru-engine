"""
まあ丸 控制面板 —— FastAPI 服务
"""

import asyncio
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

# 确保能找到 touken 包（开发模式）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .log_store import get_store
from .script_runner import get_runner, list_scripts, register_script, ScriptRunner
from touken.diagnostics import build_diagnostic_bundle
from touken.runtime_paths import (
    BUNDLE_ROOT, CONFIG_PATH, LOG_DIR, PANEL_CONFIG_PATH, RESOURCE_DIR, STATUS_DIR,
    ensure_runtime_data,
)

# ── 路径 ──
ensure_runtime_data()
_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"
_PROJECT = BUNDLE_ROOT
_CONFIG_PATH = CONFIG_PATH
_PANEL_CONFIG = PANEL_CONFIG_PATH

# 预读游戏配置（用于面板默认值，不在这里写死游戏内容）
try:
    _CFG_DATA = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
except Exception:
    _CFG_DATA = {}

# 刀解默认白名单（兼容旧配置：配置里没有就用这个常量）
from touken.flows.smith import DISMANTLE_WHITELIST as _DISMANTLE_WHITELIST

# 默认 ADB 配置（从 test_daily.py 继承）
_DEFAULT_ADB_PATH = r"D:\MUMU\MuMuPlayer\nx_device\12.0\shell\adb.exe"
_DEFAULT_ADB_ADDR = "127.0.0.1:16384"

# ── App ──
app = FastAPI(title="まあ丸 近侍面板")


def _ledger_mode() -> bool:
    """纯净账房模式只开放数据与规划，不启动任何游戏控制设施。"""
    return os.environ.get("MAAMARU_LEDGER_MODE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
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

    # 事件播报器：狐之助主动开口（QQ/ntfy）。播报挂了不许拖累日志管道
    try:
        from .broadcaster import get_broadcaster
        bc = get_broadcaster()
        if bc is not None:
            bc.feed(payload)
    except Exception:
        pass


# ── 注册脚本 ──

def _make_maa(config_path):
    """创建 MAAAdapter（优先读配置，fallback 到 test_daily.py 里的硬编码路径）"""
    from touken import MAAAdapter
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return MAAAdapter(
        adb_path=cfg.get("adb_path", _DEFAULT_ADB_PATH),
        adb_address=cfg.get("adb_address", _DEFAULT_ADB_ADDR),
        resource_dir=str(RESOURCE_DIR),
        project_root=str(STATUS_DIR.parent),
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


def _run_count_field(*, ticket=False, default=1):
    """四种出阵共用的目标数量；玩法内部再解释成圈数或手形预算。"""
    return {"key": "runs", "type": "number",
            "label": "出阵次数",
            "default": default, "min": 1, "max": 99,
            **({"help": "这是本次任务的目标次数；是否花小判补充手形由下方开关决定。"} if ticket else {})}


def _ticket_refill_field():
    return {"key": "auto_refill", "type": "toggle", "label": "是否自动补充手形？",
            "default": False,
            "help": "开启后，手形不足时将自动使用小判补充，直到完成设定的出阵次数。关闭后，手形不足时结束任务，不消耗小判。"}


def _run_count(params, default, *legacy_keys):
    """读取统一字段，同时兼容改版前已保存的各玩法字段。"""
    if params.get("runs") not in (None, ""):
        return _i(params, "runs", default)
    for key in legacy_keys:
        if params.get(key) not in (None, ""):
            return _i(params, key, default)
    return default


def _march_and_injury_fields():
    """合战场与异去共享；阵形仅在脚本行军时显示。"""
    return [
        {"key": "rotate_captain", "type": "toggle", "label": "自动换队长",
         "default": False,
         "help": "出阵前读全队疲劳，把疲劳最低的拖到队长位吃加成（保花用）。一键日课沿用此开关。"},
        {"key": "rotate_captain_margin", "type": "select", "label": "换队长阈值",
         "options": [["5", "相差 5 点"], ["10", "相差 10 点"],
                     ["20", "相差 20 点"]],
         "default": "10",
         "help": "全队最低疲劳比当前队长低到这个差值时才换，避免差距很小时频繁调整。",
         "visibleWhen": {"key": "rotate_captain", "is": True}},
        {"key": "auto_march", "type": "toggle", "label": "是否使用自动行军",
         "default": True},
        {"key": "formation_mode", "type": "select", "label": "阵形选择方式",
         "options": [["manual", "手动阵形"],
                     ["auto", "自动阵形"]],
         "default": "manual",
         "visibleWhen": {"key": "auto_march", "is": "false"}},
        {"key": "formation", "type": "select",
         "label": "固定或识别失败时的兜底阵形",
         "options": [[name, name] for name in
                     ["鱼鳞阵", "横队阵", "雁行阵", "鹤翼阵", "方阵", "逆行阵"]],
         "default": "鱼鳞阵",
         "visibleWhen": {"key": "auto_march", "is": "false"}},
        {"key": "repair_threshold", "type": "select", "label": "伤势停止条件",
         "options": [["light", "轻伤时停止"],
                     ["medium", "中伤时停止"],
                     ["heavy", "重伤时停止"]],
         "default": "light"},
        {"key": "repair_on_injury", "type": "select", "label": "停止后的处理",
         "options": [["continue", "手入加速后继续剩余圈数"],
                     ["repair_stop", "手入后停止任务"],
                     ["stop", "停止任务，不进行手入"]],
         "default": "continue"},
        {"key": "auto_equip", "type": "toggle", "label": "是否自动补充刀装",
         "default": True,
         "help": "任务首次出阵前将当前部队保存到记录一；出现刀装未满提示时，自动用记录一补齐并重新检查伤势。"},
    ]


def _formation_fields():
    """不使用自动行军、但每场仍需选择阵形的玩法共用。
    策略和兜底阵形常显：自动阵形在游戏识别失败（夜战等）时会回落到
    手动按策略选，兜底阵形照样起作用（choose_formation 的设计）。"""
    return [
        {"key": "formation_mode", "type": "select", "label": "阵形选择方式",
         "options": [["manual", "手动阵形"], ["auto", "自动阵形"]],
         "default": "manual"},
        {"key": "formation", "type": "select",
         "label": "固定或识别失败时的兜底阵形",
         "options": [[name, name] for name in
                     ["鱼鳞阵", "横队阵", "雁行阵", "鹤翼阵", "方阵", "逆行阵"]],
         "default": "鱼鳞阵"},
    ]


def _sword_names(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(name).strip() for name in raw if str(name).strip()]
    return [name.strip() for name in str(raw or "").replace("，", ",").split(",")
            if name.strip()]


# ── 各脚本 builder ──
# 玩法脚本统一由 _wrap_inventory 包一层：开工前/收工后各拍一次库存（run 级
# 整体归因）。builder 本体签名统一：(agent, config_path, params) -> generator。

def _wrap_inventory(tag: str, runner, inventory=False):
    """给玩法脚本套统一收尾：库存盘点（默认关闭）+ 必做的回本丸 + 强制 peek。

    为什么盘点默认关了：完整快照融进了锻刀收工（零额外导航），顶栏五资源靠
    各循环 quick_peek 顺路更新（60s 节流），挖地小判差值由 osaka_stream
    自带的掉落率实验记账。专程跑腿盘点太磨叽（7-27 日课超时两次的教训）。
    想给某个任务恢复 run 级盘点就显式传 inventory=True。

    - before：任务开始前拍一张；after：任务结束后拍一张（含自然失败——异常
      会穿过 try/finally，finally 里照样补拍；紧急停止/看门狗是 kill，子进程
      没机会，由面板 has_after_snapshot=False 提示缺收工快照）。
    - 盘点失败绝不拖垮任务：before/after 各自 try，坏了只打日志继续。
    - 收尾回本丸 + 强制顶栏 peek：与 inventory 开关无关，每个任务跑完都执行。
      这是资源总账的固定“跑完了”观察点；若没能回到本丸，则作为故障信号上报。
      收尾失败同样不拖垮任务结果。
    """
    def _fn(config_path, params):
        agent = _make_agent(config_path)
        enabled = inventory(params) if callable(inventory) else inventory
        if enabled and hasattr(agent, "status_snapshot_stream"):
            try:
                yield f"[{tag}] 开工前先盘点一次家底"
                yield from agent.status_snapshot_stream(phase="before")
            except Exception as exc:
                yield f"[{tag}] ⚠️ 开工盘点失败，继续干活：{exc}"
        try:
            yield from runner(agent, config_path, params)
        finally:
            if enabled and hasattr(agent, "status_snapshot_stream"):
                try:
                    yield f"[{tag}] 收工后再盘点一次，准备结算"
                    yield from agent.status_snapshot_stream(phase="after")
                except Exception as exc:
                    yield f"[{tag}] ⚠️ 收工盘点失败（不影响任务结果）：{exc}"
            # --- 新收尾：每个任务跑完都导航回本丸，并强制拍一次顶栏 peek ---
            # 这是固定观察点：给资源总账一个“跑完了”的锚点；如果没回到本丸，
            # 多半是卡在某个界面了，作为故障信号上报。
            try:
                yield f"[{tag}] 收尾：导航回本丸"
                for nav_msg in agent.navigate_to_stream("本丸"):
                    yield nav_msg
                if getattr(agent, "current_location", None) == "本丸":
                    yield f"[{tag}] 收尾：已回本丸，强制拍一次顶栏"
                    if hasattr(agent, "quick_peek"):
                        agent.quick_peek(tag=f"{tag}·收尾", force=True)
                else:
                    yield (f"[{tag}] ⚠️ 收尾没能回到本丸，可能卡在某个界面了，"
                           "去看看")
            except Exception as exc:
                yield f"[{tag}] ⚠️ 收尾导航/Peek 失败（不影响任务结果）：{exc}"
    return _fn


def _build_daily(agent, config_path, params):
    # 面板传 steps，Agent 网关传 only，都认
    steps = params.get("steps") or params.get("only") or None   # 空列表=全跑
    after = params.get("after") or "none"
    # 出阵安排：面板选的覆盖配置文件里的默认
    mode = params.get("sortie_mode") or "none"
    if mode == "raid":
        sortie_plan = {"mode": "raid",
                       "rounds": _i(params, "raid_rounds", 3),
                       "team_no": _i(params, "team_no", 3),
                       "auto_buy_ticket": _bool(params.get("raid_auto_refill", False)),
                       "max_buys": _i(params, "raid_rounds", 3)}
    elif mode == "pumpkin":
        sortie_plan = {"mode": "pumpkin",
                       "difficulty": _i(params, "pumpkin_difficulty", 1),
                       "team_no": _i(params, "team_no", 3),
                       "watch_names": _sword_names(params.get("pumpkin_watch")),
                       "max_skips": _i(params, "pumpkin_runs", 4)}
    elif mode == "yosari":
        saved_yosari = (_load_panel_settings().get("params", {}).get("yosari", {}) or {})
        sortie_plan = {"mode": "yosari",
                       "map_no": _i(params, "yosari_map_no", 1),
                       "team_no": _i(params, "team_no", 3),
                       "loops": _i(params, "yosari_runs", 1),
                       "auto_refill": _bool(params.get("yosari_auto_refill", False)),
                       "auto_march": _bool(saved_yosari.get("auto_march", True)),
                       "formation_mode": saved_yosari.get("formation_mode") or "manual",
                       "formation": saved_yosari.get("formation") or "鱼鳞阵",
                       "repair_threshold": saved_yosari.get("repair_threshold") or "light",
                       "repair_on_injury": saved_yosari.get("repair_on_injury") or "continue",
                       "auto_equip": _bool(saved_yosari.get("auto_equip", True)),
                       "rotate_captain": _bool(saved_yosari.get("rotate_captain", False)),
                       "rotate_captain_margin": _i(
                           saved_yosari, "rotate_captain_margin", 10)}
    elif mode == "sortie":
        # 地图、队伍、圈数由一键日课决定；战斗行为统一沿用「出阵」配置页。
        saved_sortie = (_load_panel_settings().get("params", {}).get("sortie", {}) or {})
        sortie_plan = {"mode": "sortie",
                       "chapter": _i(params, "chapter", 1),
                       "map_no": _i(params, "map_no", 1),
                       "loops": _i(params, "loops", 1),
                       "team_no": _i(params, "team_no", 3),
                       "auto_march": _bool(saved_sortie.get("auto_march", True)),
                       "formation_mode": saved_sortie.get("formation_mode") or "manual",
                       "formation": saved_sortie.get("formation") or "鱼鳞阵",
                       "repair_threshold": saved_sortie.get("repair_threshold") or "light",
                       "repair_on_injury": saved_sortie.get("repair_on_injury") or "continue",
                       "auto_equip": _bool(saved_sortie.get("auto_equip", True)),
                       "retreat_before_boss": _bool(params.get(
                           "retreat_before_boss",
                           saved_sortie.get("retreat_before_boss", False))),
                       "rotate_captain": _bool(saved_sortie.get("rotate_captain", False)),
                       "rotate_captain_margin": _i(
                           saved_sortie, "rotate_captain_margin", 10)}
    elif mode == "osaka":
        # 楼层、部队和圈数由日课决定；阵形、伤势与刀装恢复沿用独立大阪城配置。
        saved_osaka = (_load_panel_settings().get("params", {}).get("osaka", {}) or {})
        sortie_plan = {"mode": "osaka",
                       "team_no": _i(params, "team_no", 3),
                       "loops": _i(params, "osaka_runs", 1),
                       "select_floor": _bool(params.get("osaka_select_floor", False)),
                       "target_floor": _i(params, "osaka_target_floor", 81),
                       "formation_mode": saved_osaka.get("formation_mode") or "manual",
                       "formation": saved_osaka.get("formation") or "鱼鳞阵",
                       "repair_threshold": saved_osaka.get("repair_threshold") or "light",
                       "repair_on_injury": saved_osaka.get("repair_on_injury") or "continue",
                       "auto_equip": _bool(saved_osaka.get("auto_equip", True))}
    else:
        sortie_plan = {"mode": "none"}
    # 一键日课的演练完整沿用「演练」配置页，避免两处配置互相打架。
    saved_practice = (_load_panel_settings().get("params", {}).get("practice", {}) or {})
    practice_plan = dict(saved_practice)
    if practice_plan.get("team_no") not in (None, ""):
        practice_plan["team_no"] = int(practice_plan["team_no"])
    # 日课里的“远征”沿用独立远征页的常用安排；自动排班是另一套配置，绝不混用。
    from .scheduler import find_map, load_config
    expedition_plan = []
    for row in load_config().get("common_plan", []):
        if not row.get("enabled") or not row.get("map_code"):
            continue
        found = find_map(row["map_code"])
        expedition_plan.append({
            "team_no": int(row["team_no"]), "map_code": row["map_code"],
            "era": found.get("era") if found else None,
            "map_slot": found.get("slot") if found else None,
            "map_name": found.get("name") if found else None,
        })
    yield from agent.daily_stream(
        only=steps, after=after, sortie_override=sortie_plan,
        practice_override=practice_plan or None,
        expedition_override=expedition_plan)


def _build_daily_standalone(config_path, params):
    """一键日课独立入口：不套 run 级开工/收工盘点（_wrap_inventory）。

    盘点时机由 daily_stream 自己管：登录落本丸后拍 before、⑫ 步骤拍 after。
    之前套 wrapper 时，开工盘点在打开游戏/登录之前就触发，游戏没开只能
    盲点模拟器桌面，把冷启动登录搞挂。

    但统一收尾约定（回本丸 + 强制 peek）仍然要在整个日课 run 结束时执行
    一次，与 inventory 开关无关；收尾失败不拖垮任务结果。
    """
    agent = _make_agent(config_path)
    try:
        yield from _build_daily(agent, config_path, params)
    finally:
        # --- 统一收尾：回本丸 + 强制顶栏 peek ---
        try:
            yield "[日课] 收尾：导航回本丸"
            for nav_msg in agent.navigate_to_stream("本丸"):
                yield nav_msg
            if getattr(agent, "current_location", None) == "本丸":
                yield "[日课] 收尾：已回本丸，强制拍一次顶栏"
                if hasattr(agent, "quick_peek"):
                    agent.quick_peek(tag="日课·收尾", force=True)
            else:
                yield ("[日课] ⚠️ 收尾没能回到本丸，可能卡在某个界面了，"
                       "去看看")
        except Exception as exc:
            yield f"[日课] ⚠️ 收尾导航/Peek 失败（不影响任务结果）：{exc}"


def _build_raid(agent, config_path, params):
    runs = _run_count(params, 3, "rounds")
    yield from agent.raid_stream(
        max_rounds=runs,
        team_no=_i(params, "team_no", 3),
        difficulty_no=_i(params, "map_no", 4),
        auto_buy_ticket=_bool(params.get("auto_refill", False)),
        max_buys=runs)


def _build_pumpkin(agent, config_path, params):
    difficulty = _i(params, "difficulty", 0)
    watch = _sword_names(params.get("watch"))
    runs = _run_count(params, 4, "max_skips")
    yield from agent.pumpkin_stream(
        team_no=_i(params, "team_no", 3),
        difficulty=difficulty or None,
        watch_names=watch or None,
        max_skips=runs,
        # 南瓜新版的更新令牌购买确认后不会刷新数量、也不会自动关闭弹窗。
        # 前端先保留占位，流程端始终禁用，避免误消费小判后卡死。
        auto_refill=False)


def _build_edocastle(agent, config_path, params):
    runs = _run_count(params, 0, "max_runs")
    yield from agent.edocastle_stream(
        team_no=_i(params, "team_no", 3),
        use_koban_refill=_bool(params.get("use_koban_refill", False)),
        max_runs=runs,
        formation_mode=params.get("formation_mode") or "manual",
        formation=params.get("formation") or "鱼鳞阵")


def _build_sortie(agent, config_path, params):
    yield from agent.sortie_stream(
        chapter=_i(params, "chapter", 1),
        map_no=_i(params, "map_no", 1),
        team_no=_i(params, "team_no", 3),
        auto_march=_bool(params.get("auto_march", True)),
        max_loops=_run_count(params, 1, "loops"),
        formation_mode=params.get("formation_mode") or "manual",
        formation=params.get("formation") or "鱼鳞阵",
        repair_threshold=params.get("repair_threshold") or "light",
        injury_action=params.get("repair_on_injury") or "continue",
        auto_equip=_bool(params.get("auto_equip", True)),
        retreat_before_boss=_bool(params.get("retreat_before_boss", False)),
        rotate_captain=_bool(params.get("rotate_captain", False)),
        rotate_captain_margin=_i(params, "rotate_captain_margin", 10))


def _build_yosari(agent, config_path, params):
    yield from agent.yosari_stream(
        map_no=_i(params, "map_no", 1),
        team_no=_i(params, "team_no", 3),
        auto_march=_bool(params.get("auto_march", True)),
        auto_refill=_bool(params.get("auto_refill", False)),
        max_loops=_run_count(params, 1, "loops"),
        formation_mode=params.get("formation_mode") or "manual",
        formation=params.get("formation") or "鱼鳞阵",
        repair_threshold=params.get("repair_threshold") or "light",
        injury_action=params.get("repair_on_injury") or "continue",
        auto_equip=_bool(params.get("auto_equip", True)),
        rotate_captain=_bool(params.get("rotate_captain", False)),
        rotate_captain_margin=_i(params, "rotate_captain_margin", 10))


def _build_osaka(agent, config_path, params):
    # 小判掉落率实验由 osaka_stream 自带记账（开关沿用面板 compare_resources）
    yield from agent.osaka_stream(
        max_floors=_run_count(params, 1, "floors"),
        team_no=_i(params, "team_no", 3),
        select_floor=_bool(params.get("select_floor", False)),
        target_floor=_i(params, "target_floor", 81),
        formation_mode=params.get("formation_mode") or "manual",
        formation=params.get("formation") or "鱼鳞阵",
        repair_threshold=params.get("repair_threshold") or "light",
        injury_action=params.get("repair_on_injury") or "continue",
        auto_equip=_bool(params.get("auto_equip", True)),
        koban_science=_bool(params.get("compare_resources", True)))


def _build_sakura(agent, config_path, params):
    yield from agent.sakura_stream(
        team_no=_i(params, "team_no", 1),
        slot=_i(params, "slot", 1))


def _build_forge(agent, config_path, params):
    watch_raw = params.get("watch") or ""
    if isinstance(watch_raw, list):
        # Agent 网关传的是数组 ["03:20:00", ...]
        watch = [str(w).strip() for w in watch_raw if str(w).strip()]
    else:
        # 面板传的是字符串 "03:20:00, 04:00:00"
        watch = [w.strip() for w in re.split(r"[，,、;；\s]+", str(watch_raw)) if w.strip()]
    yield from agent.forge_stream(
        times=_i(params, "times", 3), watch=watch)


def _build_repair(agent, config_path, params):
    team_names = {f"部队{i}": i for i in range(1, 6)}
    raw_teams = params.get("speedup_teams")
    speedup_teams = None
    if isinstance(raw_teams, list):
        speedup_teams = [team_names[x] for x in raw_teams if x in team_names]
    yield from agent.repair_stream(
        dry_run=_bool(params.get("dry_run", False)),
        speedup_teams=speedup_teams)


def _build_dispatch(agent, config_path, params):
    """排班派遣：刷新结算；临近归来最多等十分钟；绝不启动模拟器。"""
    from .scheduler import find_map
    code = params.get("map_code") or ""
    team_no = _i(params, "team_no", 2)
    m = find_map(code)
    if not m:
        yield f"[远征] 不知道图 {code} 是哪张，没派"
        return
    records = _read_expedition_records()
    remain = _expedition_remaining(records.get(str(team_no), {}))
    if remain > 600:
        yield f"[远征] 部队{team_no}还剩 {remain // 60} 分钟，超过十分钟，本次跳过"
        return
    while remain > 0:
        yield f"[远征等待] 部队{team_no}还剩 {remain // 60:02d}:{remain % 60:02d}（紧急停止可取消）"
        time.sleep(min(5, remain))
        remain = _expedition_remaining(_read_expedition_records().get(str(team_no), {}))
    yield from agent.collect_expedition_stream(redispatch=None)
    yield from agent.expedition_stream(
        era=m["era"], map_slot=m["slot"],
        team_no=team_no)


def _expedition_remaining(record: dict) -> int:
    """派遣记录剩余秒数；过期或读不懂按 0。"""
    try:
        started = time.mktime(time.strptime(
            record["dispatched_at"], "%Y-%m-%d %H:%M:%S"))
        return max(0, int(started + int(record["duration_min"]) * 60 - time.time()))
    except Exception:
        return 0


def _read_expedition_records() -> dict:
    path = STATUS_DIR / "expeditions.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_expedition_manager(agent, config_path, params):
    """收取归来队伍，最多等十分钟，再按“常用安排”派遣。"""
    from .scheduler import find_map, load_config

    plan = [p for p in load_config().get("common_plan", [])
            if p.get("enabled") and p.get("map_code")]
    if not plan:
        yield "[远征管理] 没有启用任何常用安排，先去配置页勾选部队"
        return

    yield "[远征管理] 先回本丸刷新归来状态并领取结算"
    yield from agent.collect_expedition_stream(redispatch=None)

    records = _read_expedition_records()
    waitable = []
    skipped = set()
    for row in plan:
        team = str(row["team_no"])
        remain = _expedition_remaining(records.get(team, {})) if team in records else 0
        if 0 < remain <= 600:
            waitable.append((team, remain))
            yield f"[远征管理] 部队{team}还剩 {remain // 60}分{remain % 60:02d}秒，进入等待"
        elif remain > 600:
            skipped.add(team)
            yield (f"[远征管理] 部队{team}还剩 {remain // 60}分{remain % 60:02d}秒，"
                   "超过十分钟，本次跳过")
        else:
            yield f"[远征管理] 部队{team}已归来或空闲，可以派遣"

    if waitable:
        deadline = time.time() + max(remain for _, remain in waitable)
        while time.time() < deadline:
            left_lines = []
            for team, original in waitable:
                left = max(0, int(deadline - time.time()
                                 - (max(r for _, r in waitable) - original)))
                left_lines.append(f"部队{team} {left // 60:02d}:{left % 60:02d}")
            yield "[远征等待] " + " · ".join(left_lines) + "（紧急停止可取消）"
            time.sleep(min(5, max(0.2, deadline - time.time())))
        yield "[远征管理] 等待结束，再回本丸结算"
        yield from agent.collect_expedition_stream(redispatch=None)
        records = _read_expedition_records()

    for row in plan:
        team = str(row["team_no"])
        if team in skipped:
            continue
        remain = _expedition_remaining(records.get(team, {})) if team in records else 0
        if remain > 0:
            yield f"[远征管理] 部队{team}仍显示远征中，本次不碰"
            continue
        m = find_map(row["map_code"])
        if not m:
            yield f"[远征管理] 部队{team}的地图 {row['map_code']} 不存在，跳过"
            continue
        yield f"[远征管理] 派部队{team}去 {m['code']}「{m['name']}」"
        yield from agent.expedition_stream(
            era=m["era"], map_slot=m["slot"], team_no=int(team))

    yield "[远征管理] 常用安排处理完毕"


def _build_simple(stream_method_name):
    def _run(agent, config_path, params):
        method = getattr(agent, stream_method_name, None)
        if method is None:
            raise RuntimeError(f"Agent 没有 {stream_method_name} 方法")
        yield from method()
    return _run


register_script("daily", "一键日课", "",
                 _build_daily_standalone,
                 params=[{"key": "steps", "type": "checks", "label": "要干的活（不勾的不跑）",
                          "options": _DAILY_STEPS, "default": _DAILY_STEPS,
                           "help": "这里的出阵安排是日课专用配置，不会修改各玩法的单独配置。"},
                        {"key": "sortie_mode", "type": "select", "label": "出阵安排",
                         "options": [["none", "不出阵"],
                                     ["raid", "联队战"],
                                     ["pumpkin", "南瓜大作战"],
                                     ["yosari", "异去"],
                                     ["osaka", "大阪城挖地"],
                                     ["sortie", "合战场推图"]],
                         "default": "none",
                         "help": "自动行军、阵形和伤势处理沿用单独配置的战斗策略。"},
                        {"key": "team_no", "type": "select", "label": "出阵部队",
                         "options": _TEAM_OPTIONS, "default": "3",
                         "visibleWhen": {"key": "sortie_mode", "not": "none"}},
                        {"key": "raid_rounds", "type": "number", "label": "出阵次数",
                         "default": 3, "min": 1, "max": 99,
                         "visibleWhen": {"key": "sortie_mode", "is": "raid"}},
                        {"key": "raid_auto_refill", "type": "toggle",
                         "label": "是否自动补充手形？", "default": False,
                         "help": "开启后，手形不足时将自动使用小判补充，直到完成设定的出阵次数。关闭后，手形不足时结束任务，不消耗小判。",
                         "visibleWhen": {"key": "sortie_mode", "is": "raid"}},
                        {"key": "pumpkin_difficulty", "type": "select", "label": "难度",
                         "options": [["1", "低级"], ["2", "中级"], ["3", "高级"]],
                         "default": "1",
                         "visibleWhen": {"key": "sortie_mode", "is": "pumpkin"}},
                        {"key": "pumpkin_runs", "type": "number", "label": "出阵次数",
                         "default": 4, "min": 1, "max": 99,
                         "visibleWhen": {"key": "sortie_mode", "is": "pumpkin"}},
                        {"key": "yosari_map_no", "type": "select", "label": "小图",
                         "options": [[str(i), f"{i}图"] for i in range(1, 5)],
                         "default": "1",
                         "visibleWhen": {"key": "sortie_mode", "is": "yosari"}},
                        {"key": "yosari_runs", "type": "number", "label": "出阵次数",
                         "default": 1, "min": 1, "max": 99,
                         "visibleWhen": {"key": "sortie_mode", "is": "yosari"}},
                        {"key": "yosari_auto_refill", "type": "toggle",
                         "label": "是否自动补充手形？", "default": False,
                         "help": "开启后，手形不足时将自动使用小判补充，直到完成设定的出阵次数。关闭后，手形不足时结束任务，不消耗小判。",
                         "visibleWhen": {"key": "sortie_mode", "is": "yosari"}},
                        {"key": "osaka_runs", "type": "number", "label": "出阵次数",
                         "default": 1, "min": 1, "max": 99,
                         "visibleWhen": {"key": "sortie_mode", "is": "osaka"}},
                        {"key": "osaka_select_floor", "type": "toggle",
                         "label": "指定挂机层数", "default": False,
                         "visibleWhen": {"key": "sortie_mode", "is": "osaka"}},
                        {"key": "osaka_target_floor", "type": "number",
                         "label": "指定层数", "default": 81, "min": 1, "max": 99,
                         "help": "只有开启“指定挂机层数”时才会使用。",
                         "visibleWhen": {"key": "sortie_mode", "is": "osaka"}},
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
                        {"key": "retreat_before_boss", "type": "toggle",
                         "label": "王点前撤退", "default": False,
                         "help": "关闭自动行军后生效：下一步将进入王点时主动返回本丸，适合反复进图练级。小地图无法确认时会继续行军。",
                         "visibleWhen": {"key": "sortie_mode", "is": "sortie"}},
                        {"key": "after", "type": "select", "label": "跑完后（默认啥也不干）",
                         "options": [["none", "啥也不干"],
                                     ["logout", "退出游戏"],
                                     ["shutdown", "退出游戏 + 关模拟器"],
                                     ["sleep", "退出 + 关模拟器 + 电脑休眠"]],
                         "default": "none"}])
register_script("raid", "联队战", "",
                _wrap_inventory("RAID", _build_raid),
                params=[{"key": "map_no", "type": "select", "label": "打哪张图",
                         "options": [["1", "1图（坐标待补）"], ["2", "2图（坐标待补）"],
                                     ["3", "3图（坐标待补）"], ["4", "4图"]],
                         "default": "4"},
                        _team_field("3"),
                        _run_count_field(ticket=True, default=3),
                        _ticket_refill_field()])
register_script("pumpkin", "南瓜大作战", "刮刮乐刷剪影，能认出是哪把刀，不想要的自动烧令牌换板子",
                _wrap_inventory("南瓜", _build_pumpkin),
                params=[{"key": "difficulty", "type": "select", "label": "打哪张图",
                         "options": [["1", "低级"], ["2", "中级"], ["3", "高级"]],
                         "default": "1"},
                        _team_field("3"),
                        _run_count_field(ticket=True, default=4),
                        {**_ticket_refill_field(),
                         "help": "占位功能，当前暂不执行自动补充。新版南瓜的更新令牌购买后不会正确刷新并关闭弹窗，为避免误消费小判，令牌不足时脚本仍会安全结束。"}])
register_script("edocastle", "江户城潜入调查", "难度四巡游：踩点、钥匙、王点一套带走",
                _wrap_inventory("江户城", _build_edocastle),
                params=[_team_field("3"),
                        {"key": "max_runs", "type": "number", "label": "出阵次数",
                         "default": 0, "min": 0, "max": 99,
                         "help": "0 表示把当天通行令牌跑完为止。"},
                        {"key": "use_koban_refill", "type": "toggle",
                          "label": "是否补充手形", "default": False},
                        *_formation_fields()])
register_script("sortie", "合战场", "普通合战场：选择章节和小图出阵",
                _wrap_inventory("出阵", _build_sortie),
                params=[{"key": "chapter", "type": "select", "label": "章节",
                         "options": [[str(i), f"{i}章"] for i in range(1, 9)], "default": "1"},
                        {"key": "map_no", "type": "select", "label": "小图",
                         "options": [[str(i), f"{i}图"] for i in range(1, 5)], "default": "1"},
                        _team_field("3"),
                        _run_count_field(),
                        *_march_and_injury_fields(),
                        {"key": "retreat_before_boss", "type": "toggle",
                         "label": "王点前撤退", "default": False,
                         "help": "脚本手动行军时，看小地图算步数：距王点一步就主动返回本丸，反复进图练级。认不出地图时会照常行军，不会乱撤。需要安装 opencv。",
                         "visibleWhen": {"key": "auto_march", "is": "false"}}])
register_script("yosari", "异去", "",
                _wrap_inventory("异去", _build_yosari),
                params=[{"key": "chapter", "type": "select", "label": "章节",
                         "options": [["1", "1章"]], "default": "1",
                         "help": "异去目前只开放第一章；以后新增章节会在这里继续添加。"},
                        {"key": "map_no", "type": "select", "label": "小图",
                         "options": [[str(i), f"{i}图"] for i in range(1, 5)], "default": "1"},
                        _team_field("3"),
                        _run_count_field(ticket=True),
                        _ticket_refill_field(),
                        *_march_and_injury_fields(),
                        ])
register_script("osaka", "大阪城挖地", "逐层手动行军；没有自动行军，也不会消耗手形",
                _wrap_inventory("挖地", _build_osaka),
                params=[_team_field("3"),
                        {**_run_count_field(), "label": "出阵次数"},
                        {"key": "compare_resources", "type": "toggle",
                         "label": "小判掉落率实验", "default": True,
                         "help": "开工和收场时各读一次小判，差值和层数记进日志（测掉落概率用）；识别失败不影响挖地。"},
                        {"key": "select_floor", "type": "toggle",
                         "label": "指定挂机层数", "default": False},
                        {"key": "target_floor", "type": "number",
                         "label": "指定层数", "default": 81,
                         "min": 1, "max": 99,
                         "visibleWhen": {"key": "select_floor", "is": True}},
                        {"key": "formation_mode", "type": "select",
                         "label": "阵形选择方式",
                         "options": [["manual", "手动阵形"],
                                     ["auto", "自动阵形"]],
                         "default": "manual"},
                        {"key": "formation", "type": "select",
                         "label": "固定或识别失败时的兜底阵形",
                         "options": [[name, name] for name in
                                     ["鱼鳞阵", "横队阵", "雁行阵", "鹤翼阵", "方阵", "逆行阵"]],
                         "default": "鱼鳞阵"},
                        {"key": "repair_threshold", "type": "select",
                         "label": "伤势停止条件",
                         "options": [["light", "轻伤时停止"],
                                     ["medium", "中伤时停止"],
                                     ["heavy", "重伤时停止"]],
                         "default": "light"},
                        {"key": "repair_on_injury", "type": "select",
                         "label": "停止后的处理",
                         "options": [["continue", "手入加速后继续剩余层数"],
                                     ["repair_stop", "手入后停止任务"],
                                     ["stop", "返回本丸，不进行手入"]],
                         "default": "continue"},
                        {"key": "auto_equip", "type": "toggle",
                         "label": "是否自动补充刀装", "default": True,
                         "help": "任务首次出阵前保存到记录一；出现刀装未满提示时，自动用记录一补齐并重新检查伤势。"}])
register_script("sakura", "刷花", "队长单挑 1-1 刷疲劳到 100，满了自动换人",
                _wrap_inventory("刷花", _build_sakura),
                params=[_team_field("1"),
                        {"key": "slot", "type": "select", "label": "位置",
                         "options": [[str(i), f"{i}号位" + ("（队长）" if i == 1 else "")]
                                     for i in range(1, 7)], "default": "1"}])
def _build_practice(agent, config_path, params):
    # 面板单跑演练：真打 + 部队可选（_build_simple 裸调会掉进 dry_run 认人演习模式）
    return agent.practice_stream(
        dry_run=False,
        team_no=_i(params, "team_no", 2),
        formation_mode=params.get("formation_mode") or "manual",
        formation=params.get("formation") or "逆行阵")


register_script("practice", "演练", "",
                _wrap_inventory("演练", _build_practice),
                params=[
                    _team_field("2"),
                    {"key": "formation_mode", "type": "select",
                     "label": "阵形选择方式",
                     "options": [["manual", "手动选择"],
                                 ["auto", "自动阵形"]],
                     "default": "manual",
                     },
                    {"key": "formation", "type": "select",
                     "label": "固定或识别失败时的兜底阵形",
                     "options": [[name, name] for name in
                                 ["鱼鳞阵", "横队阵", "雁行阵",
                                  "鹤翼阵", "方阵", "逆行阵"]],
                     "default": "逆行阵"},
                ])
register_script("expedition", "远征", "收菜、等待临近归来，并按常用安排派遣",
                _wrap_inventory("远征管理", _build_expedition_manager))


def _map_select_field():
    from .scheduler import map_options
    opts = [[o["code"], f'{o["code"]} · {o["name"]}（{o["duration_text"]}）']
            for o in map_options()]
    return {"key": "map_code", "type": "select", "label": "远征图",
            "options": opts, "default": opts[0][0] if opts else ""}


register_script("dispatch", "派遣远征", "立刻派一支部队去指定远征图",
                _wrap_inventory("派遣", _build_dispatch),
                params=[_team_field("2"), _map_select_field()], hidden=True)
register_script("forge", "锻刀", "收完成的刀，再给空闲炉点火；不使用加速符",
                _wrap_inventory("锻刀", _build_forge),
                params=[{"key": "times", "type": "number", "label": "最多锻几炉",
                         "default": 3, "min": 1, "max": 12,
                         "help": "日课目标是锻刀 3 次，但脚本只使用当前空闲炉，绝不会消耗加速符。默认两炉的账号通常本次只能锻 2 次；没必要为了返还委托符强行加速。"},
                        {"key": "watch", "type": "duration-list",
                         "label": "目标时长（命中时手机报喜，不添加则不盯）",
                         "default": ""}])
register_script("repair", "手入", "单独扫描受伤刀剑；黑名单跳过，其余按部队决定是否加速",
                _wrap_inventory("手入", _build_repair),
                params=[{"key": "dry_run", "type": "select",
                         "label": "运行方式",
                         "options": [["false", "实际手入"],
                                     ["true", "只扫描并报告（不点击）"]],
                         "default": "false",
                         "help": "只扫描会报告每把刀的处理方式，不会点击任何按钮。"},
                        {"key": "speedup_teams", "type": "checks",
                         "label": "单独手入时，使用加速符的部队",
                         "options": ["部队一", "部队二", "部队三", "部队四", "部队五"],
                         "default": ["部队三"],
                         "help": "这里只影响单独运行“手入”：黑名单始终跳过，选中部队即时修好，其他队只安排普通手入。连续出阵选择“自动手入后继续”时，会自动加速当前出阵队，不读取这里。"}],
                hidden=True)
register_script("sugar", "炼糖", "收件箱清狗粮 + 习合循环",
                _wrap_inventory("炼糖", _build_simple("sugar_stream")))
register_script("inbox_supplies", "收杂物箱",
                "收件箱只收资源/货币/便利道具/其他物品，刀剑邮件原样躺着",
                _wrap_inventory("收杂物", _build_simple("inbox_supplies_stream"),
                                inventory=True))  # 收的都是资源，收完必拍家底
register_script("snapshot", "库存快照",
                "手动拍一次完整家底（含小判）刷新看板；日常已由锻刀收工顺手拍+顶栏顺路更新覆盖，想立刻刷新看板才用",
                _wrap_inventory("库存", _build_simple("status_snapshot_stream"),
                                inventory=False))


# ── 服务端启动 ──

@app.on_event("startup")
async def startup():
    try:
        await _startup()
    except BaseException:
        # Uvicorn turns lifespan exceptions into SystemExit(3).  Persist the
        # original traceback first so the launcher can show a useful cause.
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            (LOG_DIR / "launcher.log").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
        except OSError:
            pass
        raise


async def _startup():
    if _ledger_mode():
        # 账房模式必须能在模拟器、ADB、MAA 全都没开的情况下独立使用。
        # 广播、远征调度和机器人都可能间接触发自动化或额外网络连接，
        # 因此这里不初始化；账本、规划与手动录入 API 仍照常可用。
        return

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

    # Bot 启动（配了 panel_config.json 才启；QQ/TG 各自独立开关）
    from .bot_qq import init_qq
    _qq_sender = init_qq(app, _get_gateway)

    from .bot_telegram import start_bot as _start_bot
    # Disabled bots must not initialize the optional AI/http client.  Besides
    # doing unnecessary work, a damaged AI config used to prevent the entire
    # local panel from starting.
    try:
        bot_cfg = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8")).get("bot", {})
    except (OSError, json.JSONDecodeError):
        bot_cfg = {}
    needs_gateway = bot_cfg.get("enabled", False) and bot_cfg.get("platform", "").lower() == "telegram"
    _bot_instance = _start_bot(_get_gateway() if needs_gateway else None)

    # 事件播报器：挂上 QQ 出口（没配 QQ 也能跑，只发 ntfy）
    from .broadcaster import init_broadcaster
    init_broadcaster(qq_sender=_qq_sender)

    # 暴露给 API 路由用：机器人控制
    import __main__ as _bm
    _bm._bot_instance = _bot_instance


# ── 静态文件 ──

@app.get("/")
async def index():
    built = _STATIC / "vue" / "index.html"
    if built.exists():
        return FileResponse(str(built))
    # 开发环境尚未构建新版时仍可进入旧面板，不让启动器直接白屏。
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/legacy")
async def legacy_index():
    """迁移后的临时回退入口；确认新版长期稳定后再移除。"""
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/next")
async def next_index():
    """兼容迁移期间使用的预览地址。"""
    built = _STATIC / "vue" / "index.html"
    if not built.exists():
        return JSONResponse(
            {"ok": False, "error": "新版面板尚未构建，请先运行前端构建。"},
            status_code=503,
        )
    return FileResponse(str(built))


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


@app.get("/api/diagnostics/export")
def export_diagnostics():
    """Download a sanitized text-only bundle suitable for a public issue."""
    bundle = build_diagnostic_bundle()
    return Response(
        content=bundle.content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle.filename}"'},
    )


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


@app.get("/api/app-mode")
async def api_app_mode():
    return {
        "mode": "ledger" if _ledger_mode() else "automation",
        "automation_enabled": not _ledger_mode(),
    }

# 概览页常用功能的活动联动隐藏名单：/api/scripts 每 2 秒被轮询一次，
# 名单本身按分钟级缓存，别每趟都去读卡片和日历文件。
_event_hidden_cache = {"ts": 0.0, "value": []}


def _event_hidden_scripts() -> list[str]:
    if time.time() - _event_hidden_cache["ts"] < 60:
        return _event_hidden_cache["value"]
    from touken import advisor, event_timeline
    calendar, _ = _load_events_calendar()
    value = event_timeline.hidden_event_scripts(
        advisor.load_event_cards(STATUS_DIR),
        calendar.get("announcements", []))
    _event_hidden_cache.update(ts=time.time(), value=value)
    return value


@app.get("/api/scripts")
async def api_scripts():
    if _ledger_mode():
        return {
            "scripts": {},
            "running": False,
            "current": None,
            "event_hidden": [],
        }
    runner = get_runner()
    return {
        "scripts": list_scripts(),
        "running": runner.is_running,
        "current": runner.current_script,
        # 概览页「常用功能」联动：绑活动的脚本没开放就先收起来（配置页不受影响）
        "event_hidden": _event_hidden_scripts(),
    }


@app.post("/api/scripts/run")
async def api_run_script(request: Request):
    if _ledger_mode():
        return JSONResponse(
            {"ok": False, "reason": "纯净账房模式不连接游戏"},
            status_code=403,
        )
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


# ── API：刀剑名册（供前端名单选择器）──

@app.get("/api/swords")
async def api_swords():
    """返回全部刀剑的名称与刀种，用于候选列表分类"""
    from touken import sword_db
    swords = sword_db.all_swords()
    return {
        "swords": [
            {
                "id": sid,
                "name": info["name"],
                "name_zh": info.get("name_zh", ""),
                "type": info.get("type", "其他"),
            }
            for sid, info in swords.items()
        ]
    }


# ── API：全局名单配置（手入黑名单 / 刀解白名单）──

@app.get("/api/config-lists")
async def api_get_config_lists():
    """读取当前游戏配置里的名单"""
    cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        "repair_blacklist": cfg.get("repair", {}).get("blacklist", []),
        "dismantle_whitelist": cfg.get("dismantle", {}).get("whitelist", _DISMANTLE_WHITELIST),
    }


@app.post("/api/config-lists")
async def api_save_config_lists(request: Request):
    """把名单写回 touken_config.json（只改名单，不动别的）"""
    body = await request.json()
    cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    if "repair_blacklist" in body:
        cfg.setdefault("repair", {})["blacklist"] = [
            str(x).strip() for x in body["repair_blacklist"] if str(x).strip()
        ]
    if "dismantle_whitelist" in body:
        cfg.setdefault("dismantle", {})["whitelist"] = [
            str(x).strip() for x in body["dismantle_whitelist"] if str(x).strip()
        ]
    _CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


# ── API：聊天（已并轨 Agent 网关，面板聊天也能调脚本）──

_agent_gateway = None


def _get_gateway():
    """Agent 网关单例。chat-config 保存后置 None 重建，新配置即生效"""
    global _agent_gateway
    if _agent_gateway is None:
        from .agent import AgentGateway
        _agent_gateway = AgentGateway(str(_PANEL_CONFIG))
    return _agent_gateway


@app.get("/api/chat/history")
async def api_chat_history():
    store = get_store()
    return {"history": store.get_chat_history()}


# sync 的 LLM 调用走线程池，别卡事件循环（SSE 心跳全靠它）
from starlette.concurrency import run_in_threadpool as _run_io


@app.post("/api/chat")
async def api_chat(request: Request):
    """面板「近侍」tab：已并轨 Agent 网关——聊天归聊天，说干活就真去干活"""
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"reply": "（狐之助歪了歪头：主君，你说什么？）"})

    store = get_store()
    store.add_chat("user", message)
    try:
        reply = await _run_io(_get_gateway().process, message, "web")
    except Exception as exc:
        reply = f"（狐之助耳朵耷拉下来：主君…我脑子冒烟了 — {exc}）"
    store.add_chat("assistant", reply)   # 历史展示照旧走 log_store
    return {"reply": reply}


# ── API：Agent 网关（跨渠道 LLM 入口）──

@app.post("/api/agent")
async def api_agent(request: Request):
    """
    Agent 网关入口：接收任意渠道的消息，LLM 理解意图，调用工具。

    Body: {"message": "...", "channel": "qq"}
    Returns: {"reply": "...", "tool_called": true/false}
    """
    body = await request.json()
    message = body.get("message", "").strip()
    channel = body.get("channel", "qq")
    if not message:
        return {"reply": "（狐之助歪了歪头：你说什么？）", "tool_called": False}

    try:
        reply = await _run_io(_get_gateway().process, message, channel)
        return {"reply": reply, "tool_called": True}
    except Exception as exc:
        return {"reply": f"（狐之助耳朵耷拉下来：脑子冒烟了 — {exc}）", "tool_called": False}


# ── API：远征时刻表 ──

@app.get("/api/expedition-schedule")
async def api_get_schedule():
    from .scheduler import load_config, map_options, preset_payload
    cfg = load_config()
    return {**cfg, "maps": map_options(), "presets": preset_payload()}


@app.post("/api/expedition-schedule")
async def api_save_schedule(request: Request):
    from .scheduler import load_config, save_config
    body = await request.json()
    cfg = load_config()
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
    common = []
    for row in body.get("common_plan", []):
        try:
            team = int(row.get("team_no"))
        except Exception:
            continue
        if team not in range(1, 6):
            continue
        common.append({
            "team_no": team,
            "map_code": str(row.get("map_code", "")),
            "enabled": bool(row.get("enabled", False)),
        })
    auto_in = body.get("automation", {})
    auto = cfg.get("automation", {})
    auto.update({
        "enabled": bool(auto_in.get("enabled", False)),
        "mode": auto_in.get("mode") if auto_in.get("mode") in ("preset", "custom") else "preset",
        "preset": str(auto_in.get("preset", "小判")),
        "start_time": str(auto_in.get("start_time", "08:00"))[:5],
        "teams": [int(x) for x in auto_in.get("teams", [2, 3, 4])][:3],
        "capitalist": bool(auto_in.get("capitalist", False)),
        "paused_until": str(auto_in.get("paused_until", auto.get("paused_until", ""))),
    })
    cfg.update({"entries": clean, "common_plan": common, "automation": auto})
    save_config(cfg)
    return {"ok": True, "count": len(clean)}


@app.post("/api/expedition-pause")
async def api_pause_expedition(request: Request):
    from .scheduler import load_config, save_config
    body = await request.json()
    minutes = int(body.get("minutes", 0))
    cfg = load_config()
    if minutes <= 0:
        until = ""
    elif minutes >= 999:
        until = time.strftime("%Y-%m-%d") + " 23:59:59"
    else:
        until = time.strftime("%Y-%m-%d %H:%M:%S",
                              time.localtime(time.time() + minutes * 60))
    cfg["automation"]["paused_until"] = until
    save_config(cfg)
    return {"ok": True, "paused_until": until}


# ── API：状态 ──

@app.get("/api/status")
async def api_status():
    """读取最新的日课成绩单和库存"""
    status_dir = STATUS_DIR
    data = {}
    for fn in ("latest_report.json", "inventory.json"):
        fp = status_dir / fn
        if fp.exists():
            data[fn.replace(".json", "")] = json.loads(fp.read_text(encoding="utf-8"))
    return data


# ── API：仪表盘（总览首页聚合数据）──

# 运行中横幅文案：优先按「进度步骤」细分，其次按脚本名兜底
_STEP_FLAVOR = {
    "raid:lulian": "正在和时间溯行军搏斗中⚔️",
    "raid:hailian": "正在拿水枪喷死对面🔫",
    "daily:内番": "正在安排苦力干活💦",
    "daily:远征": "正在流放刀剑男士⛺",
    "daily:出阵": "正在和时间溯行军搏斗中⚔️",
    "daily:演练": "正在演练场挑软柿子捏🥊",
    "daily:锻刀": "正在盯炉火🔥",
    "daily:刀解": "正在拆快递🗡",
    "daily:合成": "正在喂刀🍡",
    "daily:签到": "正在打卡签到📅",
    "daily:万屋": "正在万屋蹭免费鸡蛋🥚",
    "daily:任务奖励": "正在收日课工资💰",
    "daily:库存快照": "正在盘点家底📦",
}

_SCRIPT_FLAVOR = {
    "daily": "正在爆肝日课📋",
    "raid": "正在和时间溯行军搏斗中⚔️",
    "pumpkin": "正在南瓜田里刨剪影🎃",
    "edocastle": "正在江户城摸黑巡游🏯",
    "sortie": "正在出阵打图🗡",
    "yosari": "正在提灯照耀的异去探索🏮",
    "osaka": "正在大阪城地下咔咔挖土⛏️",
    "sakura": "正在给刀剑男士刷樱花🌸",
    "practice": "正在演练场挑软柿子捏🥊",
    "expedition": "正在流放刀剑男士⛺",
    "dispatch": "正在流放刀剑男士⛺",
    "forge": "正在盯炉火🔥",
    "sugar": "正在炼糖🍬",
    "inbox_supplies": "正在收件箱翻杂物📮",
    "snapshot": "正在盘点家底📦",
}


def _flavor_text(script: str | None, step: str) -> str:
    if step in _STEP_FLAVOR:
        return _STEP_FLAVOR[step]
    return _SCRIPT_FLAVOR.get(script or "", "正在本丸干活🔧")


def _dashboard_inventory(inventory: dict | None, now: float) -> dict | None:
    """把库存快照里的炉子剩余时间换算成看板此刻的秒数。"""
    if not inventory:
        return inventory
    result = dict(inventory)
    try:
        captured = time.mktime(time.strptime(
            str(inventory.get("captured_at", "")), "%Y-%m-%d %H:%M:%S"))
        age = max(0, now - captured)
    except Exception:
        age = 0
    furnaces = []
    for raw in inventory.get("furnaces", []):
        furnace = dict(raw)
        remain = furnace.get("remain")
        match = re.fullmatch(r"(\d{1,2}):([0-5]\d):([0-5]\d)", str(remain or ""))
        if furnace.get("state") == "锻造中" and match:
            seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
            furnace["remain_sec"] = max(0, int(seconds - age))
        else:
            furnace["remain_sec"] = None
        furnaces.append(furnace)
    result["furnaces"] = furnaces
    return result


def _dashboard_expeditions(raw_exp: dict, now: float,
                           overdue_grace_sec: int = 6 * 3600) -> list[dict]:
    """整理远征记录；已到点太久的旧记录不再永久占着看板。"""
    expeditions = []
    for team_no, raw in raw_exp.items():
        item = dict(raw)
        item["team_no"] = team_no
        try:
            dispatched = time.mktime(time.strptime(
                raw["dispatched_at"], "%Y-%m-%d %H:%M:%S"))
            remain = dispatched + float(raw.get("duration_min", 0)) * 60 - now
            if remain < -overdue_grace_sec:
                continue
            item["remain_sec"] = max(0, int(remain))
            item["done"] = remain <= 0
        except Exception:
            item["remain_sec"] = None
            item["done"] = False
        expeditions.append(item)
    return sorted(expeditions, key=lambda item: item.get("remain_sec") or 0)


@app.get("/api/dashboard")
async def api_dashboard():
    """首页仪表盘：家底 + 远征倒计时 + 日课成绩单 + 内番，一次拿全"""
    status_dir = STATUS_DIR

    def _read(fn):
        fp = status_dir / fn
        if fp.exists():
            try:
                return json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    now = time.time()
    data = {
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "inventory": _dashboard_inventory(_read("inventory.json"), now),
        "latest_report": _read("latest_report.json"),
        "naihanka": _read("naihanka.json"),
    }

    # 远征：给每条算好剩余秒数，前端只管倒计时
    raw_exp = _read("expeditions.json") or {}
    data["expeditions"] = _dashboard_expeditions(raw_exp, now)

    # 远征时刻表：今天还没派的安排（前端显示用）
    try:
        from .scheduler import load_entries
        today = time.strftime("%Y-%m-%d")
        data["schedule"] = [
            e for e in load_entries()
            if e.get("enabled") and e.get("last_fired") != today
        ]
    except Exception:
        data["schedule"] = []

    # 运行中横幅：当前脚本 + 最新进度步骤 → 狐之助文案
    runner = get_runner()
    active = runner.is_running
    script = runner.current_script if active else None
    started = runner.current_started
    progress = _read("progress.json") or {}
    step = progress.get("step", "")

    # 面板起跑的新任务：进度文件的时间戳比任务启动还早 = 上一轮留下的陈年老步，
    # 作废（不然联队战刚点开还没上报，会顶着上次日课的「远征」文案到处跑）
    if active and script != "external" and started and progress.get("at"):
        try:
            if time.mktime(time.strptime(progress["at"], "%Y-%m-%d %H:%M:%S")) < started:
                step = ""
        except Exception:
            pass

    # 定时任务/命令行跑引擎时不走面板 runner，但会写 progress.json：
    # 3 分钟内更新过就算「在跑」，横幅照样营业
    # runner.current_script 有值但线程已结束，说明这是刚跑完的面板任务；
    # 此时 progress.json 仍然很新，不能反过来把它误判成外部任务继续展示。
    if not active and runner.current_script is None and step and progress.get("at"):
        try:
            age = time.time() - time.mktime(time.strptime(progress["at"], "%Y-%m-%d %H:%M:%S"))
            if 0 <= age <= 180:
                active = True
                script = "external"
                started = time.time() - age
        except Exception:
            pass
    if not active:
        step = ""

    label = ""
    if script == "external":
        label = "定时/命令行任务"
    elif script:
        label = list_scripts().get(script, {}).get("label", script)
    data["running"] = {
        "active": active,
        "script": script,
        "label": label,
        "started": started,
        "step": step,
        "flavor": _flavor_text(script, step),
    }

    return data


# ── API：聊天 AI 配置（设置弹窗真正落盘 + 热重载，不用重启）──

def _mask(value: str) -> str:
    """敏感字符串脱敏：头 4 位 + … + 尾 4 位。空值/短值原样返回"""
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return value[:4] + "…" + value[-4:]


def _bool(v) -> bool:
    return v in (True, "true", "on", "yes", 1, "1")


def _int_list(v) -> list:
    if not v:
        return []
    if isinstance(v, list):
        return [int(x) for x in v if str(x).strip().lstrip("-").isdigit()]
    return [int(x.strip()) for x in str(v).replace("，", ",").split(",") if x.strip().lstrip("-").isdigit()]


@app.get("/api/bot-config")
async def api_get_bot_config():
    """读取 bot 配置，token 全程脱敏。"""
    cfg = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8"))
    bot = cfg.get("bot", {})
    tg = bot.get("telegram", {})
    qq = bot.get("qq", {})
    bc = bot.get("broadcast", {})
    return {
        "enabled": bool(bot.get("enabled", False)),
        "platform": bot.get("platform", "telegram"),
        "telegram": {
            "token_masked": _mask(tg.get("token", "")),
            "has_token": bool(tg.get("token", "")),
            "allowed_users": list(tg.get("allowed_users", []) or []),
        },
        "qq": {
            "enabled": bool(qq.get("enabled", False)),
            "provider": qq.get("provider", "napcat"),
            "snowluma_http": qq.get("snowluma_http", "http://127.0.0.1:3000"),
            "snowluma_gui_http": qq.get("snowluma_gui_http", "http://127.0.0.1:5099"),
            "admin_qq": list(qq.get("admin_qq", []) or []),
        },
        "broadcast": {
            "qq": bool(bc.get("qq", True)),
            "ntfy": bool(bc.get("ntfy", True)),
        },
        # 哪些改了能热生效，哪些得重启
        "hot_reloadable": {
            "telegram": True,
            "qq": False,   # QQ webhook 在启动时挂载，运行时不能安全卸载
        },
    }


@app.get("/api/qq-status")
async def api_qq_status():
    """探测 OneBot API 与管理页；只检测，不启动或下载任何程序。"""
    import httpx

    cfg = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8"))
    qq = cfg.get("bot", {}).get("qq", {})
    api_url = str(qq.get("snowluma_http", "http://127.0.0.1:3000")).rstrip("/")
    gui_url = str(qq.get("snowluma_gui_http", "http://127.0.0.1:5099")).rstrip("/")

    async def probe(url, suffix=""):
        if not url:
            return False, "未配置地址"
        try:
            async with httpx.AsyncClient(timeout=3, follow_redirects=True) as client:
                r = await client.get(url + suffix)
            return r.status_code < 500, f"HTTP {r.status_code}"
        except Exception as exc:
            name = type(exc).__name__.replace("Error", "")
            return False, name or "连接失败"

    api_ok, api_detail = await probe(api_url, "/get_status")
    gui_ok, gui_detail = await probe(gui_url)
    webhook_ready = any(getattr(route, "path", "") == "/onebot/webhook"
                        for route in app.routes)
    return {
        "enabled": bool(qq.get("enabled", False)),
        "provider": qq.get("provider", "napcat"),
        "api_url": api_url,
        "gui_url": gui_url,
        "api_online": api_ok,
        "api_detail": api_detail,
        "gui_online": gui_ok,
        "gui_detail": gui_detail,
        "webhook_ready": webhook_ready,
        "webhook_url": "http://127.0.0.1:8080/onebot/webhook",
        "state": "connected" if api_ok else "unavailable",
    }


@app.post("/api/bot-config")
async def api_save_bot_config(request: Request):
    """保存 bot 配置。
    - token 留空 = 不改（防止掩码被当新 key 写回去）
    - TG token 改了尝试热重启；QQ 改了下次面板启动才生效
    """
    body = await request.json()
    cfg = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8"))
    bot = cfg.setdefault("bot", {})

    if "enabled" in body:
        bot["enabled"] = _bool(body["enabled"])
    if body.get("platform") in ("telegram", "qq"):
        bot["platform"] = body["platform"]

    # Telegram
    tg = bot.setdefault("telegram", {})
    if "telegram" in body and isinstance(body["telegram"], dict):
        t = body["telegram"]
        # token 留空不动；非空就改
        if t.get("token"):
            tg["token"] = str(t["token"]).strip()
        tg["allowed_users"] = _int_list(t.get("allowed_users", tg.get("allowed_users", [])))

    # QQ
    qq_block = bot.setdefault("qq", {})
    if "qq" in body and isinstance(body["qq"], dict):
        q = body["qq"]
        qq_block["enabled"] = _bool(q.get("enabled"))
        if q.get("provider") in ("napcat", "snowluma", "custom"):
            qq_block["provider"] = q["provider"]
        if q.get("snowluma_http"):
            qq_block["snowluma_http"] = str(q["snowluma_http"]).strip()
        # SnowLuma 远程桌面 / GUI 端口：留空 = 不变，存了就更新
        if "snowluma_gui_http" in q and q.get("snowluma_gui_http") is not None:
            qq_block["snowluma_gui_http"] = str(q["snowluma_gui_http"]).strip()
        qq_block["admin_qq"] = _int_list(q.get("admin_qq", qq_block.get("admin_qq", [])))

    # Broadcast
    bc = bot.setdefault("broadcast", {})
    if "broadcast" in body and isinstance(body["broadcast"], dict):
        b = body["broadcast"]
        bc["qq"] = _bool(b.get("qq", bc.get("qq", True)))
        bc["ntfy"] = _bool(b.get("ntfy", bc.get("ntfy", True)))

    _PANEL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # 热重试 Telegram（QQ 提示用户重启面板）
    tg_reload_msg = ""
    if bot.get("platform") == "telegram" and bot.get("enabled"):
        try:
            import __main__ as _bm
            from .bot_telegram import stop_bot, start_bot
            stop_bot(getattr(_bm, "_bot_instance", None))
            _bm._bot_instance = start_bot(_get_gateway())
            tg_reload_msg = "Telegram 已热重启，新 token 立即生效。"
        except Exception as exc:
            tg_reload_msg = f"Telegram 热重启失败：{exc}"

    return {"ok": True, "tg_reload_msg": tg_reload_msg,
            "qq_restart_required": qq_block.get("enabled", False)}


# ── API：结构化运行数据 ──


@app.get("/api/data/summary")
async def api_data_summary(days: int = 30):
    """稳定机器数据总览；前端与智能建议共用，契约由 schema_version 标识。"""
    from touken.telemetry import get_telemetry_store
    data = get_telemetry_store().summary(days=days)

    def _state(name: str):
        path = STATUS_DIR / name
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, ValueError):
            return None

    data["current_state"] = {
        "inventory": _state("inventory.json"),
        "daily_report": _state("latest_report.json"),
        "expeditions": _state("expeditions.json") or {},
        "naihanka": _state("naihanka.json"),
    }
    return data


@app.get("/api/data/events")
async def api_data_events(limit: int = 100, event_type: str = "",
                          script: str = "", before_id: int | None = None,
                          from_ts: float | None = None,
                          to_ts: float | None = None):
    """结构化玩法事件；payload 只含机器字段，不依赖中文日志文案。"""
    from touken.telemetry import get_telemetry_store, TELEMETRY_SCHEMA_VERSION
    page_limit = max(1, min(int(limit), 1000))
    items = get_telemetry_store().recent_events(
        limit=page_limit + 1, event_type=event_type or None, script=script or None,
        before_id=before_id, from_ts=from_ts, to_ts=to_ts)
    has_more = len(items) > page_limit
    items = items[:page_limit]
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "items": items,
        "has_more": has_more,
        "next_cursor": items[-1]["id"] if items else None,
    }


@app.get("/api/data/runs")
async def api_data_runs(limit: int = 20, script: str = "",
                        before_started_at: float | None = None,
                        from_ts: float | None = None,
                        to_ts: float | None = None):
    """每轮任务的结构化结算；圈速按相邻完成事件计算，不含盘点时间。"""
    from touken.telemetry import get_telemetry_store, TELEMETRY_SCHEMA_VERSION
    page_limit = max(1, min(int(limit), 100))
    items = get_telemetry_store().recent_run_summaries(
        limit=page_limit + 1, script=script or None,
        before_started_at=before_started_at, from_ts=from_ts, to_ts=to_ts)
    has_more = len(items) > page_limit
    items = items[:page_limit]
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "items": items,
        "has_more": has_more,
        "next_cursor": items[-1]["started_at"] if items else None,
    }


@app.post("/api/data/runs/{run_id}/attach-inventory")
async def api_attach_run_inventory(run_id: str):
    """把用户刚手动盘点的库存补为指定任务的收工快照。"""
    inventory_path = STATUS_DIR / "inventory.json"
    try:
        snapshot = json.loads(inventory_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return JSONResponse(
            {"ok": False, "reason": "还没有库存快照，请先运行“库存快照”"}, status_code=400)
    except (OSError, ValueError):
        return JSONResponse(
            {"ok": False, "reason": "最近的库存快照无法读取，请重新盘点"}, status_code=400)
    captured_ts = inventory_path.stat().st_mtime
    captured_at = str(snapshot.get("captured_at") or "")
    try:
        captured_ts = time.mktime(time.strptime(captured_at, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        pass
    from touken.telemetry import get_telemetry_store
    try:
        summary = get_telemetry_store().attach_inventory_snapshot(
            run_id, snapshot, captured_ts=captured_ts)
    except ValueError as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    return {"ok": True, "run": summary}


@app.get("/api/data/resource-ledger")
async def api_data_resource_ledger(days: int = 7,
                                   from_ts: float | None = Query(None, alias="from"),
                                   to: float | None = None):
    """资源总账：窗口内八资源的观察链/归因/缺口，聚合全部在服务端完成。

    from/to（Unix 秒）优先于 days；days 默认 7。契约见 docs/telemetry-data.md。
    """
    from touken.telemetry import get_telemetry_store
    to_ts = float(to) if to else time.time()
    start = float(from_ts) if from_ts is not None \
        else to_ts - max(1, min(int(days), 365)) * 86400
    return get_telemetry_store().resource_ledger(start, to_ts)


@app.post("/api/data/manual-inventory")
async def api_add_manual_inventory(request: Request):
    """手动记家底：只把实际填写的资源作为当前时刻的库存观察。"""
    body = await request.json()
    from touken.telemetry import get_telemetry_store
    try:
        snapshot = get_telemetry_store().add_manual_inventory(
            body.get("resources") or {}, observed_at=body.get("observed_at"))
    except (TypeError, ValueError) as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    return {"ok": True, "snapshot": snapshot}


@app.get("/api/data/manual-sessions")
async def api_manual_sessions(limit: int = 200, from_ts: float | None = None,
                              to_ts: float | None = None):
    """审神者手动活动记录；与まあ丸 runs 分表、分接口返回。"""
    from touken.telemetry import get_telemetry_store, TELEMETRY_SCHEMA_VERSION
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "items": get_telemetry_store().manual_sessions(
            limit=limit, from_ts=from_ts, to_ts=to_ts),
    }


@app.post("/api/data/manual-sessions")
async def api_add_manual_session(request: Request):
    body = await request.json()
    from touken.telemetry import get_telemetry_store
    try:
        item = get_telemetry_store().add_manual_session(
            script=body.get("script"),
            started_at=float(body.get("started_at")),
            ended_at=float(body.get("ended_at")),
            loops=body.get("loops"), note=body.get("note", ""),
        )
    except (TypeError, ValueError) as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    return {"ok": True, "item": item}


@app.delete("/api/data/manual-sessions/{session_id}")
async def api_delete_manual_session(session_id: int):
    from touken.telemetry import get_telemetry_store
    if not get_telemetry_store().delete_manual_session(session_id):
        return JSONResponse(
            {"ok": False, "reason": "找不到这条手动活动记录"}, status_code=404)
    return {"ok": True}


@app.get("/api/data/human-reports")
async def api_human_reports(limit: int = 200):
    from touken.telemetry import get_telemetry_store, TELEMETRY_SCHEMA_VERSION
    store = get_telemetry_store()
    return {"schema_version": TELEMETRY_SCHEMA_VERSION,
            "items": store.human_reports(limit=limit),
            "inventory_gaps": store.inventory_gaps(limit=50)}


@app.post("/api/data/human-reports")
async def api_add_human_report(request: Request):
    body = await request.json()
    from touken.telemetry import get_telemetry_store
    try:
        item = get_telemetry_store().add_human_report(
            occurred_at=float(body.get("occurred_at") or time.time()),
            activities=body.get("activities") or [], note=body.get("note", ""),
            source=body.get("source", "proactive"), gap_key=body.get("gap_key"),
            resource=body.get("resource"), claimed_delta=body.get("claimed_delta"))
    except (TypeError, ValueError) as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    return {"ok": True, "item": item}


@app.delete("/api/data/human-reports/{report_id}")
async def api_delete_human_report(report_id: int):
    from touken.telemetry import get_telemetry_store
    if not get_telemetry_store().delete_human_report(report_id):
        return JSONResponse({"ok": False, "reason": "找不到这条审神者报备"}, status_code=404)
    return {"ok": True}


# ── API：规划建议（攒钱小目标） ──

# 活动日历源：腾讯云服务器上 scripts/bili_events_crawler.py 每天扒一次
# B 站官方号公告生成 events.json（部署见交接文档 §23）
EVENTS_CALENDAR_URL = "http://49.235.132.50:8321/events.json"
EVENTS_CACHE_TTL = 6 * 3600


def _load_events_calendar() -> tuple[dict, bool]:
    """读活动日历（先本地 6h 缓存，过期则拉服务器，拉不动用旧缓存）。
    返回 (数据, 是否陈旧的兜底)。"""
    import urllib.request
    cache_path = STATUS_DIR / "events_calendar.json"
    cached = None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if cached and time.time() - cached.get("fetched_at", 0) < EVENTS_CACHE_TTL:
        return cached["data"], False
    try:
        with urllib.request.urlopen(EVENTS_CALENDAR_URL, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        cache_path.write_text(json.dumps({"fetched_at": time.time(), "data": data},
                                         ensure_ascii=False), encoding="utf-8")
        return data, False
    except Exception:
        if cached:
            return cached["data"], True
        return {"announcements": []}, True


@app.get("/api/events")
async def api_events():
    """活动日历：拉服务器上的 events.json，带 6h 本地缓存；拉不动就用旧缓存。"""
    data, stale = _load_events_calendar()
    if not data.get("announcements") and stale:
        return {"announcements": [], "stale": True,
                "reason": "活动日历服务器暂时联系不上"}
    return {**data, "stale": stale}


@app.get("/api/events/timeline")
async def api_events_timeline():
    """事件时间轴：已核实活动按 进行中/7天内/更远 分组排序，
    公告时间候选沉底待确认。契约见 touken/event_timeline.py。"""
    from touken import advisor, event_timeline
    from touken.telemetry import get_telemetry_store
    planning = advisor.get_planning(get_telemetry_store(),
                                    STATUS_DIR / advisor.GOALS_FILENAME)
    calendar, stale = _load_events_calendar()
    timeline = event_timeline.build_timeline(
        advisor.load_event_cards(STATUS_DIR),
        planning.get("events", []),
        calendar.get("announcements", []))
    return {**timeline, "calendar_stale": stale}


@app.get("/api/planning")
async def api_planning():
    """攒钱目标 + 按近日净收支速率推算的到期预测。契约见 touken/advisor.py。"""
    from touken import advisor
    from touken.telemetry import get_telemetry_store
    return advisor.get_planning(get_telemetry_store(),
                                STATUS_DIR / advisor.GOALS_FILENAME)


@app.post("/api/planning/goals")
async def api_add_planning_goal(request: Request):
    body = await request.json()
    from touken import advisor
    try:
        goal = advisor.add_goal(STATUS_DIR / advisor.GOALS_FILENAME,
                                resource=str(body.get("resource") or ""),
                                target=body.get("target"),
                                deadline=str(body.get("deadline") or ""),
                                goal_mode=str(body.get("goal_mode") or "combined"),
                                note=str(body.get("note") or ""))
    except ValueError as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    return {"ok": True, "goal": goal}


@app.delete("/api/planning/goals/{goal_id}")
async def api_delete_planning_goal(goal_id: int):
    from touken import advisor
    if not advisor.delete_goal(STATUS_DIR / advisor.GOALS_FILENAME, goal_id):
        return JSONResponse({"ok": False, "reason": "找不到这个小目标"}, status_code=404)
    return {"ok": True}


@app.post("/api/planning/event-estimate")
async def api_save_event_estimate(request: Request):
    """保存用户手填的活动场均钥匙预估；实测数据来了自动盖过它。"""
    body = await request.json()
    from touken import advisor
    try:
        card = advisor.save_key_estimate(STATUS_DIR,
                                         str(body.get("event") or ""),
                                         body.get("keys_per_run"))
    except ValueError as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    return {"ok": True, "card": card}


@app.post("/api/planning/event-goals")
async def api_add_event_goal(request: Request):
    """把活动准备立成目标。预算和活动截止时间都由服务端知识卡决定。"""
    body = await request.json()
    from touken import advisor
    from touken.telemetry import get_telemetry_store
    try:
        result = advisor.add_event_goal(get_telemetry_store(),
                                        STATUS_DIR / advisor.GOALS_FILENAME,
                                        str(body.get("event") or ""),
                                        target=body.get("target"))
    except ValueError as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    return {"ok": True, **result}


@app.get("/api/data/ocr")
async def api_data_ocr(limit: int = 100, script: str = "",
                       matched: bool | None = None):
    """OCR 观测明细；供识别质量页面及后续建议引擎使用。"""
    from touken.telemetry import get_telemetry_store, TELEMETRY_SCHEMA_VERSION
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "items": get_telemetry_store().recent_observations(
            limit=limit, script=script or None, matched=matched),
    }


@app.get("/api/stats/ocr")
async def api_ocr_stats():
    """旧前端兼容入口；数据已改从结构化仓库读取，不再解析中文日志。"""
    try:
        from touken.telemetry import get_telemetry_store
        store = get_telemetry_store()
        summary = store.summary(days=7)
        sword_counts = {}
        for event in store.recent_events(
                limit=1000, event_type="pumpkin.sword_obtained"):
            if event["ts"] < summary["window"]["since"]:
                continue
            name = str(event["payload"].get("name", "")).strip()
            if name:
                sword_counts[name] = sword_counts.get(name, 0) + 1
        sword_ranks = sorted(sword_counts.items(), key=lambda x: -x[1])[:20]
        return {
            "sword_ranks": [{"name": n, "count": c} for n, c in sword_ranks],
            "script_counts": summary["runs"]["by_script"],
            "total_logs": summary["ocr"]["total"],
            "ok": True,
            "source": "telemetry-v1",
        }
    except Exception as exc:
        return {"sword_ranks": [], "script_counts": {}, "total_logs": 0,
                "ok": False, "error": str(exc)}


# ── API：聊天 AI 配置（设置弹窗真正落盘 + 热重载，不用重启）──

@app.get("/api/chat-config")
async def api_get_chat_config():
    cfg = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8"))
    ai = cfg.get("ai", {})
    key = ai.get("api_key", "")
    masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else ""
    from .chat_ai import KITSUNE_SYSTEM_PROMPT
    return {
        "has_key": bool(key) and key != "YOUR_OPENAI_API_KEY",
        "api_key_masked": masked,
        "base_url": ai.get("base_url", ""),
        "model": ai.get("model", ""),
        "system_prompt": ai.get("system_prompt", ""),
        "default_prompt": KITSUNE_SYSTEM_PROMPT,
    }


@app.post("/api/chat-config")
async def api_save_chat_config(request: Request):
    body = await request.json()
    cfg = json.loads(_PANEL_CONFIG.read_text(encoding="utf-8"))
    ai = cfg.setdefault("ai", {})
    # key 留空 = 不改（防止掩码被当成真 key 写回去）
    if body.get("api_key"):
        ai["api_key"] = str(body["api_key"]).strip()
    if body.get("base_url"):
        ai["base_url"] = str(body["base_url"]).strip()
    if body.get("model"):
        ai["model"] = str(body["model"]).strip()
    # 角色 prompt：空字符串 = 恢复默认狐之助（显式清空也合法，所以用 in 判断）
    if "system_prompt" in body:
        sp = str(body["system_prompt"]).strip()
        if sp:
            ai["system_prompt"] = sp
        else:
            ai.pop("system_prompt", None)
    _PANEL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    from .chat_ai import reload_ai
    reload_ai(str(_PANEL_CONFIG))  # 热重载，不用重启面板
    global _agent_gateway
    _agent_gateway = None            # Agent 网关也重建，新 key/模型/人设即生效
    return {"ok": True}


# ── API：保存/加载面板设置 ──

_SETTINGS_FILE = STATUS_DIR / "panel_settings.json"


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
    """保存面板设置到服务器端（合并式：脚本参数、主题各存各的，互不覆盖）"""
    body = await request.json()
    existing = _load_panel_settings()
    existing.pop("_saved_at", None)
    # body 格式: {"params": {"daily": {...}, ...}, "theme": "pixel"}
    params = body.get("params")
    if isinstance(params, dict):
        clean = {k: v for k, v in params.items() if isinstance(v, dict)}
        existing["params"] = clean
    if body.get("theme") in ("washi", "pixel"):
        existing["theme"] = body["theme"]
    _save_panel_settings(existing)
    return {"ok": True}


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
