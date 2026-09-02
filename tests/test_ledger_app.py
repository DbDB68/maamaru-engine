import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# 先设置数据目录覆盖，避免 server 模块导入时写到真实 LOCALAPPDATA
_tmp_root = Path(tempfile.mkdtemp(prefix="ledger_app_test_"))
with patch.dict(os.environ, {"MAAMARU_DATA_DIR": str(_tmp_root)}):
    from fastapi.testclient import TestClient

    from ledger_app.server import create_app
    from touken import telemetry


@pytest.fixture
def client(tmp_path, monkeypatch):
    """每个测试用独立 telemetry 数据库，并把 server 的写路径指到 tmp_path。"""
    from ledger_app import server
    from touken import runtime_paths

    # 让 runtime_paths 重新计算到 tmp_path
    monkeypatch.setenv("MAAMARU_DATA_DIR", str(tmp_path))
    importlib = __import__("importlib")
    importlib.reload(runtime_paths)

    # server 模块在导入时已经复制了常量，直接覆盖 server 模块里的引用
    monkeypatch.setattr(server, "DATA_ROOT", runtime_paths.DATA_ROOT)
    monkeypatch.setattr(server, "STATE_DIR", runtime_paths.STATE_DIR)
    monkeypatch.setattr(server, "LOG_DIR", runtime_paths.LOG_DIR)
    monkeypatch.setattr(server, "BACKUP_DIR", runtime_paths.BACKUP_DIR)
    monkeypatch.setattr(server, "CONFIG_PATH", runtime_paths.CONFIG_PATH)
    monkeypatch.setattr(server, "_SETTINGS_FILE", runtime_paths.STATE_DIR / "ledger_settings.json")

    db_path = runtime_paths.LOG_DIR / "telemetry.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = telemetry.TelemetryStore(db_path)
    monkeypatch.setattr(telemetry, "_store", store)

    app = create_app()
    yield TestClient(app)
    store.close()


def test_app_mode_is_ledger(client):
    resp = client.get("/api/app-mode")
    assert resp.status_code == 200
    assert resp.json() == {"mode": "ledger"}


def test_resource_ledger_empty_is_valid(client):
    resp = client.get("/api/data/resource-ledger")
    assert resp.status_code == 200
    data = resp.json()
    assert "per_resource" in data
    assert "daily_series" in data
    assert "schema_version" in data
    resources = {item["resource"] for item in data["per_resource"]}
    for name in ("木炭", "玉钢", "冷却材", "砥石", "小判", "甲州金", "委托符", "加速符"):
        assert name in resources


def test_ledger_onboarding_empty(client):
    resp = client.get("/api/data/ledger-onboarding")
    assert resp.status_code == 200
    data = resp.json()
    assert data["visible"] is True
    assert data["status"] == "pending"
    assert data["step"] == 1


def test_static_fallback_when_no_build(client, tmp_path, monkeypatch):
    """静态目录不存在时，/ 返回兜底 HTML，而不是 500。"""
    from ledger_app import server
    # 让 server 以为 static 目录在 tmp_path 下且不存在
    monkeypatch.setattr(server, "_STATIC", tmp_path / "nonexistent_static")
    # 重新创建 app 使路由按新的 _STATIC 注册
    app = create_app()
    test_client = TestClient(app)
    resp = test_client.get("/")
    assert resp.status_code == 200
    assert "前端构建产物还没放进来" in resp.text


def test_config_lists_with_missing_config(client):
    resp = client.get("/api/config-lists")
    assert resp.status_code == 200
    data = resp.json()
    assert "sword_wishlist" in data
    assert data["sword_wishlist"] == []


def test_wishlist_roundtrip_preserves_other_config(client):
    from ledger_app import server

    server.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    server.CONFIG_PATH.write_text(json.dumps({
        "repair": {"blacklist": ["岩融"]},
        "daily": {"enabled": True},
    }, ensure_ascii=False), encoding="utf-8")

    resp = client.post("/api/config-lists", json={
        "sword_wishlist": [" 姬鹤一文字 ", "", "道誉一文字", "姬鹤一文字"],
        "repair_blacklist": ["不该被纯净账房改动"],
    })
    assert resp.status_code == 200
    assert resp.json()["sword_wishlist"] == ["姬鹤一文字", "道誉一文字"]

    saved = json.loads(server.CONFIG_PATH.read_text(encoding="utf-8"))
    assert saved["sword_wishlist"] == ["姬鹤一文字", "道誉一文字"]
    assert saved["repair"]["blacklist"] == ["岩融"]
    assert saved["daily"] == {"enabled": True}


def test_swords_endpoint_supplies_wishlist_candidates(client):
    resp = client.get("/api/swords")
    assert resp.status_code == 200
    swords = resp.json()["swords"]
    assert len(swords) > 100
    assert any(item["name_zh"] == "姬鹤一文字" and item["type"] == "太刀" for item in swords)


def test_saved_settings_roundtrip(client):
    resp = client.post("/api/saved-settings", json={"theme": "pixel", "hero_resource": "玉钢"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp = client.get("/api/saved-settings")
    assert resp.status_code == 200
    assert resp.json()["theme"] == "pixel"
    assert resp.json()["hero_resource"] == "玉钢"


def test_custom_goal_roundtrip(client):
    created = client.post("/api/planning/goals", json={
        "goal_mode": "amount_target", "resource": "玉钢",
        "target": 100_000, "note": "下一轮锻刀",
    })
    assert created.status_code == 200
    goal_id = created.json()["goal"]["id"]

    planning = client.get("/api/planning")
    assert planning.status_code == 200
    goal = next(item for item in planning.json()["goals"] if item["id"] == goal_id)
    assert goal["resource"] == "玉钢"
    assert goal["target"] == 100_000
    assert client.delete(f"/api/planning/goals/{goal_id}").status_code == 200
    assert client.get("/api/planning").json()["goals"] == []


def test_manual_resource_group_roundtrip(client):
    created = client.post("/api/data/human-reports/batch", json={
        "occurred_at": 1_700_000_000,
        "activities": ["领邮箱"],
        "note": "绿玩手账",
        "entries": {"小判": 1200, "木炭": -50},
    })
    assert created.status_code == 200
    group_id = created.json()["group_id"]

    updated = client.put(f"/api/data/human-reports/group/{group_id}", json={
        "occurred_at": 1_700_000_100,
        "activities": ["手动领奖"],
        "note": "改好了",
        "entries": {"小判": 1300},
    })
    assert updated.status_code == 200
    listing = client.get("/api/data/human-reports").json()["items"]
    assert [(item["resource"], item["claimed_delta"]) for item in listing] == [("小判", 1300)]

    assert client.delete(f"/api/data/human-reports/group/{group_id}").status_code == 200
    assert client.get("/api/data/human-reports").json()["items"] == []


def test_manual_inventory_roundtrip(client):
    created = client.post("/api/data/manual-inventory", json={
        "observed_at": 1_700_000_000,
        "resources": {"小判": 50_000, "木炭": 12_000},
    })
    assert created.status_code == 200
    event_id = created.json()["snapshot"]["id"]

    updated = client.put(f"/api/data/manual-inventory/{event_id}", json={
        "observed_at": 1_700_000_100,
        "resources": {"小判": 51_000},
    })
    assert updated.status_code == 200
    assert updated.json()["snapshot"]["resources"] == {"小判": 51_000}
    assert client.delete(f"/api/data/manual-inventory/{event_id}").status_code == 200
    assert client.get("/api/data/manual-inventory").json()["items"] == []


def test_manual_session_roundtrip(client):
    created = client.post("/api/data/manual-sessions", json={
        "script": "edocastle", "started_at": 1_700_000_000,
        "ended_at": 1_700_003_600, "loops": 6, "note": "自己打的",
    })
    assert created.status_code == 200
    session_id = created.json()["item"]["id"]

    updated = client.put(f"/api/data/manual-sessions/{session_id}", json={
        "script": "edocastle", "started_at": 1_700_000_000,
        "ended_at": 1_700_004_200, "loops": 7, "note": "多打一圈",
    })
    assert updated.status_code == 200
    assert updated.json()["item"]["loops"] == 7
    assert client.delete(f"/api/data/manual-sessions/{session_id}").status_code == 200
    assert client.get("/api/data/manual-sessions").json()["items"] == []


def teardown_module():
    # 清理模块级临时目录
    shutil.rmtree(_tmp_root, ignore_errors=True)
