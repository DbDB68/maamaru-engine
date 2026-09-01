# -*- coding: utf-8 -*-
"""
まあ丸 账房 —— 独立 FastAPI 服务

只暴露账房相关接口：资源总账、手账、导入导出、规划建议、活动日历。
不接触任何自动化设施（脚本运行、调度、模拟器、机器人）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# 开发/打包后都能定位到项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from touken.runtime_paths import (
    BACKUP_DIR,
    CONFIG_PATH,
    DATA_ROOT,
    LOG_DIR,
    PANEL_CONFIG_PATH,
    STATE_DIR,
    ensure_runtime_data,
)

# 初始化用户数据目录（配置、状态、日志、备份等）
ensure_runtime_data()

_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"

from touken.flows.smith import DISMANTLE_WHITELIST as _DISMANTLE_WHITELIST

# 活动日历源与面板一致
EVENTS_CALENDAR_URL = "http://49.235.132.50:8321/events.json"
EVENTS_CACHE_TTL = 6 * 3600

_SETTINGS_FILE = STATE_DIR / "ledger_settings.json"


# ── 通用 ──


def _load_panel_settings() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_panel_settings(data: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["_saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_events_calendar() -> tuple[dict, bool]:
    """读活动日历（先本地 6h 缓存，过期则拉服务器，拉不动用旧缓存）。"""
    cache_path = STATE_DIR / "events_calendar.json"
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


# ── App ──


def create_app() -> FastAPI:
    app = FastAPI(title="まあ丸 账房")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    # 静态目录 / 兜底提示
    static_index = _STATIC / "index.html"
    if _STATIC.is_dir() and static_index.is_file():
        assets_dir = _STATIC / "assets"
        if assets_dir.is_dir():
            # Vite 默认 base="/"，index.html 引用 /assets/...
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        # 账房复用主面板的样式，style.css 里的 /static/fonts、/static/img
        # 实物还在 panel/static 下，只读挂载过来（比 /static 更具体，要先注册）。
        panel_static = _HERE.parent / "panel" / "static"
        for name in ("fonts", "img"):
            shared = panel_static / name
            if shared.is_dir():
                app.mount(f"/static/{name}", StaticFiles(directory=str(shared)),
                          name=f"shared-{name}")
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

        @app.get("/")
        async def root():
            return FileResponse(str(static_index))
    else:
        _FALLBACK_HTML = (
            "<!DOCTYPE html>\n"
            '<html lang="zh-CN">\n'
            "<head><meta charset=\"utf-8\"><title>まあ丸账房</title></head>\n"
            "<body>\n"
            "  <h1>まあ丸账房</h1>\n"
            "  <p>前端构建产物还没放进来，请先构建面板并复制到 ledger_app/static/。</p>\n"
            "</body>\n"
            "</html>\n"
        )

        @app.get("/")
        async def root():
            return Response(content=_FALLBACK_HTML, media_type="text/html")

        @app.get("/index.html")
        async def index_html():
            return Response(content=_FALLBACK_HTML, media_type="text/html")

    # ── API：模式与设置 ──

    @app.get("/api/app-mode")
    async def api_app_mode():
        return {"mode": "ledger"}

    @app.get("/api/saved-settings")
    async def api_get_saved_settings():
        """获取服务端保存的账房设置（主题、各玩法参数记忆）。"""
        return _load_panel_settings()

    @app.post("/api/saved-settings")
    async def api_save_settings(request: Request):
        """保存账房设置（合并式：脚本参数、主题各存各的，互不覆盖）。"""
        body = await request.json()
        existing = _load_panel_settings()
        existing.pop("_saved_at", None)
        params = body.get("params")
        if isinstance(params, dict):
            clean = {k: v for k, v in params.items() if isinstance(v, dict)}
            existing["params"] = clean
        if body.get("theme") in ("washi", "pixel"):
            existing["theme"] = body["theme"]
        _save_panel_settings(existing)
        return {"ok": True}

    @app.get("/api/config-lists")
    async def api_get_config_lists():
        """读取当前游戏配置里的名单（只读，供账房前端选择器使用）。"""
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        return {
            "repair_blacklist": cfg.get("repair", {}).get("blacklist", []),
            "dismantle_whitelist": cfg.get("dismantle", {}).get("whitelist", _DISMANTLE_WHITELIST),
            "sword_wishlist": cfg.get("sword_wishlist", []),
        }

    # ── API：资源总账 ──

    @app.get("/api/data/resource-ledger")
    async def api_data_resource_ledger(days: int = 7,
                                       from_ts: float | None = Query(None, alias="from"),
                                       to: float | None = None):
        """资源总账：窗口内八资源的观察链/归因/缺口，聚合全部在服务端完成。"""
        from touken.telemetry import get_telemetry_store
        to_ts = float(to) if to else time.time()
        start = float(from_ts) if from_ts is not None \
            else to_ts - max(1, min(int(days), 365)) * 86400
        return get_telemetry_store().resource_ledger(start, to_ts)

    @app.get("/api/data/ledger-onboarding")
    async def api_ledger_onboarding():
        """只给真正空账本的新用户显示一次三步引导。"""
        from touken.ledger_onboarding import ONBOARDING_FILENAME, get_onboarding
        from touken.telemetry import get_telemetry_store
        return get_onboarding(get_telemetry_store(), STATE_DIR / ONBOARDING_FILENAME)

    @app.post("/api/data/ledger-onboarding")
    async def api_update_ledger_onboarding(request: Request):
        """保存引导进度；完成或明确跳过后不再打扰。"""
        from touken.ledger_onboarding import ONBOARDING_FILENAME, update_onboarding
        from touken.telemetry import get_telemetry_store
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("引导请求格式不正确")
            result = update_onboarding(
                get_telemetry_store(), STATE_DIR / ONBOARDING_FILENAME,
                str(body.get("action") or ""), step=body.get("step"),
            )
        except (OSError, TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return {"ok": True, **result}

    @app.get("/api/data/ledger-export")
    async def api_ledger_export(format: str = "xlsx"):
        """导出账房快照：Excel 含完整流水/当前家底/每日汇总，CSV 为完整流水。"""
        from touken.ledger_transfer import export_ledger_csv, export_ledger_xlsx
        from touken.telemetry import get_telemetry_store
        selected = str(format or "xlsx").strip().lower()
        if selected not in {"xlsx", "csv"}:
            return JSONResponse(
                {"ok": False, "reason": "只支持 xlsx 或 csv"}, status_code=400)
        store = get_telemetry_store()
        if selected == "xlsx":
            body = export_ledger_xlsx(store)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            body = export_ledger_csv(store)
            media_type = "text/csv; charset=utf-8"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"maamaru-ledger-{stamp}.{selected}"
        return Response(
            content=body, media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    @app.post("/api/data/ledger-import/preview")
    async def api_ledger_import_preview(request: Request, filename: str = ""):
        """只解析不落盘；返回新记录、重复、冲突和无法识别行。"""
        from touken.ledger_transfer import create_import_preview
        from touken.telemetry import get_telemetry_store
        try:
            result = create_import_preview(
                get_telemetry_store(), await request.body(), Path(filename).name)
        except (OSError, TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return {"ok": True, **result}

    @app.post("/api/data/ledger-import/apply")
    async def api_ledger_import_apply(request: Request):
        """重新检查预览内容，先备份 telemetry.db，再只写入玩家手动记录。"""
        from touken.ledger_transfer import apply_import_preview
        from touken.telemetry import get_telemetry_store
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("导入请求格式不正确")
            result = apply_import_preview(
                get_telemetry_store(), str(body.get("preview_id") or ""), BACKUP_DIR,
                accept_conflicts=bool(body.get("accept_conflicts")),
            )
        except (OSError, TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=409)
        return {"ok": True, **result}

    # ── API：手动家底 ──

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

    @app.get("/api/data/manual-inventory")
    async def api_manual_inventory(limit: int = 200):
        """列出审神者自己抄入的家底，供“我的手账”纠错。"""
        from touken.telemetry import get_telemetry_store, TELEMETRY_SCHEMA_VERSION
        return {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "items": get_telemetry_store().manual_inventory(limit=limit),
        }

    @app.put("/api/data/manual-inventory/{event_id}")
    async def api_update_manual_inventory(event_id: int, request: Request):
        body = await request.json()
        from touken.telemetry import get_telemetry_store
        try:
            snapshot = get_telemetry_store().update_manual_inventory(
                event_id, body.get("resources") or {}, observed_at=body.get("observed_at"))
        except (TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return {"ok": True, "snapshot": snapshot}

    @app.delete("/api/data/manual-inventory/{event_id}")
    async def api_delete_manual_inventory(event_id: int):
        from touken.telemetry import get_telemetry_store
        if not get_telemetry_store().delete_manual_inventory(event_id):
            return JSONResponse(
                {"ok": False, "reason": "找不到这条手动家底记录"}, status_code=404)
        return {"ok": True}

    # ── API：手动活动记录 ──

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

    @app.put("/api/data/manual-sessions/{session_id}")
    async def api_update_manual_session(session_id: int, request: Request):
        body = await request.json()
        from touken.telemetry import get_telemetry_store
        try:
            item = get_telemetry_store().update_manual_session(
                session_id, script=body.get("script"),
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

    # ── API：审神者报备 ──

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

    @app.post("/api/data/human-reports/batch")
    async def api_add_human_report_batch(request: Request):
        body = await request.json()
        from touken.telemetry import get_telemetry_store
        entries = body.get("entries") or {}
        if not isinstance(entries, dict):
            return JSONResponse({"ok": False, "reason": "多资源收支格式不正确"}, status_code=400)
        try:
            items = get_telemetry_store().add_human_report_group(
                occurred_at=float(body.get("occurred_at") or time.time()),
                activities=body.get("activities") or [], note=body.get("note", ""),
                entries=entries)
        except (TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return {"ok": True, "items": items, "group_id": items[0]["group_id"]}

    @app.put("/api/data/human-reports/{report_id}")
    async def api_update_human_report(report_id: int, request: Request):
        body = await request.json()
        from touken.telemetry import get_telemetry_store
        try:
            item = get_telemetry_store().update_human_report(
                report_id, occurred_at=float(body.get("occurred_at") or time.time()),
                activities=body.get("activities") or [], note=body.get("note", ""),
                resource=body.get("resource"), claimed_delta=body.get("claimed_delta"))
        except (TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return {"ok": True, "item": item}

    @app.delete("/api/data/human-reports/{report_id}")
    async def api_delete_human_report(report_id: int):
        from touken.telemetry import get_telemetry_store
        if not get_telemetry_store().delete_human_report(report_id):
            return JSONResponse(
                {"ok": False, "reason": "找不到这条审神者报备"}, status_code=404)
        return {"ok": True}

    @app.put("/api/data/human-reports/group/{group_id}")
    async def api_update_human_report_group(group_id: str, request: Request):
        body = await request.json()
        from touken.telemetry import get_telemetry_store
        entries = body.get("entries") or {}
        if not isinstance(entries, dict):
            return JSONResponse({"ok": False, "reason": "多资源收支格式不正确"}, status_code=400)
        try:
            items = get_telemetry_store().update_human_report_group(
                group_id, occurred_at=float(body.get("occurred_at") or time.time()),
                activities=body.get("activities") or [], note=body.get("note", ""),
                entries=entries)
        except (TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return {"ok": True, "items": items, "group_id": group_id}

    @app.delete("/api/data/human-reports/group/{group_id}")
    async def api_delete_human_report_group(group_id: str):
        from touken.telemetry import get_telemetry_store
        if not get_telemetry_store().delete_human_report_group(group_id):
            return JSONResponse(
                {"ok": False, "reason": "找不到这组手账"}, status_code=404)
        return {"ok": True}

    # ── API：活动日历与规划建议 ──

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
        """事件时间轴：已核实活动按 进行中/7天内/更远 分组排序。"""
        from touken import advisor, event_timeline
        from touken.telemetry import get_telemetry_store
        planning = advisor.get_planning(get_telemetry_store(),
                                        STATE_DIR / advisor.GOALS_FILENAME)
        calendar, stale = _load_events_calendar()
        timeline = event_timeline.build_timeline(
            advisor.load_event_cards(STATE_DIR),
            planning.get("events", []),
            calendar.get("announcements", []))
        return {**timeline, "calendar_stale": stale}

    @app.get("/api/planning")
    async def api_planning():
        """攒钱目标 + 按近日净收支速率推算的到期预测。"""
        from touken import advisor
        from touken.telemetry import get_telemetry_store
        return advisor.get_planning(get_telemetry_store(),
                                    STATE_DIR / advisor.GOALS_FILENAME)

    @app.post("/api/planning/goals")
    async def api_add_planning_goal(request: Request):
        body = await request.json()
        from touken import advisor
        try:
            goal = advisor.add_goal(STATE_DIR / advisor.GOALS_FILENAME,
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
        if not advisor.delete_goal(STATE_DIR / advisor.GOALS_FILENAME, goal_id):
            return JSONResponse({"ok": False, "reason": "找不到这个小目标"}, status_code=404)
        return {"ok": True}

    @app.post("/api/planning/event-estimate")
    async def api_save_event_estimate(request: Request):
        """保存用户手填的活动场均钥匙预估；实测数据来了自动盖过它。"""
        body = await request.json()
        from touken import advisor
        try:
            card = advisor.save_key_estimate(STATE_DIR,
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
                                            STATE_DIR / advisor.GOALS_FILENAME,
                                            str(body.get("event") or ""),
                                            target=body.get("target"))
        except ValueError as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return {"ok": True, **result}

    return app


# 模块级 app，供 uvicorn 直接运行：uvicorn ledger_app.server:app
app = create_app()
