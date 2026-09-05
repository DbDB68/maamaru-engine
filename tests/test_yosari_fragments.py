# -*- coding: utf-8 -*-
"""异去碎片库存弹窗：OCR 词元解析 + 配置补键契约。"""
import json
import tempfile
import unittest
from pathlib import Path

from touken.flows.sortie import _parse_fragment_counts, _parse_popup_map
from touken.runtime_paths import ensure_runtime_data

# 2026-09-05 1-4 鸟羽弹窗实测 OCR 词元（运行帧 1280x720）
REAL_TOKENS = [
    ("可以获得的宝物碎片", 642, 55), ("只显示未持有", 153, 111),
    ("维新的记忆", 811, 113), ("四", 934, 113), ("鸟羽", 984, 114),
    ("首领点", 81, 228), ("曜变天目碎片", 244, 248),
    ("所持", 201, 291), ("3 个", 276, 292),
    ("通常点", 80, 404), ("4", 460, 366),  # 徽章噪声：无“个”不配对
    ("狮子螺钿鞍碎片", 249, 425), ("所持", 205, 467), ("0个", 279, 467),
    ("南蛮胴具足碎片", 460, 425), ("所持", 416, 467), ("0个", 491, 467),
    ("锷·月下梅树透图碎片", 670, 424), ("所持", 627, 467), ("3 个", 702, 467),
    ("三所物·菊碎片", 883, 423), ("所持", 839, 467), ("4个", 914, 467),
    ("三所物·狮子碎片", 1094, 423), ("所持", 1049, 467), ("1个", 1125, 467),
]


class FragmentParseTests(unittest.TestCase):
    def test_real_popup_tokens(self):
        counts = _parse_fragment_counts(REAL_TOKENS)
        self.assertEqual(counts, {
            "曜变天目碎片": 3, "狮子螺钿鞍碎片": 0, "南蛮胴具足碎片": 0,
            "锷·月下梅树透图碎片": 3, "三所物·菊碎片": 4, "三所物·狮子碎片": 1,
        })

    def test_title_excluded(self):
        # 标题“可以获得的宝物碎片”也以“碎片”结尾，但 y<150 不许进结果
        counts = _parse_fragment_counts(REAL_TOKENS)
        self.assertNotIn("可以获得的宝物碎片", counts)

    def test_long_text_with_个_not_a_count(self):
        tokens = [("曜变天目碎片", 244, 248), ("每天5：00恢复3个", 244, 292)]
        self.assertEqual(_parse_fragment_counts(tokens), {})

    def test_unpaired_name_omitted(self):
        tokens = [("曜变天目碎片", 244, 248), ("狮子螺钿鞍碎片", 249, 425),
                  ("0个", 279, 467)]
        self.assertEqual(_parse_fragment_counts(tokens), {"狮子螺钿鞍碎片": 0})

    def test_map_indicator(self):
        self.assertEqual(_parse_popup_map(REAL_TOKENS), 4)
        self.assertIsNone(_parse_popup_map([("可以获得的宝物碎片", 642, 55)]))


class FragmentConfigKeyfillTests(unittest.TestCase):
    """新增 yosari.fragments_* 配置键必须能补进老安装（8-22 哑跑事故规矩）。"""

    def test_example_config_carries_fragment_keys(self):
        example = json.loads(Path("touken_config.example.json")
                             .read_text(encoding="utf-8-sig"))
        yosari = example["yosari"]
        self.assertIn("fragments_button", yosari)
        popup = yosari["fragments_popup"]
        for key in ("title_expected", "ocr_roi", "close"):
            self.assertIn(key, popup)

    def test_old_yosari_section_gets_fragment_keys_filled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "program"
            (bundle / "panel").mkdir(parents=True)
            (bundle / "profiles").mkdir()
            (bundle / "touken_config.example.json").write_text(json.dumps({
                "yosari": {
                    "entry": {"target": [1, 2]},
                    "fragments_button": [895, 632],
                    "fragments_popup": {"close": [1255, 30]},
                },
            }, ensure_ascii=False), encoding="utf-8")
            (bundle / "panel" / "panel_config.example.json").write_text('{}', encoding="utf-8")
            (bundle / "panel" / "expedition_schedule.json").write_text('{}', encoding="utf-8")
            data = root / "user-data"
            (data / "config").mkdir(parents=True)
            target = data / "config" / "touken.json"
            target.write_text(json.dumps({
                "yosari": {"entry": {"target": [9, 9]}},
            }, ensure_ascii=False), encoding="utf-8")

            ensure_runtime_data(data, bundle, legacy_roots=[])

            merged = json.loads(target.read_text(encoding="utf-8"))
            # 新键补齐，老值不动
            self.assertEqual(merged["yosari"]["fragments_button"], [895, 632])
            self.assertEqual(merged["yosari"]["fragments_popup"], {"close": [1255, 30]})
            self.assertEqual(merged["yosari"]["entry"], {"target": [9, 9]})


if __name__ == "__main__":
    unittest.main()
