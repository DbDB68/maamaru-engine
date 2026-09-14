# -*- coding: utf-8 -*-
"""当前本丸共用档案 · 事实层契约测试（honmaru_profile）。

钉死的规矩：
- 图鉴（album）快照永远不是候选池；较新残缺/来源不明盘点不覆盖旧完整盘点
- 一振一行，同名多振不合并；observation_id 只在快照内有效
- 编队槽链接：证据唯一才 linked，同名多振 ambiguous，没身份/没候选 unknown
- unknown 字段不补默认值，原始观察原样保留
"""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from touken.honmaru_profile import (PROFILE_SCHEMA_VERSION,
                                    build_candidate_pool, build_honmaru_profile,
                                    formation_conflicts)
from touken.telemetry import TelemetryStore


def _store() -> TelemetryStore:
    return TelemetryStore(Path(tempfile.mkdtemp()) / "telemetry.db")


def _row(catalog_id, name, **kw):
    row = {"sword_id": catalog_id, "name_zh": name, "level": 99,
           "tou_level": 1, "survival": 50, "survival_max": 50,
           "fatigue": 100, "fatigue_max": 100, "stats": {"打击": 55},
           "kiwame_date": None, "locked": 1, "page_no": 1}
    row.update(kw)
    return row


def _owned_snapshot(store, rows, *, captured_at, owned=None, missing=0,
                    source="owned_inventory"):
    return store.save_sword_snapshot(
        rows, owned=owned if owned is not None else len(rows), capacity=300,
        missing=missing, captured_at=captured_at, source=source)


def _roster_event(store, team_no, slots, ts):
    store.record_event("team_roster.observed", {
        "team_no": team_no, "slots": slots,
        "observation_status": "complete", "source": "formation_page",
    })
    # record_event 用当前时间；测试要控制新旧，直接改 ts
    store._conn().execute("UPDATE events SET ts = ? WHERE id = "
                          "(SELECT MAX(id) FROM events)", (ts,))
    store._conn().commit()


def _slot(slot, catalog_id="touken_003_mikazuki", name="三日月宗近",
          slot_status="occupied", **kw):
    base = {"slot": slot, "slot_status": slot_status, "name_raw": name,
            "name": name, "name_status": "recognized",
            "sword_catalog_id": catalog_id, "sword_type": "太刀",
            "level": 99, "fatigue": 100, "survival": 50, "survival_max": 50,
            "injury": "none", "kiwame_status": "normal", "unknown_fields": []}
    base.update(kw)
    return base


class CandidatePoolTests(unittest.TestCase):
    def test_album_snapshot_is_never_candidate_pool(self):
        store = _store()
        owned_id = _owned_snapshot(
            store, [_row("touken_003_mikazuki", "三日月宗近")], captured_at=100)
        store.save_sword_snapshot(
            [{"sword_id": "album_003", "name_zh": "三日月宗近", "stats": {}}],
            owned=204, capacity=208, missing=0, captured_at=200,
            source="album")
        pool = build_candidate_pool(store)
        self.assertTrue(pool["done"])
        self.assertEqual(pool["source"]["snapshot_id"], owned_id)
        self.assertEqual(pool["entries"][0]["name_zh"], "三日月宗近")
        self.assertEqual(pool["skipped_newer_snapshots"][0]["source"], "album")

    def test_newer_partial_inventory_does_not_override_last_complete(self):
        store = _store()
        good_id = _owned_snapshot(
            store, [_row("touken_003_mikazuki", "三日月宗近")], captured_at=100)
        _owned_snapshot(
            store, [_row("touken_005_kogitsunemaru", "小狐丸")],
            captured_at=200, owned=196, missing=195)  # 残缺：只认出 1/196
        pool = build_candidate_pool(store)
        self.assertTrue(pool["done"])
        self.assertEqual(pool["source"]["snapshot_id"], good_id)
        skipped = pool["skipped_newer_snapshots"]
        self.assertEqual(skipped[0]["completeness"], "partial")

    def test_unknown_source_snapshot_is_not_candidate_pool(self):
        store = _store()  # 调用方没申报来源 → unknown，不冒充盘点
        store.save_sword_snapshot(
            [_row("touken_003_mikazuki", "三日月宗近")],
            owned=1, capacity=300, missing=0, captured_at=100)
        pool = build_candidate_pool(store)
        self.assertFalse(pool["done"])
        self.assertEqual(pool["entries"], [])

    def test_same_name_copies_are_never_merged(self):
        store = _store()
        _owned_snapshot(store, [
            _row("touken_029_maeda", "前田藤四郎", level=99),
            _row("touken_029_maeda", "前田藤四郎", level=1),
        ], captured_at=100)
        pool = build_candidate_pool(store)
        self.assertEqual(len(pool["entries"]), 2)
        self.assertEqual([e["level"] for e in pool["entries"]], [99, 1])
        ids = [e["observation_id"] for e in pool["entries"]]
        self.assertEqual(len(set(ids)), 2)
        for entry in pool["entries"]:
            self.assertRegex(entry["observation_id"], r"^\d+:\d+$")

    def test_unknown_fields_are_listed_not_filled(self):
        store = _store()
        _owned_snapshot(store, [
            _row("touken_003_mikazuki", "三日月宗近",
                 level=None, fatigue=None, stats={}),
        ], captured_at=100)
        entry = build_candidate_pool(store)["entries"][0]
        self.assertIsNone(entry["level"])
        self.assertIsNone(entry["fatigue"])
        self.assertIn("level", entry["unknown_fields"])
        self.assertIn("fatigue", entry["unknown_fields"])
        self.assertIn("stats", entry["unknown_fields"])


class RosterLinkTests(unittest.TestCase):
    def _pool_store(self):
        store = _store()
        _owned_snapshot(store, [
            _row("touken_003_mikazuki", "三日月宗近"),
            _row("touken_029_maeda", "前田藤四郎", level=99),
            _row("touken_029_maeda", "前田藤四郎", level=1),
        ], captured_at=100)
        return store

    def test_unique_evidence_links(self):
        store = self._pool_store()
        _roster_event(store, 1, [_slot(1)], ts=300)
        profile = build_honmaru_profile(store)
        slot = profile["roster"]["teams"][0]["slots"][0]
        self.assertEqual(slot["link_status"], "linked")
        self.assertEqual(slot["match_basis"], "sword_catalog_id")
        pool_ids = [e["observation_id"]
                    for e in profile["candidate_pool"]["entries"]]
        self.assertIn(slot["observation_id"], pool_ids)
        # 原始观察原样保留
        self.assertEqual(slot["observed"]["name"], "三日月宗近")

    def test_same_name_member_is_ambiguous_not_first_match(self):
        store = self._pool_store()
        _roster_event(store, 1, [
            _slot(1, catalog_id="touken_029_maeda", name="前田藤四郎"),
        ], ts=300)
        slot = build_honmaru_profile(store)["roster"]["teams"][0]["slots"][0]
        self.assertEqual(slot["link_status"], "ambiguous")
        self.assertIsNone(slot["observation_id"])
        self.assertEqual(len(slot["candidate_ids"]), 2)

    def test_slot_without_identity_is_unknown(self):
        store = self._pool_store()
        _roster_event(store, 1, [
            _slot(1, catalog_id=None, name=None, name_status="unrecognized",
                  slot_status="occupied", unknown_fields=["identity"]),
        ], ts=300)
        slot = build_honmaru_profile(store)["roster"]["teams"][0]["slots"][0]
        self.assertEqual(slot["link_status"], "unknown")
        self.assertIn("身份", slot["link_reason"])

    def test_member_missing_from_pool_is_unknown(self):
        store = self._pool_store()
        _roster_event(store, 1, [
            _slot(1, catalog_id="touken_999_nobody", name="空想刀"),
        ], ts=300)
        slot = build_honmaru_profile(store)["roster"]["teams"][0]["slots"][0]
        self.assertEqual(slot["link_status"], "unknown")
        self.assertIn("候选池里没有", slot["link_reason"])

    def test_name_fallback_when_catalog_id_missing(self):
        store = self._pool_store()
        _roster_event(store, 1, [
            _slot(1, catalog_id=None, name="三日月宗近"),
        ], ts=300)
        slot = build_honmaru_profile(store)["roster"]["teams"][0]["slots"][0]
        self.assertEqual(slot["link_status"], "linked")
        self.assertEqual(slot["match_basis"], "name")

    def test_empty_slot_is_not_applicable(self):
        store = self._pool_store()
        _roster_event(store, 1, [
            _slot(1, slot_status="empty", catalog_id=None, name=None),
        ], ts=300)
        slot = build_honmaru_profile(store)["roster"]["teams"][0]["slots"][0]
        self.assertEqual(slot["link_status"], "not_applicable")

    def test_latest_event_per_team_wins(self):
        store = self._pool_store()
        _roster_event(store, 1, [_slot(1, name="三日月宗近")], ts=300)
        _roster_event(store, 1, [
            _slot(1, catalog_id="touken_029_maeda", name="前田藤四郎"),
        ], ts=400)
        team = build_honmaru_profile(store)["roster"]["teams"][0]
        self.assertEqual(team["observed_at"], 400)
        self.assertEqual(team["slots"][0]["link_status"], "ambiguous")

    def test_team_without_observation_is_unknown(self):
        store = self._pool_store()
        _roster_event(store, 2, [_slot(1)], ts=300)
        teams = build_honmaru_profile(store)["roster"]["teams"]
        self.assertEqual(teams[0]["observation_status"], "unknown")  # 部队1
        self.assertEqual(teams[1]["team_no"], 2)
        self.assertEqual(teams[1]["observation_status"], "complete")


class NoPoolTests(unittest.TestCase):
    def test_roster_observation_kept_when_pool_unavailable(self):
        store = _store()  # 只有图鉴，候选池不可用
        store.save_sword_snapshot(
            [{"sword_id": "album_003", "name_zh": "三日月宗近", "stats": {}}],
            owned=204, capacity=208, missing=0, captured_at=100, source="album")
        _roster_event(store, 1, [_slot(1)], ts=300)
        profile = build_honmaru_profile(store)
        self.assertFalse(profile["candidate_pool"]["done"])
        slot = profile["roster"]["teams"][0]["slots"][0]
        self.assertEqual(slot["link_status"], "unknown")
        self.assertIn("候选池不可用", slot["link_reason"])
        self.assertEqual(slot["observed"]["level"], 99)  # 原始观察还在


class LegacyMigrationTests(unittest.TestCase):
    """历史库（v9 及更早，没有 source/completeness 列）打开即回填分类。

    回填依据是行形态的确定证据：图鉴写入器的 sword_id 恒为 album_NNN，
    一览盘点恒为名册目录 id；混排/空快照无法可靠判断 → unknown。
    """

    def _legacy_db(self) -> Path:
        db = Path(tempfile.mkdtemp()) / "telemetry.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE sword_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at REAL NOT NULL,
                owned INTEGER, capacity INTEGER,
                sword_count INTEGER NOT NULL DEFAULT 0, missing INTEGER);
            CREATE TABLE sword_snapshot_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                sword_id TEXT NOT NULL, name_zh TEXT NOT NULL,
                level INTEGER, tou_level INTEGER, survival INTEGER,
                survival_max INTEGER, fatigue INTEGER, fatigue_max INTEGER,
                stats TEXT NOT NULL DEFAULT '{}', kiwame_date TEXT,
                locked INTEGER, page_no INTEGER);
        """)
        # 1: 完整盘点（目录 id 行） 2: 图鉴（album 行） 3: 混排（说不准）
        # 4: 空快照  5: 有缺口盘点
        conn.executemany(
            "INSERT INTO sword_snapshots(id, captured_at, owned, capacity, "
            "sword_count, missing) VALUES (?, ?, ?, ?, ?, ?)",
            [(1, 100, 2, 300, 2, 0), (2, 200, 204, 208, 1, 203),
             (3, 300, 3, 300, 3, 0), (4, 400, None, None, 0, None),
             (5, 500, 196, 300, 190, 6)])
        conn.executemany(
            "INSERT INTO sword_snapshot_rows(snapshot_id, sword_id, name_zh) "
            "VALUES (?, ?, ?)",
            [(1, "touken_003_mikazuki", "三日月宗近"),
             (1, "touken_005_kogitsunemaru", "小狐丸"),
             (2, "album_003", "三日月宗近"),
             (3, "touken_003_mikazuki", "三日月宗近"),
             (3, "album_005", "小狐丸"),
             (5, "touken_007_ishikirimaru", "石切丸")])
        conn.commit()
        conn.close()
        return db

    def test_legacy_rows_classified_by_row_shape_evidence(self):
        store = TelemetryStore(self._legacy_db())
        snaps = {s["id"]: s for s in store.recent_sword_snapshots(limit=10)}
        self.assertEqual(snaps[1]["source"], "owned_inventory")
        self.assertEqual(snaps[1]["completeness"], "complete")
        self.assertEqual(snaps[2]["source"], "album")
        self.assertEqual(snaps[2]["completeness"], "partial")
        self.assertEqual(snaps[3]["source"], "unknown")  # 混排不硬猜
        self.assertEqual(snaps[4]["source"], "unknown")  # 空快照不硬猜
        self.assertEqual(snaps[5]["source"], "owned_inventory")
        self.assertEqual(snaps[5]["completeness"], "partial")
        # 候选池晋升只看完整盘点：1 号当选，5 号残缺/2 号图鉴都踩在脚下
        pool = build_candidate_pool(store)
        self.assertTrue(pool["done"])
        self.assertEqual(pool["source"]["snapshot_id"], 1)

    def test_legacy_data_survives_migration_untouched(self):
        store = TelemetryStore(self._legacy_db())
        detail = store.sword_snapshot_detail(1)
        self.assertEqual([r["name_zh"] for r in detail["swords"]],
                         ["三日月宗近", "小狐丸"])
        self.assertEqual(detail["owned"], 2)
        # 行 id 暴露给 observation_id
        self.assertIn("row_id", detail["swords"][0])
        # 重复打开幂等：回填只碰 NULL，不覆盖已分类
        store.close()
        store2 = TelemetryStore(self._legacy_db().parent / "telemetry.db")
        snaps = {s["id"]: s for s in store2.recent_sword_snapshots(limit=10)}
        self.assertEqual(snaps[1]["source"], "owned_inventory")


class QueryWindowTests(unittest.TestCase):
    """可信档案走 SQL 无窗口查询：较新无效快照攒再多也挤不掉它。"""

    def test_pool_survives_200_newer_invalid_snapshots(self):
        store = _store()
        good_id = _owned_snapshot(
            store, [_row("touken_003_mikazuki", "三日月宗近")], captured_at=100)
        for i in range(230):  # 230 条较新的图鉴/残缺/来源不明
            store.save_sword_snapshot(
                [{"sword_id": f"album_{i:03d}", "name_zh": "某刀", "stats": {}}],
                owned=204, capacity=208, missing=1, captured_at=200 + i,
                source=("album", "unknown")[i % 2])
        pool = build_candidate_pool(store)
        self.assertTrue(pool["done"])
        self.assertEqual(pool["source"]["snapshot_id"], good_id)
        # 展示证据可以截断，但只许是"比当选者新"的
        skipped = pool["skipped_newer_snapshots"]
        self.assertTrue(skipped)
        self.assertTrue(all(s["captured_at"] > 100 for s in skipped))

    def test_latest_inventory_api_survives_50_newer_album_snapshots(self):
        import asyncio
        from unittest.mock import patch
        from panel.server import api_latest_sword_inventory

        store = _store()
        good_id = _owned_snapshot(
            store, [_row("touken_003_mikazuki", "三日月宗近")], captured_at=100)
        for i in range(60):
            store.save_sword_snapshot(
                [{"sword_id": f"album_{i:03d}", "name_zh": "某刀", "stats": {}}],
                owned=204, capacity=208, missing=0, captured_at=200 + i,
                source="album")
        with patch("touken.telemetry._store", store):
            response = asyncio.run(api_latest_sword_inventory())
        self.assertEqual(response["snapshot"]["id"], good_id)


class FormationExclusionTests(unittest.TestCase):
    """同位刀同队互斥：普通/极化共用目录 id（127 条目录实测无重名），
    互斥键取 sword_catalog_id；一振一行全保留，绝不因此去重。"""

    def test_normal_and_kiwame_same_position_conflict_and_both_kept(self):
        store = _store()
        # 同一位长谷部练了两振（一普一极，盘点行不区分形态）
        _owned_snapshot(store, [
            _row("touken_118_heshikiri_hasebe", "压切长谷部", level=99),
            _row("touken_118_heshikiri_hasebe", "压切长谷部", level=35),
        ], captured_at=100)
        pool = build_candidate_pool(store)
        self.assertEqual(len(pool["entries"]), 2)  # 两振都在，不合并
        keys = {e["same_team_exclusion_key"] for e in pool["entries"]}
        self.assertEqual(keys, {"touken_118_heshikiri_hasebe"})
        conflicts = formation_conflicts(pool["entries"])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["exclusion_key"],
                         "touken_118_heshikiri_hasebe")
        self.assertEqual(len(conflicts[0]["observation_ids"]), 2)

    def test_two_normal_copies_same_name_conflict(self):
        store = _store()
        _owned_snapshot(store, [
            _row("touken_029_maeda", "前田藤四郎", level=99),
            _row("touken_029_maeda", "前田藤四郎", level=1),
        ], captured_at=100)
        pool = build_candidate_pool(store)
        self.assertEqual(len(formation_conflicts(pool["entries"])), 1)

    def test_different_swords_do_not_conflict(self):
        store = _store()
        _owned_snapshot(store, [
            _row("touken_003_mikazuki", "三日月宗近"),
            _row("touken_005_kogitsunemaru", "小狐丸"),
        ], captured_at=100)
        pool = build_candidate_pool(store)
        self.assertEqual(formation_conflicts(pool["entries"]), [])

    def test_empty_key_is_never_judged(self):
        entries = [{"observation_id": "1:1", "same_team_exclusion_key": None},
                   {"observation_id": "1:2", "same_team_exclusion_key": None},
                   {"observation_id": "1:3"}]  # 键都不存在
        self.assertEqual(formation_conflicts(entries), [])

    def test_roster_link_output_exposes_exclusion_key(self):
        store = _store()
        _owned_snapshot(store, [
            _row("touken_003_mikazuki", "三日月宗近")], captured_at=100)
        _roster_event(store, 1, [_slot(1)], ts=300)
        slot = build_honmaru_profile(store)["roster"]["teams"][0]["slots"][0]
        self.assertEqual(slot["same_team_exclusion_key"],
                         "touken_003_mikazuki")
        # 身份未知的槽：key 保持 None，不拿名字硬猜
        _roster_event(store, 2, [
            _slot(1, catalog_id=None, name=None, name_status="unrecognized",
                  unknown_fields=["identity"])], ts=300)
        slot2 = build_honmaru_profile(store)["roster"]["teams"][1]["slots"][0]
        self.assertIsNone(slot2["same_team_exclusion_key"])


class ProfileSkeletonTests(unittest.TestCase):
    def test_empty_store_returns_honest_skeleton(self):
        profile = build_honmaru_profile(_store())
        self.assertEqual(profile["schema_version"], PROFILE_SCHEMA_VERSION)
        self.assertIn("generated_at", profile)
        self.assertFalse(profile["candidate_pool"]["done"])
        self.assertEqual(len(profile["roster"]["teams"]), 5)

    def test_broken_store_returns_error_skeleton_not_raise(self):
        class BrokenStore:
            def latest_sword_snapshot(self, **kw):
                raise RuntimeError("db gone")

        from touken.honmaru_profile import get_honmaru_profile
        profile = get_honmaru_profile(BrokenStore())
        self.assertFalse(profile["done"])
        self.assertIn("db gone", profile["error"])


if __name__ == "__main__":
    unittest.main()
