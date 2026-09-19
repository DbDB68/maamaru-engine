# -*- coding: utf-8 -*-
"""代码 ROI 注册表 + 覆盖层测试。

覆盖：默认回落、存取往返、返回 tuple 约定、坏覆盖静默回落、save 拒非法
矩形、删除恢复默认且幂等、mtime 缓存失效重读；注册表条目健全性；
注册表 default 与流程代码常量逐一对齐（防漂移）。

隔离红线（照 test_template_lab.py 惯例）：模块头的 MAAMARU_DATA_DIR 环境
补丁只为 import touken 系模块用，全量跑时可能已失效——真正的隔离靠每个
用例 patch roi_overrides.DEBUG_DIR 到临时目录。import 顺序有讲究：先注册表
再 sword_inventory，常量接线发生在 import 那一刻（模块 tmp 目录里没有
覆盖文件，常量必等于注册表默认，漂移测试才成立）。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_module_tmp = tempfile.TemporaryDirectory(prefix="roi_overrides_module_test_")
with patch.dict("os.environ", {"MAAMARU_DATA_DIR": _module_tmp.name}):
    from touken import roi_overrides
    from touken.flows import formation_editor, smith, sortie, sword_inventory
    from touken.roi_registry import ROI_REGISTRY


def _overrides_path(debug_dir: Path) -> Path:
    return debug_dir / "template_lab" / "code-rois.json"


class OverrideStorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="roi_overrides_test_")
        self.addCleanup(self._tmp.cleanup)
        self.debug_dir = Path(self._tmp.name) / "debug"
        self._patches = [patch.object(roi_overrides, "DEBUG_DIR", self.debug_dir)]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_get_roi_falls_back_to_default_without_override(self):
        self.assertEqual(roi_overrides.get_roi("sword_inventory.title",
                                               (1, 2, 3, 4)), (1, 2, 3, 4))

    def test_save_and_get_override_roundtrip(self):
        roi_overrides.save_override("sword_inventory.title", [100, 10, 500, 60])
        self.assertEqual(roi_overrides.get_roi("sword_inventory.title",
                                               (1, 2, 3, 4)), (100, 10, 500, 60))
        # 落盘格式 {id: [x1,y1,x2,y2]}
        data = json.loads(_overrides_path(self.debug_dir).read_text(encoding="utf-8"))
        self.assertEqual(data, {"sword_inventory.title": [100, 10, 500, 60]})
        self.assertEqual(roi_overrides.list_overrides(),
                         {"sword_inventory.title": (100, 10, 500, 60)})

    def test_get_roi_returns_tuple_even_for_list_default(self):
        roi_overrides.save_override("sword_inventory.title", [1, 2, 3, 4])
        rect = roi_overrides.get_roi("sword_inventory.title", [9, 9, 9, 9])
        self.assertIsInstance(rect, tuple)
        self.assertEqual(rect, (1, 2, 3, 4))

    def test_bad_overrides_fall_back_silently(self):
        path = _overrides_path(self.debug_dir)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "sword_inventory.title": [500, 10, 100, 60],   # x1>x2
            "sword_inventory.owned": [100, 10, 500],        # 少一条
            "sword_inventory.list": [100, 10, 500, 900],    # y2 越界
            "smith.capacity": ["a", 1, 2, 3],               # 非数字
            "sortie.name_plate": [0, 480, 430, True],       # bool 不算 int
            "formation_editor.list": None,                  # 根本不是矩形
        }), encoding="utf-8")
        for roi_id, default in (
                ("sword_inventory.title", (400, 15, 880, 50)),
                ("sword_inventory.owned", (640, 15, 1065, 50)),
                ("sword_inventory.list", (130, 145, 1120, 660)),
                ("smith.capacity", (960, 45, 1100, 85)),
                ("sortie.name_plate", (0, 480, 430, 710)),
                ("formation_editor.list", (60, 100, 1240, 700))):
            self.assertEqual(roi_overrides.get_roi(roi_id, default), default, roi_id)
        self.assertEqual(roi_overrides.list_overrides(), {})

    def test_save_override_rejects_bad_rect(self):
        for bad in ([1, 2, 3], [100, 10, 50, 60], [-1, 0, 10, 10],
                    [0, 0, 1281, 10], [0, 0, 10, 721], [0.5, 0, 10, 10],
                    [0, 0, 10, True], "1234", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                roi_overrides.save_override("sword_inventory.title", bad)
        self.assertFalse(_overrides_path(self.debug_dir).exists())

    def test_delete_override_restores_default_and_is_idempotent(self):
        roi_overrides.save_override("sword_inventory.title", [1, 2, 3, 4])
        self.assertIs(roi_overrides.delete_override("sword_inventory.title"), True)
        self.assertEqual(roi_overrides.get_roi("sword_inventory.title",
                                               (400, 15, 880, 50)),
                         (400, 15, 880, 50))
        self.assertEqual(roi_overrides.list_overrides(), {})
        # 再删一次：没有这条也算完事
        self.assertIs(roi_overrides.delete_override("sword_inventory.title"), False)

    def test_external_edit_is_picked_up_via_mtime(self):
        roi_overrides.save_override("sword_inventory.title", [1, 2, 3, 4])
        self.assertEqual(roi_overrides.get_roi("sword_inventory.title",
                                               (9, 9, 9, 9)), (1, 2, 3, 4))
        # 面板外的手改（mtime 变了）下一次读必须生效
        path = _overrides_path(self.debug_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["sword_inventory.title"] = [5, 6, 7, 8]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(roi_overrides.get_roi("sword_inventory.title",
                                               (9, 9, 9, 9)), (5, 6, 7, 8))


class RegistryShapeTests(unittest.TestCase):
    def test_entries_are_wellformed(self):
        ids = set()
        for entry in ROI_REGISTRY:
            self.assertEqual(set(entry),
                             {"id", "label", "used_in", "purpose", "default"},
                             entry)
            self.assertNotIn(entry["id"], ids, "注册表 id 重复")
            ids.add(entry["id"])
            self.assertIsInstance(entry["default"], tuple)
            self.assertTrue(roi_overrides._is_valid_rect(entry["default"]),
                            f"{entry['id']} 默认矩形不合法")
            self.assertIn(":", entry["used_in"], "used_in 要写到 文件:行号")

    def test_effective_rois_merges_registry_and_overrides(self):
        with tempfile.TemporaryDirectory(prefix="roi_overrides_eff_test_") as tmp:
            with patch.object(roi_overrides, "DEBUG_DIR", Path(tmp) / "debug"):
                roi_overrides.save_override("smith.capacity", [1, 2, 3, 4])
                rois = {item["id"]: item for item in roi_overrides.effective_rois()}
        title = rois["sword_inventory.title"]
        self.assertEqual(set(title),
                         {"id", "label", "used_in", "purpose", "default",
                          "override", "effective", "overridden"})
        self.assertEqual(title["default"], [400, 15, 880, 50])
        self.assertIsNone(title["override"])
        self.assertEqual(title["effective"], [400, 15, 880, 50])
        self.assertIs(title["overridden"], False)
        capacity = rois["smith.capacity"]
        self.assertEqual(capacity["override"], [1, 2, 3, 4])
        self.assertEqual(capacity["effective"], [1, 2, 3, 4])
        self.assertIs(capacity["overridden"], True)


class RegistryDriftTests(unittest.TestCase):
    def test_registry_defaults_match_code_constants(self):
        """注册表 default 与流程写死的常量逐一对齐，谁偷偷改了谁翻车。"""
        pairs = [
            ("sword_inventory.title", sword_inventory._TITLE_ROI),
            ("sword_inventory.owned", sword_inventory._OWNED_ROI),
            ("sword_inventory.list", sword_inventory._LIST_ROI),
            ("sword_inventory.album_title", sword_inventory._ALBUM_TITLE_ROI),
            ("sword_inventory.album_collect", sword_inventory._COLLECT_ROI),
            ("sword_inventory.album_grid", sword_inventory._GRID_ROI),
            ("formation_editor.list", formation_editor._LIST_ROI),
            ("smith.capacity", smith.SmithMixin._CAPACITY_ROI),
            ("smith.board_name", smith.SmithMixin._BOARD_NAME_ROI),
            ("smith.board_mark", smith.SmithMixin._BOARD_MARK_ROI),
            ("sortie.obtain_banner", sortie.SortieMixin._OBTAIN_BANNER_ROI),
            ("sortie.name_plate", sortie.SortieMixin._NAME_PLATE_ROI),
        ]
        defaults = {entry["id"]: entry["default"] for entry in ROI_REGISTRY}
        for roi_id, constant in pairs:
            self.assertEqual(tuple(constant), defaults[roi_id], roi_id)


if __name__ == "__main__":
    unittest.main()
