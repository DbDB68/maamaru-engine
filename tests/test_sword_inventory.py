# -*- coding: utf-8 -*-
"""刀帐盘点：图鉴解析、快照存储与老库迁移"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from touken.flows.sword_inventory import (  # noqa: E402
    parse_album_tokens, parse_collected)
from touken.telemetry import TelemetryStore  # noqa: E402


def _tok(text, x, y):
    return (text, (x, y))


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


if __name__ == "__main__":
    unittest.main()
