# -*- coding: utf-8 -*-
"""刀帐档案（sword_archive）契约测试。

钉死的规矩：
- 人工标注按指纹 (sword_catalog_id, kiwame_date) 挂行；机器 unknown +
  人工确认 → 以人工为准，form_evidence 追加「人工确认（YYYY-MM-DD）」
- 机器 kiwame/normal/ambiguous + 人工确认且与机器不同 → 人工改判
  （form_overridden=True，机器原值留在 machine_form_status，机器证据
  保留，追加「人工改判（YYYY-MM-DD）：原识别=…」）；人工与机器一致
  只追加确认证据不算改判；改判后 attention 的 form_ambiguous 不再触发
- 一标注多行（同名多振同日显现）→ 每行 human 都带且 stale=true，
  不合并形态，attention 记 duplicate_fingerprint
- 标注匹配不到任何行 → 不进 entries，attention 记 stale_annotation
- hints 只对同名多振组出：等级最高（并列都给）/ 显现最早（并列都给），
  日期解析不了就不出那条
- attention 排序：按刀帐番号升序（对齐游戏「刀帐顺序」，方便对照
  游戏翻页核对），番号认不出的殿后，同番号按显现日期老的在前
"""
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from touken.honmaru_profile import build_candidate_pool
from touken.sword_archive import build_sword_archive
from touken.telemetry import TELEMETRY_SCHEMA_VERSION, TelemetryStore

# 固定 epoch（2025-06-15 晚 9 点 UTC+8），让「人工确认（日期）」可断言
CONFIRM_TS = 1750000000.0
EXPECTED_DAY = datetime.fromtimestamp(CONFIRM_TS).strftime("%Y-%m-%d")

IMA_GIRI = "touken_011_imagiri_no_toshiro"  # 今剑（短刀）
HIRANO = "touken_031_hirano_toushirou"      # 平野藤四郎（短刀）
MAEDA = "touken_029_maeda_toushirou"        # 前田藤四郎（短刀）


def _store() -> TelemetryStore:
    return TelemetryStore(Path(tempfile.mkdtemp()) / "telemetry.db")


def _row(catalog_id, name, **kw):
    row = {"sword_id": catalog_id, "name_zh": name, "level": 99,
           "tou_level": 1, "survival": 50, "survival_max": 50,
           "fatigue": 100, "fatigue_max": 100, "stats": {"打击": 55},
           "kiwame_date": "2024-5-1", "locked": None, "page_no": 1}
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
    store._conn().execute("UPDATE events SET ts = ? WHERE id = "
                          "(SELECT MAX(id) FROM events)", (ts,))
    store._conn().commit()


def _slot(slot, catalog_id, name, kiwame_status, **kw):
    base = {"slot": slot, "slot_status": "occupied", "name_raw": name,
            "name": name, "name_status": "recognized",
            "sword_catalog_id": catalog_id, "sword_type": "短刀",
            "level": 99, "fatigue": 100, "survival": 50, "survival_max": 50,
            "injury": "none", "kiwame_status": kiwame_status,
            "unknown_fields": []}
    base.update(kw)
    return base


def _annotate(store, catalog_id, kiwame_date, **kw):
    """存标注并把 updated_at 钉成固定值，让证据日期可断言。"""
    ann = store.save_sword_annotation(catalog_id, kiwame_date, **kw)
    store._conn().execute(
        "UPDATE sword_annotations SET updated_at = ? WHERE id = ?",
        (CONFIRM_TS, ann["id"]))
    store._conn().commit()
    return ann


class SwordArchiveMergeTests(unittest.TestCase):
    def test_unknown_merges_human_confirmation_and_counts_summary(self):
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", kiwame_date="2024-5-1"),
        ], captured_at=100)
        ann = _annotate(store, IMA_GIRI, "2024-5-1",
                        form_confirmed="kiwame", keeper=True, note="要练")

        archive = build_sword_archive(store)
        self.assertTrue(archive["done"])
        self.assertEqual(archive["snapshot_id"], 1)
        self.assertEqual(archive["observed_at"], 100)
        entry = archive["entries"][0]
        self.assertEqual(entry["form_status"], "kiwame")
        self.assertIn(f"人工确认（{EXPECTED_DAY}）", entry["form_evidence"])
        self.assertEqual(entry["sword_type"], "短刀")
        self.assertEqual(entry["human"], {
            "id": ann["id"], "form": "kiwame", "level": None,
            "keeper": True, "favorite": False, "watch": False,
            "note": "要练",
            "confirmed_at": CONFIRM_TS, "stale": False,
        })
        self.assertEqual(archive["summary"], {
            "total": 1, "human_confirmed": 1, "keepers": 1,
            "attention_count": 0})
        self.assertEqual(archive["attention"], [])

    def test_human_none_fields_stay_none(self):
        store = _store()
        _owned_snapshot(store, [_row(IMA_GIRI, "今剑")], captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", note="只留个备注")

        entry = build_sword_archive(store)["entries"][0]
        self.assertIsNone(entry["human"]["form"])
        self.assertFalse(entry["human"]["keeper"])
        self.assertEqual(entry["form_status"], "unknown")  # 没确认形态
        self.assertEqual(archive_reasons(store), ["form_unknown"])

    def test_machine_form_overridden_by_conflicting_annotation(self):
        """机器 normal + 人工确认 kiwame → 人工改判：以人工为准，机器
        原值留在 machine_form_status，机器证据保留并追加改判记录。"""
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑",
                 form_fact={"status": "normal",
                            "evidence": ["花数2/基线2"]}),
        ], captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="kiwame")

        entry = build_sword_archive(store)["entries"][0]
        self.assertEqual(entry["form_status"], "kiwame")  # 人工改判生效
        self.assertEqual(entry["machine_form_status"], "normal")
        self.assertIs(entry["form_overridden"], True)
        self.assertTrue(any("刀帐盘点徽章直读" in e for e in
                            entry["form_evidence"]))  # 机器证据保留
        self.assertIn(f"人工改判（{EXPECTED_DAY}）：原识别=普通",
                      entry["form_evidence"])
        self.assertEqual(entry["human"]["form"], "kiwame")

    def test_machine_ambiguous_not_overridden_by_human(self):
        """两处机器直读打架（盘点 kiwame × 编队页 normal）且人工与盘点
        一致 → 不算改判（只追加确认证据），编队冲突照旧降级 ambiguous，
        进 attention 等人在界面上点。"""
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑",
                 form_fact={"status": "kiwame",
                            "evidence": ["花数3/基线2"]}),
        ], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, IMA_GIRI, "今剑", kiwame_status="normal")], ts=200)
        _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="kiwame")

        archive = build_sword_archive(store)
        entry = archive["entries"][0]
        self.assertEqual(entry["form_status"], "ambiguous")
        self.assertIs(entry["form_overridden"], False)
        self.assertEqual(entry["human"]["form"], "kiwame")
        self.assertFalse(entry["human"]["stale"])
        self.assertEqual([a["reasons"] for a in archive["attention"]],
                         [["form_ambiguous"]])

    def test_revoked_annotation_stops_matching(self):
        store = _store()
        _owned_snapshot(store, [_row(IMA_GIRI, "今剑")], captured_at=100)
        ann = _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="kiwame")
        store.revoke_sword_annotation(ann["id"])

        archive = build_sword_archive(store)
        self.assertIsNone(archive["entries"][0]["human"])
        self.assertEqual(archive["entries"][0]["form_status"], "unknown")
        self.assertEqual(archive["summary"]["human_confirmed"], 0)


class FingerprintCollisionTests(unittest.TestCase):
    def test_same_name_same_day_annotation_hits_all_rows_stale(self):
        store = _store()
        _owned_snapshot(store, [
            _row(MAEDA, "前田藤四郎", level=99, kiwame_date="2024-5-1"),
            _row(MAEDA, "前田藤四郎", level=1, kiwame_date="2024-5-1"),
        ], captured_at=100)
        _annotate(store, MAEDA, "2024-5-1", form_confirmed="kiwame")

        archive = build_sword_archive(store)
        for entry in archive["entries"]:
            self.assertTrue(entry["human"]["stale"])
            self.assertEqual(entry["human"]["form"], "kiwame")
            # 撞车不裁决：形态保持 unknown，attention 同时记 form_unknown
            self.assertEqual(entry["form_status"], "unknown")
        reasons = [tuple(a["reasons"]) for a in archive["attention"]]
        # 行内 reasons 按优先级排：form_unknown > duplicate_fingerprint
        self.assertEqual(reasons, [
            ("form_unknown", "duplicate_fingerprint"),
            ("form_unknown", "duplicate_fingerprint")])
        self.assertEqual(archive["summary"]["human_confirmed"], 0)

    def test_stale_annotation_without_row_surfaces_in_attention(self):
        store = _store()
        _owned_snapshot(store, [_row(IMA_GIRI, "今剑")], captured_at=100)
        _annotate(store, HIRANO, "2026-3-3", form_confirmed="normal",
                  keeper=True)

        archive = build_sword_archive(store)
        self.assertEqual(len(archive["entries"]), 1)  # 没混进 entries
        stale = archive["attention"][-1]
        self.assertEqual(stale["reasons"], ["stale_annotation"])
        self.assertIsNone(stale["observation_id"])
        self.assertEqual(stale["sword_catalog_id"], HIRANO)
        self.assertEqual(stale["name_zh"], "平野藤四郎")  # sword_db 反查
        self.assertEqual(stale["kiwame_date"], "2026-3-3")
        self.assertIsNone(stale["level"])
        # 今剑形态仍 unknown，也占一条 attention
        self.assertEqual(archive["summary"]["attention_count"], 2)

    def test_unknown_catalog_falls_back_to_id_as_display_name(self):
        store = _store()
        _owned_snapshot(store, [_row(IMA_GIRI, "今剑")], captured_at=100)
        _annotate(store, "touken_999_nobody", "2026-1-1")

        stale = build_sword_archive(store)["attention"][-1]
        self.assertEqual(stale["name_zh"], "touken_999_nobody")


class LevelMergeTests(unittest.TestCase):
    """人工等级只补空缺，永不覆盖机器读数（等级会随练级涨，人填的会过期）。"""

    def test_human_level_fills_machine_gap_and_clears_unknown_field(self):
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", level=None,
                 form_fact={"status": "normal",
                            "evidence": ["花数2/基线2"]}),
        ], captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", level_confirmed=88)

        entry = build_sword_archive(store)["entries"][0]
        self.assertEqual(entry["level"], 88)
        self.assertNotIn("level", entry["unknown_fields"])
        self.assertEqual(entry["human"]["level"], 88)
        # 形态机器已确认、等级人工补上 → 不再是 attention
        self.assertEqual(build_sword_archive(store)["attention"], [])

    def test_machine_level_wins_over_human_value(self):
        store = _store()
        _owned_snapshot(store, [_row(IMA_GIRI, "今剑", level=67)],
                        captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", level_confirmed=88)

        entry = build_sword_archive(store)["entries"][0]
        self.assertEqual(entry["level"], 67)  # 机器有值一律信机器
        # 前端仍要标「这等级是你填的」
        self.assertEqual(entry["human"]["level"], 88)

    def test_human_level_key_present_even_without_value(self):
        store = _store()
        _owned_snapshot(store, [_row(IMA_GIRI, "今剑")], captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="kiwame")

        human = build_sword_archive(store)["entries"][0]["human"]
        self.assertIn("level", human)
        self.assertIsNone(human["level"])

    def test_collision_rows_do_not_merge_level(self):
        store = _store()
        _owned_snapshot(store, [
            _row(MAEDA, "前田藤四郎", level=None, kiwame_date="2024-5-1"),
            _row(MAEDA, "前田藤四郎", level=None, kiwame_date="2024-5-1"),
        ], captured_at=100)
        _annotate(store, MAEDA, "2024-5-1", level_confirmed=88)

        archive = build_sword_archive(store)
        for entry in archive["entries"]:
            self.assertIsNone(entry["level"])  # 撞车不合并，照旧
            self.assertIn("level", entry["unknown_fields"])
            self.assertTrue(entry["human"]["stale"])

    def test_level_unknown_reason_alone_and_alongside_form_unknown(self):
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", level=None),  # 形态等级双缺 → 两个 reason
            _row(HIRANO, "平野藤四郎", level=None,
                 form_fact={"status": "kiwame",
                            "evidence": ["花数3/基线2"]}),  # 只缺等级
        ], captured_at=100)

        reasons = [tuple(a["reasons"]) for a in
                   build_sword_archive(store)["attention"]]
        self.assertEqual(reasons, [
            ("form_unknown", "level_unknown"),
            ("level_unknown",),
        ])

    def test_attention_sorting_places_level_unknown_between(self):
        store = _store()
        _owned_snapshot(store, [
            _row("touken_005_kogitsunemaru", "小狐丸"),  # form_unknown
            _row(IMA_GIRI, "今剑", level=None,
                 form_fact={"status": "normal",
                            "evidence": ["花数2/基线2"]}),  # 编队打架→ambiguous
            _row(HIRANO, "平野藤四郎", level=None,
                 form_fact={"status": "kiwame",
                            "evidence": ["花数3/基线2"]}),  # 只缺等级
        ], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, IMA_GIRI, "今剑", kiwame_status="kiwame")], ts=200)

        archive = build_sword_archive(store)
        # attention 按刀帐番号升序：小狐丸(5) → 今剑(11) → 平野藤四郎(31)
        self.assertEqual(
            [(a["name_zh"], tuple(a["reasons"]))
             for a in archive["attention"]],
            [("小狐丸", ("form_unknown",)),
             ("今剑", ("level_unknown", "form_ambiguous")),
             ("平野藤四郎", ("level_unknown",))])
        # 今剑等级被人工没补、机器没读 → attention 行的 level 如实为 None
        jian = next(a for a in archive["attention"] if a["name_zh"] == "今剑")
        self.assertIsNone(jian["level"])

    def test_attention_sorted_by_catalog_number_not_reason_priority(self):
        """番号大的先出事也不能插队：平野(31) 形态没认出、今剑(11) 只缺
        等级——旧优先级排序会把平野排前，刀帐番号排序必须今剑在前。"""
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", level=None,
                 form_fact={"status": "normal",
                            "evidence": ["花数2/基线2"]}),  # 只缺等级
            _row(HIRANO, "平野藤四郎"),  # form_unknown
        ], captured_at=100)

        names = [a["name_zh"] for a in build_sword_archive(store)["attention"]]
        self.assertEqual(names, ["今剑", "平野藤四郎"])

    def test_profile_pool_fills_level_gap_but_never_overwrites(self):
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", level=None),
            _row(HIRANO, "平野藤四郎", level=67),
        ], captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", level_confirmed=88)
        _annotate(store, HIRANO, "2024-5-1", level_confirmed=88)

        entries = build_candidate_pool(store)["entries"]
        gap, machine = entries
        self.assertEqual(gap["level"], 88)
        self.assertNotIn("level", gap["unknown_fields"])
        self.assertEqual(machine["level"], 67)  # 机器读数不被盖


class HintTests(unittest.TestCase):
    def test_level_top_ties_all_get_hint_and_earliest_manifest(self):
        store = _store()
        _owned_snapshot(store, [
            _row(MAEDA, "前田藤四郎", level=99, kiwame_date="2024-5-1"),
            _row(MAEDA, "前田藤四郎", level=99, kiwame_date="2024-6-1"),
            _row(MAEDA, "前田藤四郎", level=50, kiwame_date="2024-7-1"),
            _row(IMA_GIRI, "今剑", level=99, kiwame_date="2024-1-1"),
        ], captured_at=100)

        entries = build_sword_archive(store)["entries"]
        by_level = [(e["level"], e["hints"]) for e in entries
                    if e["sword_catalog_id"] == MAEDA]
        self.assertEqual(by_level, [
            (99, ["同名 3 振中等级最高", "同名中显现最早"]),
            (99, ["同名 3 振中等级最高"]),
            (50, []),  # 2024/7/1 不是最早显现
        ])
        single = next(e for e in entries
                      if e["sword_catalog_id"] == IMA_GIRI)
        self.assertEqual(single["hints"], [])  # 单振组不出提示

    def test_unparseable_date_skips_only_date_hint(self):
        store = _store()
        _owned_snapshot(store, [
            _row(MAEDA, "前田藤四郎", level=99, kiwame_date="读不出"),
            _row(MAEDA, "前田藤四郎", level=1, kiwame_date="2024-5-1"),
        ], captured_at=100)

        entries = build_sword_archive(store)["entries"]
        top = next(e for e in entries if e["level"] == 99)
        self.assertEqual(top["hints"], ["同名 2 振中等级最高"])
        other = next(e for e in entries if e["level"] == 1)
        self.assertEqual(other["hints"], ["同名中显现最早"])

    def test_missing_level_in_group_skips_level_hint(self):
        # 组内有等级没读出来的行：缺一振的"最高"会误导人，等级提示整组不出
        store = _store()
        _owned_snapshot(store, [
            _row(MAEDA, "前田藤四郎", level=1, kiwame_date="2024-5-1"),
            _row(MAEDA, "前田藤四郎", level=None, kiwame_date="2024-6-1"),
        ], captured_at=100)

        entries = build_sword_archive(store)["entries"]
        for entry in entries:
            self.assertNotIn("等级最高", "；".join(entry["hints"]))
        low = next(e for e in entries if e["level"] == 1)
        self.assertEqual(low["hints"], ["同名中显现最早"])

    def test_slash_date_format_parses(self):
        store = _store()
        _owned_snapshot(store, [
            _row(MAEDA, "前田藤四郎", level=99, kiwame_date="2024/5/1"),
            _row(MAEDA, "前田藤四郎", level=1, kiwame_date="2024/6/1"),
        ], captured_at=100)

        entries = build_sword_archive(store)["entries"]
        top = next(e for e in entries if e["level"] == 99)
        self.assertIn("同名中显现最早", top["hints"])


class AttentionOrderTests(unittest.TestCase):
    def test_attention_sorted_by_catalog_number(self):
        store = _store()
        _owned_snapshot(store, [
            _row("touken_005_kogitsunemaru", "小狐丸"),   # unknown
            _row(IMA_GIRI, "今剑",
                 form_fact={"status": "kiwame",
                            "evidence": ["花数3/基线2"]}),  # 待会打成 ambiguous
            _row(MAEDA, "前田藤四郎", level=99),          # unknown
            _row(MAEDA, "前田藤四郎", level=1),           # 同名多振 → 提示
        ], captured_at=100)
        # 编队页与盘点打架 → 今剑 ambiguous
        _roster_event(store, 1, [
            _slot(1, IMA_GIRI, "今剑", kiwame_status="normal")], ts=200)
        # 没挂到行的标注 → stale_annotation
        _annotate(store, HIRANO, "2026-3-3")

        archive = build_sword_archive(store)
        attention = archive["attention"]
        # 刀帐番号升序：小狐丸(5) → 今剑(11) → 前田(29)×2 → 平野(31)；
        # 与 reason 优先级无关——番号大的先出事也不插队
        self.assertEqual(
            [(a["name_zh"], tuple(a["reasons"])) for a in attention],
            [("小狐丸", ("form_unknown",)),
             ("今剑", ("form_ambiguous",)),
             ("前田藤四郎", ("form_unknown",)),   # 同名两振，按 oid 稳定次序
             ("前田藤四郎", ("form_unknown",)),
             ("平野藤四郎", ("stale_annotation",))])
        # 同名多振的 unknown 行带 hints；attention 行也带
        maeda_rows = [a for a in attention if a["name_zh"] == "前田藤四郎"]
        self.assertIn("同名 2 振中等级最高", maeda_rows[0]["hints"])
        self.assertEqual(archive["summary"]["attention_count"], 5)


class NoSnapshotTests(unittest.TestCase):
    def test_no_trustworthy_snapshot_returns_honest_skeleton(self):
        store = _store()
        store.save_sword_snapshot(
            [{"sword_id": "album_003", "name_zh": "三日月宗近",
              "stats": {}}],
            owned=204, capacity=208, missing=0, captured_at=100,
            source="album")
        _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="kiwame")

        archive = build_sword_archive(store)
        self.assertFalse(archive["done"])
        self.assertTrue(archive["reason"])
        self.assertEqual(archive["snapshot_id"], None)
        self.assertEqual(archive["summary"], {
            "total": 0, "human_confirmed": 0, "keepers": 0,
            "attention_count": 0})
        self.assertEqual(archive["entries"], [])
        self.assertEqual(archive["attention"], [])


class CandidatePoolHumanMergeTests(unittest.TestCase):
    """honmaru_profile 侧的同规则合并：档案与候选池共用一套指纹挂接。"""

    def test_pool_merges_unique_annotation_into_unknown(self):
        store = _store()
        _owned_snapshot(store, [_row(IMA_GIRI, "今剑")], captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="normal")

        entry = build_candidate_pool(store)["entries"][0]
        self.assertEqual(entry["form_status"], "normal")
        self.assertIn(f"人工确认（{EXPECTED_DAY}）", entry["form_evidence"])

    def test_pool_leaves_collision_rows_unknown(self):
        store = _store()
        _owned_snapshot(store, [
            _row(MAEDA, "前田藤四郎", level=99, kiwame_date="2024-5-1"),
            _row(MAEDA, "前田藤四郎", level=1, kiwame_date="2024-5-1"),
        ], captured_at=100)
        _annotate(store, MAEDA, "2024-5-1", form_confirmed="kiwame")

        entries = build_candidate_pool(store)["entries"]
        for entry in entries:
            self.assertEqual(entry["form_status"], "unknown")


class FormOverrideArchiveTests(unittest.TestCase):
    """人工改判的档案层契约：entry 透传 machine_form_status/form_overridden
    （无覆盖给 None/False）；ambiguous 被人工裁决后自然出 attention 清单。"""

    def test_override_fields_passthrough_with_defaults(self):
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", kiwame_date="2024-5-1",
                 form_fact={"status": "kiwame", "evidence": ["花数3/基线2"]}),
            _row(HIRANO, "平野藤四郎", kiwame_date="2024-5-1",
                 form_fact={"status": "normal", "evidence": ["花数2/基线2"]}),
        ], captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="normal")

        entries = build_sword_archive(store)["entries"]
        overridden, untouched = entries
        self.assertEqual(overridden["form_status"], "normal")
        self.assertEqual(overridden["machine_form_status"], "kiwame")
        self.assertIs(overridden["form_overridden"], True)
        # 无覆盖的行给默认值
        self.assertEqual(untouched["form_status"], "normal")
        self.assertIsNone(untouched["machine_form_status"])
        self.assertIs(untouched["form_overridden"], False)
        # 改判后形态/等级都齐 → 不占 attention
        self.assertEqual(build_sword_archive(store)["attention"], [])

    def test_ambiguous_overridden_by_human_leaves_attention(self):
        """盘点徽章 kiwame × 编队页直读 normal 本会打成 ambiguous；人工
        裁决 normal 后 form_status 是确定值，form_ambiguous 不再触发，
        自然出 attention 清单。"""
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", kiwame_date="2024-5-1",
                 form_fact={"status": "kiwame", "evidence": ["花数3/基线2"]}),
        ], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, IMA_GIRI, "今剑", kiwame_status="normal")], ts=200)
        _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="normal")

        archive = build_sword_archive(store)
        entry = archive["entries"][0]
        self.assertEqual(entry["form_status"], "normal")
        self.assertEqual(entry["machine_form_status"], "kiwame")
        self.assertIs(entry["form_overridden"], True)
        # 机器徽章证据、人工改判、编队页直读全部保留
        joined = "；".join(entry["form_evidence"])
        self.assertIn("刀帐盘点徽章直读", joined)
        self.assertIn(f"人工改判（{EXPECTED_DAY}）：原识别=极", joined)
        self.assertIn("编队页", joined)
        self.assertEqual(archive["attention"], [])

    def test_conflicting_roster_read_after_override_stays_ambiguous(self):
        """改判成 normal 后编队页直读仍说 kiwame → 照旧降级 ambiguous，
        如实进 attention（改判字段原样保留，证据不丢）。"""
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", kiwame_date="2024-5-1",
                 form_fact={"status": "kiwame", "evidence": ["花数3/基线2"]}),
        ], captured_at=100)
        _roster_event(store, 1, [
            _slot(1, IMA_GIRI, "今剑", kiwame_status="kiwame")], ts=200)
        _annotate(store, IMA_GIRI, "2024-5-1", form_confirmed="normal")

        archive = build_sword_archive(store)
        entry = archive["entries"][0]
        self.assertEqual(entry["form_status"], "ambiguous")
        self.assertEqual(entry["machine_form_status"], "kiwame")
        self.assertIs(entry["form_overridden"], True)
        self.assertEqual([a["reasons"] for a in archive["attention"]],
                         [["form_ambiguous"]])


class PreferenceFlagTests(unittest.TestCase):
    """favorite/watch（v14）与 keeper 同为玩家偏好契约：档案 human 字典
    透传布尔，更新只动传入的非 None 字段（前端单字段递回）。"""

    def test_human_dict_passes_favorite_watch(self):
        store = _store()
        _owned_snapshot(store, [
            _row(IMA_GIRI, "今剑", kiwame_date="2024-5-1",
                 form_fact={"status": "normal", "evidence": ["花数2/基线2"]}),
            _row(HIRANO, "平野藤四郎", kiwame_date="2024-5-1",
                 form_fact={"status": "normal", "evidence": ["花数2/基线2"]}),
        ], captured_at=100)
        _annotate(store, IMA_GIRI, "2024-5-1", favorite=True, watch=True)
        _annotate(store, HIRANO, "2024-5-1", note="只留个备注")  # 没标偏好

        entries = build_sword_archive(store)["entries"]
        flagged, plain = entries
        self.assertIs(flagged["human"]["favorite"], True)
        self.assertIs(flagged["human"]["watch"], True)
        self.assertIsNotNone(plain["human"])  # 有标注但没带偏好标记
        self.assertIs(plain["human"]["favorite"], False)
        self.assertIs(plain["human"]["watch"], False)
        # summary 不加新计数，字段保持原样
        self.assertEqual(set(build_sword_archive(store)["summary"]),
                         {"total", "human_confirmed", "keepers",
                          "attention_count"})

    def test_single_field_write_does_not_touch_other_flags(self):
        """前端单字段递回：只传 favorite 时 watch/keeper 不被动。"""
        store = _store()
        _annotate(store, IMA_GIRI, "2024-5-1", keeper=True)
        _annotate(store, IMA_GIRI, "2024-5-1", favorite=True)
        _annotate(store, IMA_GIRI, "2024-5-1", watch=True)

        ann = store.sword_annotations()[0]
        self.assertTrue(ann["keeper"])
        self.assertTrue(ann["favorite"])
        self.assertTrue(ann["watch"])
        # 只递回一个字段时另一个不被清掉
        _annotate(store, IMA_GIRI, "2024-5-1", favorite=False)
        ann = store.sword_annotations()[0]
        self.assertFalse(ann["favorite"])
        self.assertTrue(ann["watch"])


class SchemaV14MigrationTests(unittest.TestCase):
    """v13 老库（sword_annotations 没有 favorite/watch 列）原地升级：
    ALTER 补列默认 0，老标注一条不丢，照常 upsert 新偏好标记。"""

    def _v13_db(self) -> Path:
        db = Path(tempfile.mkdtemp()) / "telemetry.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sword_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sword_catalog_id TEXT NOT NULL,
                kiwame_date TEXT NOT NULL,
                level_at_mark INTEGER,
                level_confirmed INTEGER,
                form_confirmed TEXT,
                keeper INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                created_at REAL,
                updated_at REAL,
                revoked INTEGER NOT NULL DEFAULT 0);
            INSERT INTO metadata(key, value) VALUES('schema_version', '13');
            INSERT INTO sword_annotations(sword_catalog_id, kiwame_date,
                level_confirmed, form_confirmed, keeper, note,
                created_at, updated_at, revoked)
                VALUES ('touken_011_imagiri_no_toshiro', '2024-5-1',
                        88, 'kiwame', 1, '老标注', 100, 100, 0);
        """)
        conn.commit()
        conn.close()
        return db

    def test_v13_database_gains_favorite_watch_without_data_loss(self):
        db = self._v13_db()
        store = TelemetryStore(db)
        try:
            # 库内版本号原地升级（summary() 返回的是常量，以 metadata 为准）
            version = store._conn().execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()["value"]
            self.assertEqual(version, str(TELEMETRY_SCHEMA_VERSION))
            cols = {row["name"]: row for row in store._conn().execute(
                "PRAGMA table_info(sword_annotations)").fetchall()}
            self.assertIn("favorite", cols)
            self.assertIn("watch", cols)
            self.assertEqual(cols["favorite"]["dflt_value"], "0")
            self.assertEqual(cols["watch"]["dflt_value"], "0")
            # 老标注原样在，新列补成 0，不回填不猜测
            old = store.sword_annotations()[0]
            self.assertEqual(old["note"], "老标注")
            self.assertTrue(old["keeper"])
            self.assertFalse(old["favorite"])
            self.assertFalse(old["watch"])
            self.assertEqual(old["level_confirmed"], 88)
            # 老行照常 upsert 补偏好标记，别的字段不动
            updated = store.save_sword_annotation(
                "touken_011_imagiri_no_toshiro", "2024-5-1", favorite=True)
            self.assertTrue(updated["favorite"])
            self.assertFalse(updated["watch"])
            self.assertEqual(updated["form_confirmed"], "kiwame")
            self.assertEqual(updated["note"], "老标注")
        finally:
            store.close()
        # 重复打开幂等：列不重复加、补的值不丢
        store2 = TelemetryStore(db)
        try:
            self.assertTrue(store2.sword_annotations()[0]["favorite"])
        finally:
            store2.close()


def archive_reasons(store):
    return [reason for item in build_sword_archive(store)["attention"]
            for reason in item["reasons"]]


if __name__ == "__main__":
    unittest.main()
