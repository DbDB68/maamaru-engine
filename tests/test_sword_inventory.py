# -*- coding: utf-8 -*-
"""刀帐盘点：图鉴解析、快照存储与老库迁移"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from touken.flows.sword_inventory import (  # noqa: E402
    _parse_row, _row_key, parse_album_tokens, parse_collected,
    parse_list_tokens, parse_owned, read_row_form_fact)
from touken.flows.team_roster import load_flower_templates  # noqa: E402
from touken.telemetry import TelemetryStore  # noqa: E402

HASEBE = "touken_118_heshikiri_hasebe"   # 压切长谷部（打刀，名册基线 2）
HIGEKIRI = "touken_107_higekiri"         # 髭切（太刀，动态涨花例外）


def _tok(text, x, y):
    return (text, (x, y))


# 一览第 1 页「安宅切」一行的真实坐标样本（2026-09-12 运行帧 OCR）。
# 等级(158) 和乱舞(175) 只差 17px，OCR 抖动就能翻序——标签锚定就是为此。
ROW_ATAGI = [
    _tok("胁", 201, 171), _tok("安宅切", 206, 215),
    _tok("刀剑", 423, 157), _tok("99 级", 495, 158),
    _tok("乱舞", 423, 174), _tok("1级", 495, 175),
    _tok("生存", 424, 197), _tok("40/40", 492, 198),
    _tok("疲劳", 425, 220), _tok("85/100", 488, 221),
    _tok("生存", 551, 167), _tok("45", 551, 206),
    _tok("打击", 603, 167), _tok("46", 604, 206),
    _tok("防御", 662, 167), _tok("54", 663, 206),
    _tok("机动", 716, 167), _tok("52", 718, 207),
    _tok("冲力", 770, 167), _tok("34", 771, 207),
    _tok("侦察", 827, 167), _tok("42", 828, 205),
    _tok("隐蔽", 883, 167), _tok("40", 883, 206),
    _tok("必杀", 936, 166), _tok("29", 937, 207),
    _tok("范围", 991, 166), _tok("狭", 989, 207),
    _tok("显现", 1062, 165), _tok("2024", 1062, 193), _tok("3/8", 1061, 216),
    _tok("裝备", 1134, 186), _tok("修行", 1207, 186),
]


class ParseRowTests(unittest.TestCase):
    def test_full_row_fields(self):
        row = _parse_row(ROW_ATAGI)
        self.assertIsNotNone(row)
        self.assertEqual(row["sword_id"], "touken_250_atagi_kiri")
        self.assertEqual(row["name_zh"], "安宅切")
        self.assertEqual(row["level"], 99)   # 刀剑等级，不是乱舞的 1
        self.assertEqual(row["tou_level"], 1)
        self.assertEqual((row["survival"], row["survival_max"]), (40, 40))
        self.assertEqual((row["fatigue"], row["fatigue_max"]), (85, 100))
        self.assertEqual(row["stats"]["生存"], 45)
        self.assertEqual(row["stats"]["机动"], 52)
        self.assertEqual(row["stats"]["必杀"], 29)
        self.assertEqual(len(row["stats"]), 8)  # 范围「狭」是汉字不占数字槽
        self.assertEqual(row["kiwame_date"], "2024-3-8")

    def test_label_anchor_beats_y_jitter(self):
        # 等级和乱舞的 token y 被抖动互换后（乱舞读到更小的 y），
        # 标签锚定仍应把 99 给刀剑等级、1 给乱舞
        tokens = [(_tok[0], _tok[1]) for _tok in ROW_ATAGI]
        swapped = []
        for t, (x, y) in tokens:
            if t == "99 级":
                swapped.append(_tok(t, 495, 176))
            elif t == "1级":
                swapped.append(_tok(t, 495, 157))
            else:
                swapped.append(_tok(t, x, y))
        row = _parse_row(swapped)
        self.assertEqual(row["level"], 99)
        self.assertEqual(row["tou_level"], 1)

    def test_multiple_copies_are_distinct_rows(self):
        # 锻刀会堆出同名刀：石切丸 34 级和石切丸 1 级是两行，指纹必须不同
        mature = _parse_row(ROW_ATAGI)
        fresh = dict(mature, level=1, tou_level=1, survival=32,
                     survival_max=32, kiwame_date="2026-8-29")
        self.assertNotEqual(_row_key(mature), _row_key(fresh))
        self.assertEqual(_row_key(fresh), _row_key(dict(fresh)))

    def test_unreadable_row_counts_as_failure(self):
        row = _parse_row([
            _tok("???", 206, 215), _tok("99 级", 495, 158), _tok("40/40", 492, 198),
        ])
        self.assertEqual(row.get("_failed"), 1)
        self.assertIsNone(row["sword_id"])

    def test_blank_line_is_neither_row_nor_failure(self):
        result = parse_list_tokens([_tok("組织图", 21, 204), _tok("8", 103, 201)])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["fail_rows"], 0)

    def test_parse_owned(self):
        self.assertEqual(parse_owned("所持刀剑 196/200"), (196, 200))
        self.assertEqual(parse_owned("197 /200"), (197, 200))
        self.assertEqual(parse_owned("没读出来"), (None, None))


# 2026-09-12 刀帐图鉴真实运行帧的 OCR 输出（序号 39~50 一屏）。
# 注意：六个「极」字标实测只读出序号 42 那个——金字小标漏读是已知限制，
# 测试样本保持真实读数，不臆造没读出的 token。
ALBUM_SCREEN = [
    _tok("短", 137, 166), _tok("短", 137, 443),
    _tok("序号.39", 201, 130), _tok("前田藤四郎", 263, 217),
    _tok("序号.40", 388, 130), _tok("前田藤四郎", 450, 217),
    _tok("序号.41", 576, 130), _tok("秋田藤四郎", 637, 218),
    _tok("序号.42", 763, 130), _tok("秋田藤四郎", 825, 221), _tok("极", 826, 302),
    _tok("序号.43", 950, 130), _tok("博多藤四郎", 1010, 216),
    _tok("序号.44", 1138, 130), _tok("博多藤四郎", 1200, 220),
    _tok("序号.45", 202, 407), _tok("乱藤四郎", 263, 482),
    _tok("序号.46", 389, 406), _tok("乱藤四郎", 450, 482),
    _tok("序号.47", 576, 407), _tok("五虎退", 638, 467),
    _tok("序号.48", 763, 407), _tok("五虎退", 823, 467),
    _tok("序号.49", 950, 407), _tok("药研藤四郎", 1012, 493),
    _tok("序号.50", 1138, 407), _tok("药研藤四郎", 1199, 494),
]


class ParseAlbumTests(unittest.TestCase):
    def test_full_screen_twelve_cells(self):
        cells = parse_album_tokens(ALBUM_SCREEN)
        self.assertEqual(len(cells), 12)
        nos = [c["no"] for c in cells]
        self.assertEqual(nos, list(range(39, 51)))

    def test_kiwame_flag_when_ocr_reads_it(self):
        cells = {c["no"]: c for c in parse_album_tokens(ALBUM_SCREEN)}
        # 同名刀的普通/极化是两个图鉴条目：39 非极、40 极
        self.assertFalse(cells[39]["kiwame"])
        self.assertEqual(cells[39]["name_zh"], "前田藤四郎")
        self.assertEqual(cells[40]["name_zh"], "前田藤四郎")
        # 已知限制：金色小「极」字 OCR 漏读率高（一屏 6 个极实测只读出 1 个），
        # 极化状态允许缺报，但对账按格数走不受影响
        self.assertTrue(cells[42]["kiwame"])

    def test_missing_name_cell_is_skipped(self):
        # 空栏（未收集）：只有序号没有名字 → 不收，宁缺勿错
        tokens = [_tok("序号.99", 201, 130), _tok("短", 137, 166)]
        self.assertEqual(parse_album_tokens(tokens), [])

    def test_parse_collected(self):
        self.assertEqual(parse_collected("收集 204/208"), (204, 208))
        self.assertEqual(parse_collected("205 /208"), (205, 208))
        self.assertEqual(parse_collected("没读出来"), (None, None))


class RowFormFactTests(unittest.TestCase):
    """一览行徽章形态事实（read_row_form_fact）：合成帧 + 仓库真模板验证
    白名单门禁与结论规则（规则本体与编队页同一套，team_roster）。

    合成帧把模板原图贴进行 1（base_y=215）徽章位，匹配分必然接近 1.0，
    专测「结论怎么走」，不测「真机能不能读出」——后者靠一览同源真帧
    校准（_INV_PROVEN_FLOWER_COMBOS 注释里的流程）。"""

    BASE_Y = 215  # _ROW_NAME_YS[0]

    @classmethod
    def setUpClass(cls):
        cls.templates = load_flower_templates("resource/base")
        if not cls.templates:
            raise unittest.SkipTest("缺刀种花数模板资源")

    def _frame_with_badge(self, template_stem):
        import cv2
        import numpy as np
        img = np.full((720, 1280, 3), 235, dtype=np.uint8)
        for path, _flowers, _type in self.templates:
            if path.stem == template_stem:
                tpl = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8),
                                   cv2.IMREAD_COLOR)
                h, w = tpl.shape[:2]
                img[138:138 + h, 168:168 + w] = tpl  # 行 1 徽章实测位置
                return img
        raise AssertionError(f"模板不存在 {template_stem}")

    def test_normal_when_flowers_equal_base(self):
        # 压切长谷部（打刀基线 2）+ 二花打刀徽章 → 普通
        img = self._frame_with_badge("二花打刀")
        fact = read_row_form_fact(img, self.BASE_Y, HASEBE, self.templates,
                                  {("打刀", 2)})
        self.assertEqual(fact["status"], "normal")
        self.assertEqual(fact["badge"]["flowers"], 2)
        self.assertEqual(fact["sword_type"], "打刀")
        self.assertEqual(fact["rarity_base"], 2)
        self.assertTrue(any("花数2/基线2" in e for e in fact["evidence"]))

    def test_kiwame_when_flowers_above_base(self):
        # 压切长谷部（基线 2）+ 三花打刀徽章 → 极化
        img = self._frame_with_badge("三花打刀")
        fact = read_row_form_fact(img, self.BASE_Y, HASEBE, self.templates,
                                  {("打刀", 3)})
        self.assertEqual(fact["status"], "kiwame")
        self.assertEqual(fact["badge"]["flowers"], 3)

    def test_unproven_combo_stays_unknown_but_keeps_raw_observation(self):
        # 白名单外的达标匹配：不出结论，但原始观测（花数/分数）保留落盘
        img = self._frame_with_badge("二花打刀")
        fact = read_row_form_fact(img, self.BASE_Y, HASEBE, self.templates,
                                  frozenset())
        self.assertEqual(fact["status"], "unknown")
        self.assertEqual(fact["evidence"], [])
        self.assertEqual(fact["badge"]["conclusion"], "unproven_combo")
        self.assertEqual(fact["badge"]["observed_flowers"], 2)
        self.assertGreaterEqual(fact["badge"]["observed_score"], 0.7)

    def test_dynamic_flower_exception_never_concludes(self):
        # 髭切/膝丸普通形态随特阶段涨花：花数>基线也不区分极化
        img = self._frame_with_badge("三花太刀")
        fact = read_row_form_fact(img, self.BASE_Y, HIGEKIRI, self.templates,
                                  {("太刀", 3)})
        self.assertEqual(fact["status"], "unknown")
        self.assertTrue(any("花数3/基线2" in e for e in fact["evidence"]))

    def test_no_frame_or_wrong_identity_gives_unknown(self):
        # 截图失明：不出证据
        fact = read_row_form_fact(None, self.BASE_Y, HASEBE, self.templates,
                                  {("打刀", 2)})
        self.assertEqual(fact["status"], "unknown")
        self.assertEqual(fact["badge"]["conclusion"], "low_score")
        # 名册没有的身份：没有确认刀种，不产生花数证据
        img = self._frame_with_badge("二花打刀")
        fact = read_row_form_fact(img, self.BASE_Y, "touken_999_nobody",
                                  self.templates, {("打刀", 2)})
        self.assertEqual(fact["status"], "unknown")
        self.assertEqual(fact["badge"]["conclusion"], "no_confirmed_type")


class SwordSnapshotStoreTests(unittest.TestCase):
    def _store(self):
        return TelemetryStore(Path(tempfile.mkdtemp()) / "telemetry.db")

    def test_save_and_read_roundtrip(self):
        store = self._store()
        rows = [{
            "sword_id": "album_039", "name_zh": "前田藤四郎",
            "stats": {}, "page_no": 1,
        }, {
            "sword_id": "album_040", "name_zh": "前田藤四郎",
            "stats": {"极化": True}, "page_no": 1,
        }]
        snapshot_id = store.save_sword_snapshot(
            rows, owned=204, capacity=208, missing=202,
            captured_at=time.time())
        detail = store.sword_snapshot_detail(snapshot_id)
        self.assertEqual(detail["owned"], 204)
        self.assertEqual(detail["sword_count"], 2)
        self.assertEqual(detail["missing"], 202)
        self.assertEqual(detail["swords"][1]["stats"], {"极化": True})
        recent = store.recent_sword_snapshots()
        self.assertEqual(recent[0]["id"], snapshot_id)

    def test_legacy_db_without_sword_tables_gets_them(self):
        # 老库（只有 v8 时代的表）被新代码打开后，快照表自动补建且老数据不丢
        import sqlite3
        db = Path(tempfile.mkdtemp()) / "telemetry.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE runs (run_id TEXT PRIMARY KEY, script TEXT NOT NULL,
                started_at REAL NOT NULL, ended_at REAL,
                status TEXT NOT NULL DEFAULT 'running', label TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL, run_id TEXT, script TEXT, event_type TEXT, payload TEXT);
            INSERT INTO runs(run_id, script, started_at, status)
                VALUES ('legacy_run', 'workflow', 1765500000, 'completed');
        """)
        conn.commit()
        conn.close()

        store = TelemetryStore(db)  # 打开即迁移
        snapshot_id = store.save_sword_snapshot(
            [{"sword_id": "album_003", "name_zh": "三日月宗近"}])
        self.assertEqual(store.sword_snapshot_detail(snapshot_id)["sword_count"], 1)
        # 老数据安然无恙
        check = sqlite3.connect(str(db))
        kept = check.execute(
            "SELECT script FROM runs WHERE run_id='legacy_run'").fetchone()
        check.close()
        self.assertEqual(kept[0], "workflow")

    def test_form_fact_roundtrip(self):
        # 形态事实随快照落盘：存进去什么读出来什么
        store = self._store()
        fact = {"status": "kiwame", "evidence": ["花数3/基线2"],
                "badge": {"flowers": 3, "score": 0.9,
                          "conclusion": "recognized"},
                "rarity_base": 2, "sword_type": "打刀"}
        snapshot_id = store.save_sword_snapshot(
            [{"sword_id": "touken_118_heshikiri_hasebe", "name_zh": "压切长谷部",
              "form_fact": fact}], owned=1, capacity=300, missing=0)
        row = store.sword_snapshot_detail(snapshot_id)["swords"][0]
        self.assertEqual(row["form_fact"], fact)
        # 没带形态事实的行落 NULL，读回 None
        snapshot_id = store.save_sword_snapshot(
            [{"sword_id": "album_003", "name_zh": "三日月宗近"}])
        row = store.sword_snapshot_detail(snapshot_id)["swords"][0]
        self.assertIsNone(row["form_fact"])

    def test_legacy_rows_table_gets_form_fact_column(self):
        # v10 时代的老库（行表无 form_fact）打开即补列；老行不丢、
        # 形态事实为 None（不回填不猜测：老快照没看过徽章就是没有）
        import sqlite3
        db = Path(tempfile.mkdtemp()) / "telemetry.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE sword_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at REAL NOT NULL, owned INTEGER, capacity INTEGER,
                sword_count INTEGER NOT NULL DEFAULT 0, missing INTEGER,
                source TEXT, completeness TEXT);
            CREATE TABLE sword_snapshot_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL, sword_id TEXT NOT NULL,
                name_zh TEXT NOT NULL, level INTEGER, tou_level INTEGER,
                survival INTEGER, survival_max INTEGER,
                fatigue INTEGER, fatigue_max INTEGER,
                stats TEXT NOT NULL DEFAULT '{}', kiwame_date TEXT,
                locked INTEGER, page_no INTEGER);
            INSERT INTO sword_snapshots(captured_at, owned, capacity,
                sword_count, missing, source, completeness)
                VALUES (100, 1, 300, 1, 0, 'owned_inventory', 'complete');
            INSERT INTO sword_snapshot_rows(snapshot_id, sword_id, name_zh,
                level, tou_level, survival, survival_max, fatigue, fatigue_max,
                stats, kiwame_date, locked, page_no)
                VALUES (1, 'touken_118_heshikiri_hasebe', '压切长谷部', 99, 1,
                        50, 50, 100, 100, '{}', '2024-01-01', 1, 1);
        """)
        conn.commit()
        conn.close()

        store = TelemetryStore(db)  # 打开即迁移
        detail = store.sword_snapshot_detail(1)
        self.assertEqual(detail["swords"][0]["name_zh"], "压切长谷部")
        self.assertIsNone(detail["swords"][0]["form_fact"])
        cols = {r["name"] for r in store._conn().execute(
            "PRAGMA table_info(sword_snapshot_rows)")}
        self.assertIn("form_fact", cols)


if __name__ == "__main__":
    unittest.main()
