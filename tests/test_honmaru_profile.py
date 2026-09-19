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
from datetime import datetime
from pathlib import Path

from touken.honmaru_profile import (PROFILE_SCHEMA_VERSION,
                                    _apply_human_confirmations,
                                    build_candidate_pool, build_honmaru_profile,
                                    formation_conflicts)
from touken.telemetry import TelemetryStore

# 固定 epoch，让「人工确认（日期）」「人工改判（日期）」可断言
CONFIRM_TS = 1750000000.0
EXPECTED_DAY = datetime.fromtimestamp(CONFIRM_TS).strftime("%Y-%m-%d")


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


def _annotate(store, catalog_id, kiwame_date, **kw):
    """存标注并把 updated_at 钉成固定值，让证据日期可断言。"""
    ann = store.save_sword_annotation(catalog_id, kiwame_date, **kw)
    store._conn().execute(
        "UPDATE sword_annotations SET updated_at = ? WHERE id = ?",
        (CONFIRM_TS, ann["id"]))
    store._conn().commit()
    return ann


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


class FormConclusionTests(unittest.TestCase):
    """候选形态结论（2026-09-15 P0 修正）：kiwame_date 是显现日期，
    每振都有，永不当形态证据。结论只来自——实例级：一览盘点落盘的
    徽章直读（刀种+花数 vs 名册基线）与编队页槽位直读（两处冲突降级
    ambiguous）；种级：图鉴「极」字标（只正向，分不清哪振就 ambiguous）；
    都没有 → unknown（前端显示「形态未确认」）。"""

    HASEBE = "touken_118_heshikiri_hasebe"

    def _profile(self, store):
        return build_honmaru_profile(store)

    def test_manifest_date_alone_proves_nothing(self):
        """带显现日期（kiwame_date）的条目没有任何形态结论——反例，
        旧版就是拿它把 185/196 振全误判成极。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=35,
                 kiwame_date="2024-01-01")], captured_at=100)
        profile = self._profile(store)
        entry = profile["candidate_pool"]["entries"][0]
        self.assertEqual(entry["form_status"], "unknown")
        self.assertEqual(entry["form_evidence"], [])

    def test_roster_linked_slot_gives_instance_conclusion(self):
        """实例级最强证据：唯一链接到在队槽位 + 槽位直读结论。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99)], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, catalog_id=self.HASEBE, name="压切长谷部",
                  kiwame_status="kiwame",
                  kiwame_evidence=[{"raw_value": "白樱花"}])], ts=200)
        profile = self._profile(store)
        entry = profile["candidate_pool"]["entries"][0]
        self.assertEqual(entry["form_status"], "kiwame")
        self.assertTrue(any("编队页" in e for e in entry["form_evidence"]))
        self.assertTrue(any("白樱花" in e for e in entry["form_evidence"]))

    def test_roster_normal_conclusion_too(self):
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99)], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, catalog_id=self.HASEBE, name="压切长谷部",
                  kiwame_status="normal")], ts=200)
        profile = self._profile(store)
        self.assertEqual(profile["candidate_pool"]["entries"][0]
                         ["form_status"], "normal")

    def test_album_mark_without_instance_evidence_is_ambiguous(self):
        """图鉴有极标但分不清哪一振 → ambiguous，不猜 kiwame。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99),
            _row(self.HASEBE, "压切长谷部", level=35)], captured_at=100)
        _owned_snapshot(store, [
            {"sword_id": "album_118", "name_zh": "压切长谷部",
             "stats": {"极化": True}}],
            owned=204, missing=3, captured_at=300,
            source="album")
        profile = self._profile(store)
        for entry in profile["candidate_pool"]["entries"]:
            self.assertEqual(entry["form_status"], "ambiguous")
            self.assertTrue(any("图鉴" in e for e in entry["form_evidence"]))

    def test_unmarked_and_unseen_stays_unknown(self):
        """图鉴没极标（或未扫过图鉴）又不是队里直读 → unknown。"""
        store = _store()
        _owned_snapshot(store, [
            _row("touken_999_adana", "安宅切", level=99,
                 kiwame_date="2026-7-29")], captured_at=100)
        _owned_snapshot(store, [
            {"sword_id": "album_118", "name_zh": "压切长谷部",
             "stats": {"极化": True}}],
            owned=204, missing=3, captured_at=300,
            source="album")
        profile = self._profile(store)
        entry = profile["candidate_pool"]["entries"][0]
        self.assertEqual(entry["form_status"], "unknown")  # 安宅切不再盖极章
        self.assertEqual(entry["form_evidence"], [])

    def test_roster_unknown_slot_does_not_downgrade(self):
        """槽位直读 unknown 不算证据，落回种级/无证据路径。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99)], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, catalog_id=self.HASEBE, name="压切长谷部",
                  kiwame_status="unknown")], ts=200)
        profile = self._profile(store)
        self.assertEqual(profile["candidate_pool"]["entries"][0]
                         ["form_status"], "unknown")

    def test_stored_badge_fact_gives_instance_conclusion(self):
        """落盘形态事实（一览徽章直读，2026-09-15 收口）：实例级结论，
        证据标来源；显现日期依旧零证据。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99,
                 kiwame_date="2024-01-01",
                 form_fact={"status": "kiwame",
                            "evidence": ["花数3/基线2"]})], captured_at=100)
        profile = self._profile(store)
        entry = profile["candidate_pool"]["entries"][0]
        self.assertEqual(entry["form_status"], "kiwame")
        self.assertTrue(any("刀帐盘点徽章直读" in e and "花数3/基线2" in e
                            for e in entry["form_evidence"]))

    def test_stored_fact_and_roster_agree_stacks_evidence(self):
        """落盘结论与编队页直读一致 → 结论不变，证据叠加。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99,
                 form_fact={"status": "normal",
                            "evidence": ["花数2/基线2"]})], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, catalog_id=self.HASEBE, name="压切长谷部",
                  kiwame_status="normal")], ts=200)
        profile = self._profile(store)
        entry = profile["candidate_pool"]["entries"][0]
        self.assertEqual(entry["form_status"], "normal")
        self.assertTrue(any("刀帐盘点" in e for e in entry["form_evidence"]))
        self.assertTrue(any("编队页" in e for e in entry["form_evidence"]))

    def test_stored_fact_conflicting_roster_is_ambiguous(self):
        """盘点徽章说普通、编队页直读说极化 → 两处打架，降级存疑。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99,
                 form_fact={"status": "normal",
                            "evidence": ["花数2/基线2"]})], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, catalog_id=self.HASEBE, name="压切长谷部",
                  kiwame_status="kiwame",
                  kiwame_evidence=[{"raw_value": "白樱花"}])], ts=200)
        profile = self._profile(store)
        entry = profile["candidate_pool"]["entries"][0]
        self.assertEqual(entry["form_status"], "ambiguous")
        self.assertTrue(any("冲突" in e for e in entry["form_evidence"]))

    def test_stored_unknown_fact_is_not_evidence(self):
        """落盘 status=unknown（徽章没读出/白名单未覆盖）不挂证据。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99,
                 form_fact={"status": "unknown", "evidence": [],
                            "badge": {"conclusion": "unproven_combo"}})],
            captured_at=100)
        profile = self._profile(store)
        entry = profile["candidate_pool"]["entries"][0]
        self.assertEqual(entry["form_status"], "unknown")
        self.assertEqual(entry["form_evidence"], [])


class HumanFormOverrideTests(unittest.TestCase):
    """人工可覆盖机器的极/普判定（刀帐升级·第一批）：
    机器 unknown 照旧以人工为准；机器 kiwame/normal/ambiguous + 人工
    确认且与机器不同 → 人工改判（form_overridden=True，机器原值留在
    machine_form_status，机器证据保留）；人工与机器一致只追加确认证据
    不算改判；指纹撞车不合并；撤销后回落机器结论；等级仍只补空缺。"""

    HASEBE = "touken_118_heshikiri_hasebe"

    def _pool(self, form_fact=None, **row_kw):
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", kiwame_date="2024-5-1",
                 form_fact=form_fact, **row_kw)], captured_at=100)
        return store

    def test_machine_kiwame_overridden_by_human_normal(self):
        store = self._pool(form_fact={"status": "kiwame",
                                      "evidence": ["花数3/基线2"]})
        _annotate(store, self.HASEBE, "2024-5-1", form_confirmed="normal")

        entry = build_candidate_pool(store)["entries"][0]
        self.assertEqual(entry["form_status"], "normal")
        self.assertEqual(entry["machine_form_status"], "kiwame")
        self.assertIs(entry["form_overridden"], True)
        # 机器原证据保留，追加人工改判证据
        self.assertTrue(any("刀帐盘点徽章直读" in e for e in
                            entry["form_evidence"]))
        self.assertIn(f"人工改判（{EXPECTED_DAY}）：原识别=极",
                      entry["form_evidence"])

    def test_machine_normal_overridden_by_human_kiwame(self):
        store = self._pool(form_fact={"status": "normal",
                                      "evidence": ["花数2/基线2"]})
        _annotate(store, self.HASEBE, "2024-5-1", form_confirmed="kiwame")

        entry = build_candidate_pool(store)["entries"][0]
        self.assertEqual(entry["form_status"], "kiwame")
        self.assertEqual(entry["machine_form_status"], "normal")
        self.assertIs(entry["form_overridden"], True)
        self.assertIn(f"人工改判（{EXPECTED_DAY}）：原识别=普通",
                      entry["form_evidence"])

    def test_machine_ambiguous_overridden_by_human(self):
        """候选池生成期机器形态只有 kiwame/normal/unknown（_stored_form_status
        不收 ambiguous），ambiguous 是档案管线后段（编队打架/图鉴极标）才
        出的结论——改判分支对 ambiguous 的验证直接调合并函数。"""
        entry = {"sword_catalog_id": self.HASEBE, "kiwame_date": "2024-5-1",
                 "form_status": "ambiguous",
                 "form_evidence": ["两处直读结论冲突，分不清，存疑"],
                 "machine_form_status": None, "form_overridden": False,
                 "level": 99, "unknown_fields": []}
        ann = {"sword_catalog_id": self.HASEBE, "kiwame_date": "2024-5-1",
               "form_confirmed": "normal", "updated_at": CONFIRM_TS,
               "revoked": 0}
        _apply_human_confirmations([entry], [ann])
        self.assertEqual(entry["form_status"], "normal")
        self.assertEqual(entry["machine_form_status"], "ambiguous")
        self.assertIs(entry["form_overridden"], True)
        self.assertIn("两处直读结论冲突，分不清，存疑", entry["form_evidence"])
        self.assertIn(f"人工改判（{EXPECTED_DAY}）：原识别=存疑",
                      entry["form_evidence"])

    def test_human_matching_machine_is_confirmation_not_override(self):
        store = self._pool(form_fact={"status": "kiwame",
                                      "evidence": ["花数3/基线2"]})
        _annotate(store, self.HASEBE, "2024-5-1", form_confirmed="kiwame")

        entry = build_candidate_pool(store)["entries"][0]
        self.assertEqual(entry["form_status"], "kiwame")
        self.assertIsNone(entry["machine_form_status"])
        self.assertIs(entry["form_overridden"], False)
        self.assertIn(f"人工确认（{EXPECTED_DAY}）", entry["form_evidence"])
        self.assertFalse(any("人工改判" in e for e in entry["form_evidence"]))

    def test_fingerprint_collision_rows_are_not_overridden(self):
        """同名同日两行（一标注对不上唯一行）→ 不合并不改判，保持机器结论。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=99,
                 kiwame_date="2024-5-1",
                 form_fact={"status": "kiwame", "evidence": ["花数3/基线2"]}),
            _row(self.HASEBE, "压切长谷部", level=35,
                 kiwame_date="2024-5-1",
                 form_fact={"status": "kiwame", "evidence": ["花数3/基线2"]}),
        ], captured_at=100)
        _annotate(store, self.HASEBE, "2024-5-1", form_confirmed="normal")

        entries = build_candidate_pool(store)["entries"]
        for entry in entries:
            self.assertEqual(entry["form_status"], "kiwame")  # 机器结论不动
            self.assertIsNone(entry["machine_form_status"])
            self.assertIs(entry["form_overridden"], False)
            self.assertFalse(any("人工改判" in e for e in
                                 entry["form_evidence"]))

    def test_revoked_annotation_falls_back_to_machine(self):
        store = self._pool(form_fact={"status": "normal",
                                      "evidence": ["花数2/基线2"]})
        ann = _annotate(store, self.HASEBE, "2024-5-1",
                        form_confirmed="kiwame")
        store.revoke_sword_annotation(ann["id"])

        entry = build_candidate_pool(store)["entries"][0]
        self.assertEqual(entry["form_status"], "normal")  # 回落机器结论
        self.assertIsNone(entry["machine_form_status"])
        self.assertIs(entry["form_overridden"], False)
        self.assertEqual(entry["form_evidence"],
                         ["刀帐盘点徽章直读（花数2/基线2）"])

    def test_level_rules_unchanged_by_override(self):
        """改判形态不碰等级铁律：机器有值信机器，机器空缺才补人工。"""
        store = _store()
        _owned_snapshot(store, [
            _row(self.HASEBE, "压切长谷部", level=67,
                 kiwame_date="2024-5-1",
                 form_fact={"status": "kiwame", "evidence": ["花数3/基线2"]}),
            _row("touken_003_mikazuki", "三日月宗近", level=None,
                 kiwame_date="2024-5-1"),
        ], captured_at=100)
        _annotate(store, self.HASEBE, "2024-5-1", form_confirmed="normal",
                  level_confirmed=88)
        _annotate(store, "touken_003_mikazuki", "2024-5-1",
                  level_confirmed=88)

        overridden, gap = build_candidate_pool(store)["entries"]
        self.assertEqual(overridden["form_status"], "normal")  # 形态被改判
        self.assertEqual(overridden["level"], 67)  # 机器读数不被盖
        self.assertEqual(gap["level"], 88)  # 空缺补人工
        self.assertNotIn("level", gap["unknown_fields"])


if __name__ == "__main__":
    unittest.main()
