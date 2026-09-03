import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


# server 模块导入时会准备数据目录；整个测试模块都把它留在临时目录里，
# 避免测试收集阶段触碰真实 LOCALAPPDATA。
_module_tmp = tempfile.TemporaryDirectory(prefix="ledger_app_module_test_")
_module_root = Path(_module_tmp.name)
with patch.dict(os.environ, {"MAAMARU_DATA_DIR": str(_module_root)}):
    from fastapi.testclient import TestClient

    from ledger_app.server import create_app
    from touken import telemetry


class _TestTelemetryStore(telemetry.TelemetryStore):
    """测试请求跨线程执行，复用一个允许跨线程访问的连接以便可靠清理。"""

    def _conn(self):
        conn = getattr(self, "_test_conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._test_conn = conn
        return conn

    def close(self):
        conn = getattr(self, "_test_conn", None)
        if conn is not None:
            conn.close()
            self._test_conn = None


class LedgerAppTests(unittest.TestCase):
    def setUp(self):
        """每个测试使用独立数据目录与 telemetry 数据库。"""
        from ledger_app import server
        from touken import runtime_paths

        self._tmp = tempfile.TemporaryDirectory(prefix="ledger_app_test_")
        self._tmp_path = Path(self._tmp.name)
        self._env_patch = patch.dict(os.environ, {"MAAMARU_DATA_DIR": str(self._tmp_path)})
        self._env_patch.start()
        importlib.reload(runtime_paths)

        self._server = server
        self._runtime_paths = runtime_paths
        self._server_patchers = [
            patch.object(server, "DATA_ROOT", runtime_paths.DATA_ROOT),
            patch.object(server, "STATE_DIR", runtime_paths.STATE_DIR),
            patch.object(server, "LOG_DIR", runtime_paths.LOG_DIR),
            patch.object(server, "BACKUP_DIR", runtime_paths.BACKUP_DIR),
            patch.object(server, "CONFIG_PATH", runtime_paths.CONFIG_PATH),
            patch.object(server, "_SETTINGS_FILE", runtime_paths.STATE_DIR / "ledger_settings.json"),
        ]
        for patcher in self._server_patchers:
            patcher.start()

        db_path = runtime_paths.LOG_DIR / "telemetry.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._store = _TestTelemetryStore(db_path)
        self._store_patch = patch.object(telemetry, "_store", self._store)
        self._store_patch.start()
        self.client = TestClient(create_app())

    def tearDown(self):
        self.client.close()
        self._store.close()
        self._store_patch.stop()
        for patcher in reversed(self._server_patchers):
            patcher.stop()
        self._env_patch.stop()
        with patch.dict(os.environ, {"MAAMARU_DATA_DIR": str(_module_root)}):
            importlib.reload(self._runtime_paths)
        self._tmp.cleanup()

    def test_app_mode_is_ledger(self):
        resp = self.client.get("/api/app-mode")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"mode": "ledger"})

    def test_resource_ledger_empty_is_valid(self):
        resp = self.client.get("/api/data/resource-ledger")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("per_resource", data)
        self.assertIn("daily_series", data)
        self.assertIn("schema_version", data)
        resources = {item["resource"] for item in data["per_resource"]}
        for name in ("木炭", "玉钢", "冷却材", "砥石", "小判", "甲州金", "委托符", "加速符"):
            self.assertIn(name, resources)

    def test_ledger_onboarding_empty_is_valid(self):
        resp = self.client.get("/api/data/ledger-onboarding")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["visible"])
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["step"], 1)

    def test_static_fallback_when_no_build(self):
        """静态目录不存在时，/ 返回兜底 HTML，而不是 500。"""
        with patch.object(self._server, "_STATIC", self._tmp_path / "nonexistent_static"):
            test_client = TestClient(create_app())
            try:
                resp = test_client.get("/")
            finally:
                test_client.close()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("前端构建产物还没放进来", resp.text)

    def test_config_lists_with_missing_config(self):
        resp = self.client.get("/api/config-lists")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("sword_wishlist", data)
        self.assertEqual(data["sword_wishlist"], [])

    def test_wishlist_roundtrip_preserves_other_config(self):
        self._server.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._server.CONFIG_PATH.write_text(json.dumps({
            "repair": {"blacklist": ["岩融"]},
            "daily": {"enabled": True},
        }, ensure_ascii=False), encoding="utf-8")

        resp = self.client.post("/api/config-lists", json={
            "sword_wishlist": [" 姬鹤一文字 ", "", "道誉一文字", "姬鹤一文字"],
            "repair_blacklist": ["不该被纯净账房改动"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["sword_wishlist"], ["姬鹤一文字", "道誉一文字"])

        saved = json.loads(self._server.CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["sword_wishlist"], ["姬鹤一文字", "道誉一文字"])
        self.assertEqual(saved["repair"]["blacklist"], ["岩融"])
        self.assertEqual(saved["daily"], {"enabled": True})

    def test_swords_endpoint_supplies_wishlist_candidates(self):
        resp = self.client.get("/api/swords")
        self.assertEqual(resp.status_code, 200)
        swords = resp.json()["swords"]
        self.assertGreater(len(swords), 100)
        self.assertTrue(any(item["name_zh"] == "姬鹤一文字" and item["type"] == "太刀" for item in swords))

    def test_saved_settings_roundtrip(self):
        resp = self.client.post("/api/saved-settings", json={"theme": "pixel", "hero_resource": "玉钢"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

        resp = self.client.get("/api/saved-settings")
        self.assertEqual(resp.json()["theme"], "pixel")
        self.assertEqual(resp.json()["hero_resource"], "玉钢")

    def test_custom_goal_roundtrip(self):
        created = self.client.post("/api/planning/goals", json={
            "goal_mode": "amount_target", "resource": "玉钢",
            "target": 100_000, "note": "下一轮锻刀",
        })
        self.assertEqual(created.status_code, 200)
        goal_id = created.json()["goal"]["id"]

        planning = self.client.get("/api/planning")
        self.assertEqual(planning.status_code, 200)
        goal = next(item for item in planning.json()["goals"] if item["id"] == goal_id)
        self.assertEqual(goal["resource"], "玉钢")
        self.assertEqual(goal["target"], 100_000)
        self.assertEqual(self.client.delete(f"/api/planning/goals/{goal_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/planning").json()["goals"], [])

    def test_manual_resource_group_roundtrip(self):
        created = self.client.post("/api/data/human-reports/batch", json={
            "occurred_at": 1_700_000_000,
            "activities": ["领邮箱"],
            "note": "绿玩手账",
            "entries": {"小判": 1200, "木炭": -50},
        })
        self.assertEqual(created.status_code, 200)
        group_id = created.json()["group_id"]

        updated = self.client.put(f"/api/data/human-reports/group/{group_id}", json={
            "occurred_at": 1_700_000_100,
            "activities": ["手动领奖"],
            "note": "改好了",
            "entries": {"小判": 1300},
        })
        self.assertEqual(updated.status_code, 200)
        listing = self.client.get("/api/data/human-reports").json()["items"]
        self.assertEqual([(item["resource"], item["claimed_delta"]) for item in listing], [("小判", 1300)])

        self.assertEqual(self.client.delete(f"/api/data/human-reports/group/{group_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/data/human-reports").json()["items"], [])

    def test_manual_inventory_roundtrip(self):
        created = self.client.post("/api/data/manual-inventory", json={
            "observed_at": 1_700_000_000,
            "resources": {"小判": 50_000, "木炭": 12_000},
        })
        self.assertEqual(created.status_code, 200)
        event_id = created.json()["snapshot"]["id"]

        updated = self.client.put(f"/api/data/manual-inventory/{event_id}", json={
            "observed_at": 1_700_000_100,
            "resources": {"小判": 51_000},
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["snapshot"]["resources"], {"小判": 51_000})
        self.assertEqual(self.client.delete(f"/api/data/manual-inventory/{event_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/data/manual-inventory").json()["items"], [])

    def test_manual_session_roundtrip(self):
        created = self.client.post("/api/data/manual-sessions", json={
            "script": "edocastle", "started_at": 1_700_000_000,
            "ended_at": 1_700_003_600, "loops": 6, "note": "自己打的",
        })
        self.assertEqual(created.status_code, 200)
        session_id = created.json()["item"]["id"]

        updated = self.client.put(f"/api/data/manual-sessions/{session_id}", json={
            "script": "edocastle", "started_at": 1_700_000_000,
            "ended_at": 1_700_004_200, "loops": 7, "note": "多打一圈",
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["item"]["loops"], 7)
        self.assertEqual(self.client.delete(f"/api/data/manual-sessions/{session_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/data/manual-sessions").json()["items"], [])


def tearDownModule():
    _module_tmp.cleanup()
