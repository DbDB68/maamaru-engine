import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# 先设置数据目录覆盖，避免 server 模块导入时写到真实 LOCALAPPDATA
_tmp_root = Path(tempfile.mkdtemp(prefix="ledger_app_test_"))
os.environ["MAAMARU_DATA_DIR"] = str(_tmp_root)

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


def test_config_lists_read_only_with_missing_config(client):
    resp = client.get("/api/config-lists")
    assert resp.status_code == 200
    data = resp.json()
    assert "sword_wishlist" in data
    assert data["sword_wishlist"] == []


def test_saved_settings_roundtrip(client):
    resp = client.post("/api/saved-settings", json={"theme": "pixel"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp = client.get("/api/saved-settings")
    assert resp.status_code == 200
    assert resp.json()["theme"] == "pixel"


def teardown_module():
    # 清理模块级临时目录
    shutil.rmtree(_tmp_root, ignore_errors=True)
