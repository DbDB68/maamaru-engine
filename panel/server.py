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
from touken.runtime_paths import (
    BUNDLE_ROOT, CONFIG_PATH, PANEL_CONFIG_PATH, RESOURCE_DIR, STATUS_DIR,
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


# ── 各脚本 builder（签名统一：(config_path, params) -> generator）──

def _build_daily(config_path, params):
    # 面板传 steps，Agent 网关传 only，都认
    steps = params.get("steps") or params.get("only") or None   # 空列表=全跑
    after = params.get("after") or "none"
    # 出阵安排：面板选的覆盖配置文件里的默认
    mode = params.get("sortie_mode") or "none"
    if mode == "raid":
        sortie_plan = {"mode": "raid",
                       "rounds": _i(params, "raid_rounds", 3),
                       "team_no": _i(params, "team_no", 3),
                       "max_buys": _i(params, "raid_buys", 30)}
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
                       "formation_strategy": saved_sortie.get("formation_strategy") or "fixed",
                       "formation": saved_sortie.get("formation") or "鱼鳞阵",
                       "repair_threshold": saved_sortie.get("repair_threshold") or "light",
                       "repair_on_injury": saved_sortie.get("repair_on_injury") or "continue"}
    elif mode == "pumpkin":
        # 出阵走南瓜大作战：面板传的 watch 沿用 pumpkin 的解析逻辑
        watch_raw = params.get("pumpkin_watch") or ""
        if isinstance(watch_raw, list):
            watch = [str(w).strip() for w in watch_raw if str(w).strip()]
        else:
            watch = [w.strip() for w in str(watch_raw).replace("，", ",").split(",") if w.strip()]
        sortie_plan = {"mode": "pumpkin",
                       "team_no": _i(params, "team_no", 3),
                       "watch_names": watch,
                       "max_skips": _i(params, "pumpkin_max_skips", 4)}
    else:
        sortie_plan = {"mode": "none"}
    # 一键日课的演练完整沿用「演练」配置页，避免两处配置互相打架。
    saved_practice = (_load_panel_settings().get("params", {}).get("practice", {}) or {})
    practice_plan = dict(saved_practice)
    if practice_plan.get("team_no") not in (None, ""):
        practice_plan["team_no"] = int(practice_plan["team_no"])
    yield from _make_agent(config_path).daily_stream(
        only=steps, after=after, sortie_override=sortie_plan,
        practice_override=practice_plan or None)


def _build_raid(config_path, params):
    yield from _make_agent(config_path).raid_stream(
        max_rounds=_i(params, "rounds", 3),
        team_no=_i(params, "team_no", 3),
        max_buys=_i(params, "max_buys", 30))


def _build_pumpkin(config_path, params):
    difficulty = _i(params, "difficulty", 0)
    watch_raw = params.get("watch") or ""
    if isinstance(watch_raw, list):
        watch = [str(w).strip() for w in watch_raw if str(w).strip()]
    else:
        watch = [w.strip() for w in str(watch_raw).replace("，", ",").split(",") if w.strip()]
    yield from _make_agent(config_path).pumpkin_stream(
        team_no=_i(params, "team_no", 3),
        difficulty=difficulty or None,
        watch_names=watch or None,
        max_skips=_i(params, "pumpkin_max_skips", 4))


def _build_sortie(config_path, params):
    yield from _make_agent(config_path).sortie_stream(
        chapter=_i(params, "chapter", 1),
        map_no=_i(params, "map_no", 1),
        team_no=_i(params, "team_no", 3),
        auto_march=_bool(params.get("auto_march", True)),
        max_loops=_i(params, "loops", 1),
        formation_mode=params.get("formation_mode") or "manual",
        formation_strategy=params.get("formation_strategy") or "fixed",
        formation=params.get("formation") or "鱼鳞阵",
        repair_threshold=params.get("repair_threshold") or "light",
        injury_action=params.get("repair_on_injury") or "continue")


def _build_sakura(config_path, params):
    yield from _make_agent(config_path).sakura_stream(
        team_no=_i(params, "team_no", 1),
        slot=_i(params, "slot", 1))


def _build_forge(config_path, params):
    watch_raw = params.get("watch") or ""
    if isinstance(watch_raw, list):
        # Agent 网关传的是数组 ["03:20:00", ...]
        watch = [str(w).strip() for w in watch_raw if str(w).strip()]
    else:
        # 面板传的是字符串 "03:20:00, 04:00:00"
        watch = [w.strip() for w in re.split(r"[，,、;；\s]+", str(watch_raw)) if w.strip()]
    yield from _make_agent(config_path).forge_stream(
        times=_i(params, "times", 3), watch=watch)


def _build_repair(config_path, params):
    team_names = {f"部队{i}": i for i in range(1, 6)}
    raw_teams = params.get("speedup_teams")
    speedup_teams = None
    if isinstance(raw_teams, list):
        speedup_teams = [team_names[x] for x in raw_teams if x in team_names]
    yield from _make_agent(config_path).repair_stream(
        dry_run=_bool(params.get("dry_run", False)),
        speedup_teams=speedup_teams)


def _build_dispatch(config_path, params):
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
    agent = _make_agent(config_path)
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
    path = _PROJECT / "status" / "expeditions.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_expedition_manager(config_path, params):
    """收取归来队伍，最多等十分钟，再按“常用安排”派遣。"""
    from .scheduler import find_map, load_config

    plan = [p for p in load_config().get("common_plan", [])
            if p.get("enabled") and p.get("map_code")]
    if not plan:
        yield "[远征管理] 没有启用任何常用安排，先去配置页勾选部队"
        return

    agent = _make_agent(config_path)
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
    def _fn(config_path, params):
        agent = _make_agent(config_path)
        method = getattr(agent, stream_method_name, None)
        if method is None:
            raise RuntimeError(f"Agent 没有 {stream_method_name} 方法")
        yield from method()
    return _fn


register_script("daily", "一键日课", "勾选要干的活，一条龙跑完；演练和合战场行为沿用各自配置",
                 _build_daily,
                 params=[{"key": "steps", "type": "checks", "label": "要干的活（不勾的不跑）",
                          "options": _DAILY_STEPS, "default": _DAILY_STEPS,
                           "help": "演练沿用左侧「演练」配置；合战场的自动行军、阵形和伤势处理沿用「出阵」配置。地图、部队与圈数仍在本页设置。"},
                        {"key": "sortie_mode", "type": "select", "label": "出阵安排",
                         "options": [["none", "不出阵"],
                                     ["raid", "联队战（活动）"],
                                     ["sortie", "合战场推图"],
                                     ["pumpkin", "南瓜大作战（活动）"]],
                         "default": "raid"},
                        {"key": "team_no", "type": "select", "label": "出阵部队",
                         "options": _TEAM_OPTIONS, "default": "3",
                         "visibleWhen": {"key": "sortie_mode", "not": "none"}},
                        {"key": "raid_rounds", "type": "number", "label": "联队战圈数",
                         "default": 3, "min": 1, "max": 99,
                         "visibleWhen": {"key": "sortie_mode", "is": "raid"}},
                        {"key": "raid_buys", "type": "number",
                         "label": "手形最多买几次",
                         "default": 30, "min": 0, "max": 99,
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
                        {"key": "pumpkin_max_skips", "type": "number",
                         "label": "更新令牌烧几枚（烧完收工）",
                         "hint": "令牌 = 一切：打满拿刀后的刷新、认出非目标的刷新都算。默认 4，想全刷就把数字填大",
                         "default": 4, "min": 1, "max": 99,
                         "visibleWhen": {"key": "sortie_mode", "is": "pumpkin"}},
                        {"key": "pumpkin_watch", "type": "text", "swords": True,
                         "label": "只刷这些刀（留空=全刷不认人）",
                         "default": "",
                         "placeholder": "点下方候选添加，或手动输入逗号分隔",
                         "presets": [{"label": "清空", "value": []}],
                         "visibleWhen": {"key": "sortie_mode", "is": "pumpkin"}},
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
                         "default": 3, "min": 1, "max": 99},
                        {"key": "max_buys", "type": "number",
                         "label": "手形最多买几次（加班烧小判用）",
                         "default": 30, "min": 0, "max": 99}])
register_script("pumpkin", "南瓜大作战", "刮刮乐刷剪影，能认出是哪把刀，不想要的自动烧令牌换板子",
                _build_pumpkin,
                params=[_team_field("3"),
                        {"key": "rounds", "type": "number",
                         "label": "刷几局（一局=九宫格全翻完）",
                         "default": 1, "min": 1, "max": 99},
                        {"key": "difficulty", "type": "select", "label": "难度",
                         "options": [["0", "不点（用当前tab）"],
                                     ["1", "初级"], ["2", "中级"], ["3", "上级"]],
                         "default": "0"},
                        {"key": "watch", "type": "text", "swords": True,
                         "label": "只刷这些刀（逗号分隔，留空=全刷不认人）",
                         "default": "", "placeholder": "点下方候选添加，或手动输入逗号分隔",
                         "presets": [{"label": "清空", "value": []}]},
                        {"key": "max_skips", "type": "number",
                         "label": "更新令牌最多烧几枚（认出不想要的才烧）",
                         "default": 10, "min": 0, "max": 99}])
register_script("sortie", "出阵", "普通图：部队x 去打 x-x",
                _build_sortie,
                params=[_team_field("3"),
                        {"key": "chapter", "type": "select", "label": "章节",
                         "options": [[str(i), f"{i}章"] for i in range(1, 9)], "default": "1"},
                        {"key": "map_no", "type": "select", "label": "小图",
                         "options": [[str(i), f"{i}图"] for i in range(1, 5)], "default": "1"},
                        {"key": "loops", "type": "number", "label": "连打几圈",
                         "default": 1, "min": 1, "max": 99},
                        {"key": "auto_march", "type": "select",
                         "label": "行军方式",
                         "options": [["true", "使用游戏自动行军"],
                                     ["false", "脚本手动行军"]],
                         "default": "true",
                         "help": "自动行军会由游戏处理路线与阵形；关闭后才使用下方阵形设置。"},
                        {"key": "formation_mode", "type": "select",
                         "label": "阵形选择方式",
                         "options": [["manual", "游戏内手动阵形"],
                                     ["auto", "游戏内自动阵形"]],
                         "default": "manual",
                         "visibleWhen": {"key": "auto_march", "is": "false"}},
                        {"key": "formation_strategy", "type": "select",
                         "label": "阵形策略",
                         "options": [["fixed", "固定阵形"],
                                     ["advantage", "优先选择有利阵形"]],
                         "default": "fixed",
                         "visibleWhen": {"key": "auto_march", "is": "false"}},
                        {"key": "formation", "type": "select",
                         "label": "固定或识别失败时的兜底阵形",
                         "options": [[name, name] for name in
                                     ["鱼鳞阵", "横队阵", "雁行阵",
                                      "鹤翼阵", "方阵", "逆行阵"]],
                         "default": "鱼鳞阵",
                         "visibleWhen": {"key": "auto_march", "is": "false"}},
                        {"key": "repair_threshold", "type": "select",
                         "label": "什么时候开始手入",
                         "options": [["light", "轻伤开始手入"],
                                     ["medium", "轻伤继续，中伤开始手入"],
                                     ["heavy", "轻伤和中伤继续，只在重伤时手入"]],
                         "default": "light",
                         "help": "出阵前和局内行军选择时都会检查；重伤永远不会继续出阵。"},
                        {"key": "repair_on_injury", "type": "select",
                         "label": "达到上述伤势后",
                         "options": [["continue", "自动手入后继续"],
                                     ["repair_stop", "立即收工，手入但不用加速符"],
                                     ["stop", "立即收工，不手入"]],
                         "default": "continue",
                         "help": "选择继续时会加速修复当前出阵队，并接着完成剩余圈数。重伤即使选择“不手入”也会尝试普通手入后收工；黑名单仍不修。"}])
register_script("sakura", "刷花", "队长单挑 1-1 刷疲劳到 100，满了自动换人",
                _build_sakura,
                params=[_team_field("1"),
                        {"key": "slot", "type": "select", "label": "位置",
                         "options": [[str(i), f"{i}号位" + ("（队长）" if i == 1 else "")]
                                     for i in range(1, 7)], "default": "1"}])
def _build_practice(config_path, params):
    # 面板单跑演练：真打 + 部队可选（_build_simple 裸调会掉进 dry_run 认人演习模式）
    return _make_agent(config_path).practice_stream(
        dry_run=False,
        team_no=_i(params, "team_no", 2),
        formation_mode=params.get("formation_mode") or "manual",
        formation_strategy=params.get("formation_strategy") or "fixed",
        formation=params.get("formation") or "逆行阵")


register_script("practice", "演练", "只认人打软柿子，赢 3 场收工",
                _build_practice,
                params=[
                    _team_field("2"),
                    {"key": "formation_mode", "type": "select",
                     "label": "阵形选择方式",
                     "options": [["manual", "手动选择（每战按策略点阵形）"],
                                 ["auto", "使用游戏自动阵形"]],
                     "default": "manual",
                     "help": "自动模式会先切换右上角开关并选择一次；敌方阵形不明时仍使用兜底阵形。"},
                    {"key": "formation_strategy", "type": "select",
                     "label": "手动/首次选择策略",
                     "options": [["fixed", "固定阵形"],
                                 ["advantage", "优先选择有利阵形"]],
                     "default": "fixed"},
                    {"key": "formation", "type": "select",
                     "label": "固定或识别失败时的兜底阵形",
                     "options": [[name, name] for name in
                                 ["鱼鳞阵", "横队阵", "雁行阵",
                                  "鹤翼阵", "方阵", "逆行阵"]],
                     "default": "逆行阵"},
                ])
register_script("expedition", "远征", "收菜、等待临近归来，并按常用安排派遣",
                _build_expedition_manager)


def _map_select_field():
    from .scheduler import map_options
    opts = [[o["code"], f'{o["code"]} · {o["name"]}（{o["duration_text"]}）']
            for o in map_options()]
    return {"key": "map_code", "type": "select", "label": "远征图",
            "options": opts, "default": opts[0][0] if opts else ""}


register_script("dispatch", "派遣远征", "立刻派一支部队去指定远征图",
                _build_dispatch,
                params=[_team_field("2"), _map_select_field()], hidden=True)
register_script("forge", "锻刀", "收完成的刀，再给空闲炉点火；不使用加速符",
                _build_forge,
                params=[{"key": "times", "type": "number", "label": "最多锻几炉",
                         "default": 3, "min": 1, "max": 12,
                         "help": "日课目标是锻刀 3 次，但脚本只使用当前空闲炉，绝不会消耗加速符。默认两炉的账号通常本次只能锻 2 次；没必要为了返还委托符强行加速。"},
                        {"key": "watch", "type": "duration-list",
                         "label": "目标时长（命中时手机报喜，不添加则不盯）",
                         "default": ""}])
register_script("repair", "手入", "单独扫描受伤刀剑；黑名单跳过，其余按部队决定是否加速",
                _build_repair,
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
                         "help": "这里只影响单独运行“手入”：黑名单始终跳过，选中部队即时修好，其他队只安排普通手入。连续出阵选择“自动手入后继续”时，会自动加速当前出阵队，不读取这里。"}])
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

    # Bot 启动（配了 panel_config.json 才启；QQ/TG 各自独立开关）
    from .bot_qq import init_qq
    _qq_sender = init_qq(app, _get_gateway)

    from .bot_telegram import start_bot as _start_bot
    _bot_instance = _start_bot(_get_gateway())

    # 事件播报器：挂上 QQ 出口（没配 QQ 也能跑，只发 ntfy）
    from .broadcaster import init_broadcaster
    init_broadcaster(qq_sender=_qq_sender)

    # 暴露给 API 路由用：机器人控制
    import __main__ as _bm
    _bm._bot_instance = _bot_instance


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
    "sortie": "正在出阵打图🗡",
    "sakura": "正在给刀剑男士刷樱花🌸",
    "practice": "正在演练场挑软柿子捏🥊",
    "expedition": "正在流放刀剑男士⛺",
    "dispatch": "正在流放刀剑男士⛺",
    "forge": "正在盯炉火🔥",
    "sugar": "正在炼糖🍬",
    "snapshot": "正在盘点家底📦",
}


def _flavor_text(script: str | None, step: str) -> str:
    if step in _STEP_FLAVOR:
        return _STEP_FLAVOR[step]
    return _SCRIPT_FLAVOR.get(script or "", "正在本丸干活🔧")


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

    data = {
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "inventory": _read("inventory.json"),
        "latest_report": _read("latest_report.json"),
        "naihanka": _read("naihanka.json"),
    }

    # 远征：给每条算好剩余秒数，前端只管倒计时
    expeditions = []
    raw_exp = _read("expeditions.json") or {}
    now = time.time()
    for team_no, e in raw_exp.items():
        item = dict(e)
        item["team_no"] = team_no
        try:
            dispatched = time.mktime(time.strptime(e["dispatched_at"], "%Y-%m-%d %H:%M:%S"))
            remain = dispatched + float(e.get("duration_min", 0)) * 60 - now
            item["remain_sec"] = max(0, int(remain))
            item["done"] = remain <= 0
        except Exception:
            item["remain_sec"] = None
            item["done"] = False
        expeditions.append(item)
    data["expeditions"] = sorted(expeditions, key=lambda x: x.get("remain_sec") or 0)

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


# ── API：OCR 数据统计（日志流里扒拉出来的）──

import sqlite3

_OCR_SWORD_PATTERN = re.compile(r"【([^】]+)】")


@app.get("/api/stats/ocr")
async def api_ocr_stats():
    """从日志库里统计 OCR 数据：认刀排行、操作次数等"""
    db_path = _PROJECT / "status" / "maamaru_logs.db"
    if not db_path.exists():
        return {"sword_ranks": [], "script_counts": {}, "total_logs": 0, "ok": True}
    try:
        conn = sqlite3.connect(str(db_path))
        total = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]

        # 刀剑识别排行：从消息里扒 【刀名】
        rows = conn.execute(
            "SELECT message FROM logs WHERE message LIKE '%【%】%'"
        ).fetchall()
        sword_counts = {}
        for (msg,) in rows:
            for m in _OCR_SWORD_PATTERN.findall(msg):
                if m:
                    sword_counts[m] = sword_counts.get(m, 0) + 1
        sword_ranks = sorted(sword_counts.items(), key=lambda x: -x[1])[:20]

        # 最近 7 天各脚本执行条数
        week_ago = time.time() - 86400 * 7
        rows = conn.execute(
            "SELECT script, COUNT(*) as cnt FROM logs "
            "WHERE ts > ? GROUP BY script ORDER BY cnt DESC",
            (week_ago,),
        ).fetchall()
        script_counts = {r[0]: r[1] for r in rows}

        conn.close()
        return {
            "sword_ranks": [{"name": n, "count": c} for n, c in sword_ranks],
            "script_counts": script_counts,
            "total_logs": total,
            "ok": True,
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
