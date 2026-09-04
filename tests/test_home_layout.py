# -*- coding: utf-8 -*-
"""执务页常用功能自定义布局后端测试。

覆盖：默认回落（无文件）、order 排序生效、hidden 生效、新 key 自动追加末尾、
wf: 悬空丢弃、读写往返、坏 JSON 容错、非法 body 400（API 层）。

隔离红线（9-04 血泪）：一律 patch `panel.home_layout.STATUS_DIR` 到临时目录；
涉及工作流预设的用例连同 `panel.workflow.STATUS_DIR` 一起 patch。
模块头的 MAAMARU_DATA_DIR 环境补丁只为 import panel.server 注册脚本用，
全量跑时可能已失效——真正的隔离靠 patch STATUS_DIR 本身。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# server 模块导入时填充脚本注册表 _SCRIPTS；在临时数据目录下做，
# 不碰真实用户数据（与 tests/test_workflow.py 同款写法）。
_module_tmp = tempfile.TemporaryDirectory(prefix="home_layout_module_test_")
with patch.dict("os.environ", {"MAAMARU_DATA_DIR": _module_tmp.name}):
    import panel.server  # noqa: F401  (import 即完成脚本注册)
    from panel import home_layout, workflow
    from panel.script_runner import _SCRIPTS


def _preset(preset_id, name):
    return {"id": preset_id, "name": name, "nodes": [], "after": "none"}


class HomeLayoutStoreTests(unittest.TestCase):
    """纯存储/解析层：patch home_layout.STATUS_DIR 即可。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="home_layout_test_")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self._patch = patch.object(home_layout, "STATUS_DIR", self.dir)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _save(self, order, hidden):
        home_layout.save_layout({"order": order, "hidden": hidden})

    def test_default_fallback_when_no_file(self):
        layout = home_layout.load_layout()
        self.assertEqual(layout["order"], home_layout.DEFAULT_ORDER)
        self.assertEqual(layout["hidden"], [])
        # resolve：DEFAULT_ORDER 里注册了的关键都在，且保持清单顺序
        keys = [e["key"] for e in home_layout.resolve_layout()]
        known = [k for k in home_layout.DEFAULT_ORDER if k in _SCRIPTS]
        self.assertEqual(keys[:len(known)], known)

    def test_order_sorting_applies(self):
        self._save(["osaka", "daily"], [])
        keys = [e["key"] for e in home_layout.resolve_layout()]
        self.assertEqual(keys[:2], ["osaka", "daily"])

    def test_hidden_items_dropped_from_entries(self):
        self._save(["daily", "sortie"], ["daily"])
        keys = [e["key"] for e in home_layout.resolve_layout()]
        self.assertNotIn("daily", keys)
        self.assertIn("sortie", keys)

    def test_unlisted_script_appended_at_end(self):
        self._save(["daily"], [])
        keys = [e["key"] for e in home_layout.resolve_layout()]
        self.assertEqual(keys[0], "daily")
        tail = keys[1:]
        self.assertTrue(tail)  # 其余注册脚本自动追加在末尾
        self.assertEqual(len(tail), len(set(tail)))  # 不重复

    def test_dangling_keys_silently_dropped(self):
        self._save(["nonsense", "wf:deadbeef", "daily"], [])
        keys = [e["key"] for e in home_layout.resolve_layout()]
        self.assertEqual(keys[0], "daily")
        self.assertNotIn("nonsense", keys)
        self.assertNotIn("wf:deadbeef", keys)

    def test_read_write_roundtrip(self):
        self._save(["daily", "wf:abc123"], ["pumpkin"])
        self.assertEqual(home_layout.load_layout(),
                         {"order": ["daily", "wf:abc123"], "hidden": ["pumpkin"]})

    def test_bad_json_backed_up_and_falls_back(self):
        path = self.dir / "home_layout.json"
        path.write_text("{broken", encoding="utf-8")
        layout = home_layout.load_layout()
        self.assertEqual(layout["order"], home_layout.DEFAULT_ORDER)
        bad_files = list(self.dir.glob("home_layout.json.bad-*"))
        self.assertEqual(len(bad_files), 1)
        self.assertEqual(bad_files[0].read_text(encoding="utf-8"), "{broken")

    def test_non_list_fields_fall_back_to_default(self):
        path = self.dir / "home_layout.json"
        path.write_text(json.dumps({"order": "daily", "hidden": []}),
                        encoding="utf-8")
        self.assertEqual(home_layout.load_layout()["order"],
                         home_layout.DEFAULT_ORDER)

    def test_normalize_rejects_bad_shapes_and_overlap(self):
        with self.assertRaises(home_layout.HomeLayoutError):
            home_layout.normalize_layout({"order": "daily", "hidden": []})
        with self.assertRaises(home_layout.HomeLayoutError):
            home_layout.normalize_layout({"order": ["daily", 1], "hidden": []})
        with self.assertRaises(home_layout.HomeLayoutError):
            home_layout.normalize_layout({"order": ["daily"], "hidden": ["daily"]})
        # 去重是正常化的一部分，不报错
        self.assertEqual(
            home_layout.normalize_layout({"order": ["daily", "daily"],
                                          "hidden": []})["order"],
            ["daily"])


class HomeLayoutWorkflowEntryTests(unittest.TestCase):
    """wf: 项解析：预设存在则带名字出现，预设被删则静默消失。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="home_layout_wf_test_")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self._patches = [
            patch.object(home_layout, "STATUS_DIR", self.dir),
            patch.object(workflow, "STATUS_DIR", self.dir),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_pinned_workflow_resolves_with_preset_name(self):
        workflow.save_presets([_preset("abc123", "江户城+异去")])
        home_layout.save_layout({"order": ["wf:abc123", "daily"], "hidden": []})
        entries = home_layout.resolve_layout()
        self.assertEqual(entries[0], {"kind": "workflow", "key": "wf:abc123",
                                      "label": "江户城+异去"})
        self.assertEqual(entries[1]["kind"], "script")

    def test_deleted_preset_drops_wf_entry(self):
        home_layout.save_layout({"order": ["wf:abc123", "daily"], "hidden": []})
        keys = [e["key"] for e in home_layout.resolve_layout()]
        self.assertEqual(keys[0], "daily")
        self.assertNotIn("wf:abc123", keys)

    def test_unpinned_workflows_do_not_auto_appear(self):
        workflow.save_presets([_preset("abc123", "江户城+异去")])
        home_layout.save_layout({"order": ["daily"], "hidden": []})
        keys = [e["key"] for e in home_layout.resolve_layout()]
        self.assertNotIn("wf:abc123", keys)


class HomeLayoutApiTests(unittest.TestCase):
    """HTTP 契约：前端按这个形状开发。"""

    def setUp(self):
        from fastapi.testclient import TestClient
        self._tmp = tempfile.TemporaryDirectory(prefix="home_layout_api_test_")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self._patches = [
            patch.object(home_layout, "STATUS_DIR", self.dir),
            patch.object(workflow, "STATUS_DIR", self.dir),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(panel.server.app)
        self.addCleanup(self.client.close)

    def test_get_returns_default_layout(self):
        r = self.client.get("/api/home-layout")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["order"], home_layout.DEFAULT_ORDER)
        self.assertEqual(body["hidden"], [])
        kinds = {e["kind"] for e in body["entries"]}
        self.assertEqual(kinds, {"script"})

    def test_put_then_get_roundtrip(self):
        r = self.client.put("/api/home-layout",
                            json={"order": ["osaka", "daily", "wf:abc123"],
                                  "hidden": ["pumpkin"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])

        r = self.client.get("/api/home-layout")
        body = r.json()
        self.assertEqual(body["order"], ["osaka", "daily", "wf:abc123"])
        self.assertEqual(body["hidden"], ["pumpkin"])
        # wf:abc123 预设不存在 → 悬空丢弃；pumpkin 被藏起来
        keys = [e["key"] for e in body["entries"]]
        self.assertEqual(keys[:2], ["osaka", "daily"])
        self.assertNotIn("wf:abc123", keys)
        self.assertNotIn("pumpkin", keys)

    def test_put_with_pinned_workflow_entry(self):
        workflow.save_presets([_preset("abc123", "江户城+异去")])
        r = self.client.put("/api/home-layout",
                            json={"order": ["wf:abc123"], "hidden": []})
        self.assertEqual(r.status_code, 200, r.text)
        entries = r.json()["entries"]
        self.assertEqual(entries[0], {"kind": "workflow", "key": "wf:abc123",
                                      "label": "江户城+异去"})

    def test_invalid_body_is_400_and_not_persisted(self):
        for bad in ({}, {"order": "daily", "hidden": []},
                    {"order": ["daily"], "hidden": "x"},
                    {"order": ["daily"], "hidden": ["daily"]}):
            r = self.client.put("/api/home-layout", json=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertFalse(r.json()["ok"])
        self.assertFalse((self.dir / "home_layout.json").exists())

    def test_put_invalid_json_is_400(self):
        r = self.client.put("/api/home-layout", content="{broken",
                            headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse((self.dir / "home_layout.json").exists())
