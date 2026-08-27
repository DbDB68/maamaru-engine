import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from touken.telemetry import TELEMETRY_SCHEMA_VERSION, TelemetryStore


class TelemetryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(Path(self.temp.name) / "telemetry.db")
        self.env = patch.dict(os.environ, {
            "MAAMARU_RUN_ID": "run-1",
            "MAAMARU_SCRIPT": "osaka",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.store.close()
        self.temp.cleanup()

    def test_records_run_ocr_and_event_with_stable_context(self):
        self.store.start_run("run-1", "osaka")
        self.store.record_ocr(
            kind="match", roi=[1, 2, 3, 4], expected="当前层数",
            match_mode="contains", matched=True,
            tokens=[{"text": "当前层数", "score": 0.98,
                     "center": [10, 20], "box": [1, 2, 3, 4]}],
        )
        self.store.record_event("osaka.floor_completed", {"completed": 1})
        self.store.finish_run("run-1", "completed")

        observation = self.store.recent_observations()[0]
        self.assertEqual(observation["run_id"], "run-1")
        self.assertEqual(observation["roi"], [1, 2, 3, 4])
        self.assertTrue(observation["matched"])
        self.assertEqual(observation["tokens"][0]["text"], "当前层数")

        event = self.store.recent_events()[0]
        self.assertEqual(event["event_type"], "osaka.floor_completed")
        self.assertEqual(event["payload"]["completed"], 1)

        summary = self.store.summary()
        self.assertEqual(summary["schema_version"], TELEMETRY_SCHEMA_VERSION)
        self.assertEqual(summary["runs"]["by_status"]["completed"], 1)
        self.assertEqual(summary["ocr"]["match_rate"], 1.0)
        self.assertEqual(summary["events"]["by_type"]["osaka.floor_completed"], 1)

    def test_filters_and_limits_are_machine_fields_not_log_parsing(self):
        self.store.record_event("repair.completed", {"repaired": 2})
        self.store.record_event("inventory.captured", {"resources": {"小判": 10}})
        self.store.record_ocr(kind="match", roi=[0, 0, 1, 1],
                              expected="登录", match_mode="exact",
                              matched=False, tokens=[])

        events = self.store.recent_events(event_type="repair.completed")
        misses = self.store.recent_observations(matched=False)
        self.assertEqual([e["event_type"] for e in events], ["repair.completed"])
        self.assertEqual([o["expected"] for o in misses], ["登录"])

    def test_run_summary_counts_upkeep_speed_and_resource_delta(self):
        self.store.start_run("run-1", "osaka", started_at=100)
        conn = self.store._conn()
        samples = [
            (110, "inventory.captured", {"phase": "before", "resources": {"小判": 1000, "加速符": 20}}),
            (120, "osaka.floor_completed", {"selected_floor": 88}),
            (180, "repair.session_completed", {"repaired": 2, "speedups": 2}),
            (200, "equipment.restored", {"record_no": 1}),
            (220, "osaka.floor_completed", {"selected_floor": 88}),
            (320, "osaka.floor_completed", {"selected_floor": 88}),
            (330, "inventory.captured", {"phase": "after", "resources": {"小判": 1300, "加速符": 18}}),
        ]
        for ts, kind, payload in samples:
            conn.execute("INSERT INTO events(ts, run_id, script, event_type, payload) VALUES (?, 'run-1', 'osaka', ?, ?)",
                         (ts, kind, __import__('json').dumps(payload)))
        conn.commit()
        self.store.finish_run("run-1", "completed", ended_at=340)

        result = self.store.run_summary("run-1")
        self.assertEqual(result["loops"], 3)
        self.assertEqual(result["average_loop_seconds"], 100)
        self.assertEqual(result["estimated_6h_loops"], 216)
        self.assertEqual(result["play_duration_seconds"], 220)
        self.assertEqual(result["repair_sessions"], 1)
        self.assertEqual(result["repaired_swords"], 2)
        self.assertEqual(result["speedups"], 2)
        self.assertEqual(result["equipment_restores"], 1)
        self.assertEqual(result["resource_delta"], {"小判": 300, "加速符": -2})

    def test_run_summary_counts_edocastle_key_settlements_as_loops(self):
        self.store.start_run("edo-1", "edocastle", started_at=100)
        conn = self.store._conn()
        for ts, run_no, keys in ((160, 1, 17), (260, 2, 26)):
            conn.execute(
                "INSERT INTO events(ts, run_id, script, event_type, payload) "
                "VALUES (?, 'edo-1', 'edocastle', 'edocastle.run_completed', ?)",
                (ts, __import__('json').dumps({"run_no": run_no, "keys": keys})),
            )
        conn.commit()
        self.store.finish_run("edo-1", "completed", ended_at=280)

        result = self.store.run_summary("edo-1")
        self.assertEqual(result["loops"], 2)
        self.assertEqual(result["play_duration_seconds"], 160)
        self.assertEqual(result["average_loop_seconds"], 100)

    def test_run_summary_does_not_count_empty_repair_visit(self):
        self.store.start_run("run-1", "osaka", started_at=100)
        self.store.record_event("osaka.floor_completed", {"selected_floor": 88})
        self.store.record_event("repair.session_completed", {
            "repaired": 0, "speedups": 0, "session_count": 1,
        })
        self.store.finish_run("run-1", "completed", ended_at=200)

        result = self.store.run_summary("run-1")
        self.assertEqual(result["repair_sessions"], 0)
        self.assertEqual(result["repaired_swords"], 0)

    def test_run_summary_exposes_confirmed_changes_without_snapshots(self):
        self.store.start_run("run-1", "daily")
        self.store.record_event("resource.change", {
            "resource": "木炭", "delta": -700, "attribution": "confirmed",
        })
        self.store.record_event("resource.change", {
            "resource": "木炭", "delta": 1050, "attribution": "confirmed",
        })
        self.store.record_event("resource.change", {
            "resource": "委托符", "delta": -1, "attribution": "confirmed",
        })
        self.store.record_event("resource.change", {
            "resource": "玉钢", "delta": None, "attribution": "unknown",
        })
        self.store.finish_run("run-1", "completed")

        result = self.store.run_summary("run-1")
        self.assertEqual(result["attributed_resource_delta"], {
            "木炭": 350, "委托符": -1,
        })
        self.assertEqual(result["resource_change_count"], 3)
        self.assertFalse(result["has_resource_comparison"])

    def test_run_summary_counts_boss_retreat_and_keeps_latest_inventory_peek(self):
        self.store.start_run("run-1", "sortie", started_at=100)
        self.store.record_event("inventory.peek", {
            "tag": "sortie", "木炭": 100, "玉钢": 200,
            "冷却材": 300, "砥石": 400, "小判": 500,
        })
        self.store.record_event("sortie.retreated_before_boss", {
            "chapter": 5, "map_no": 4, "sequence": 1,
        })
        self.store.finish_run("run-1", "completed", ended_at=200)

        result = self.store.run_summary("run-1")
        self.assertEqual(result["loops"], 1)
        self.assertEqual(result["inventory_observation_count"], 1)
        self.assertEqual(result["inventory_observation"]["小判"], 500)
        self.assertFalse(result["has_resource_comparison"])

    def test_manual_inventory_snapshot_completes_run_comparison(self):
        self.store.start_run("run-1", "osaka", started_at=100)
        conn = self.store._conn()
        conn.execute(
            "INSERT INTO events(ts, run_id, script, event_type, payload) "
            "VALUES (110, 'run-1', 'osaka', 'inventory.captured', ?)",
            (__import__('json').dumps({"phase": "before", "resources": {"小判": 1000}}),),
        )
        conn.commit()
        self.store.finish_run("run-1", "completed", ended_at=200)

        result = self.store.attach_inventory_snapshot(
            "run-1", {"resources": {"小判": 1300}}, captured_ts=220)

        self.assertTrue(result["has_resource_comparison"])
        self.assertEqual(result["resource_delta"], {"小判": 300})
        event = self.store.recent_events(event_type="inventory.captured")[0]
        self.assertEqual(event["run_id"], "run-1")
        self.assertEqual(event["payload"]["source"], "manual_attach")

    def test_manual_inventory_snapshot_rejects_stale_data(self):
        self.store.start_run("run-1", "osaka", started_at=100)
        self.store.finish_run("run-1", "completed", ended_at=200)

        with self.assertRaisesRegex(ValueError, "早于这轮收工"):
            self.store.attach_inventory_snapshot(
                "run-1", {"resources": {"小判": 1300}}, captured_ts=190)

    def test_manual_inventory_snapshot_rejects_older_run(self):
        conn = self.store._conn()
        for run_id, started_at, ended_at in (("old", 100, 150), ("latest", 200, 250)):
            self.store.start_run(run_id, "osaka", started_at=started_at)
            conn.execute(
                "INSERT INTO events(ts, run_id, script, event_type, payload) "
                "VALUES (?, ?, 'osaka', 'inventory.captured', ?)",
                (started_at + 1, run_id,
                 __import__('json').dumps({"phase": "before", "resources": {"小判": 1000}})),
            )
            conn.commit()
            self.store.finish_run(run_id, "completed", ended_at=ended_at)

        with self.assertRaisesRegex(ValueError, "只能给最近一条"):
            self.store.attach_inventory_snapshot(
                "old", {"resources": {"小判": 1300}}, captured_ts=300)

    def test_inventory_gap_can_be_explained_without_changing_run_delta(self):
        self.store.start_run("first", "osaka", started_at=100)
        self.store.start_run("second", "osaka", started_at=300)
        conn = self.store._conn()
        samples = [
            (200, "first", {"phase": "after", "resources": {"小判": 1000, "木炭": 500}}),
            (310, "second", {"phase": "before", "resources": {"小判": 1200, "木炭": 480}}),
        ]
        for ts, run_id, payload in samples:
            conn.execute(
                "INSERT INTO events(ts, run_id, script, event_type, payload) "
                "VALUES (?, ?, 'osaka', 'inventory.captured', ?)",
                (ts, run_id, __import__('json').dumps(payload)),
            )
        conn.commit()

        gap = self.store.inventory_gaps()[0]
        self.assertEqual(gap["resource_delta"], {"小判": 200, "木炭": -20})
        self.assertFalse(gap["reported"])
        report = self.store.add_human_report(
            occurred_at=300, activities=["领邮箱"], source="gap",
            gap_key=gap["gap_key"])
        self.assertEqual(report["activities"], ["领邮箱"])
        self.assertTrue(self.store.inventory_gaps()[0]["reported"])
        self.assertEqual(self.store.recent_events(event_type="human.report"), [])

    def test_prune_only_removes_expired_observations_and_events(self):
        self.store.record_event("keep", {})
        conn = self.store._conn()
        old = time.time() - 100 * 86400
        conn.execute(
            "INSERT INTO events(ts, run_id, script, event_type, payload) "
            "VALUES (?, NULL, NULL, 'old', '{}')", (old,),
        )
        conn.commit()

        self.store.prune(retention_days=90)

        self.assertEqual([e["event_type"] for e in self.store.recent_events()], ["keep"])

    def test_default_prune_keeps_long_term_results_but_removes_old_ocr(self):
        old = time.time() - 100 * 86400
        conn = self.store._conn()
        conn.execute(
            "INSERT INTO events(ts, run_id, script, event_type, payload) "
            "VALUES (?, NULL, NULL, 'old.result', '{}')", (old,),
        )
        conn.execute(
            "INSERT INTO observations(ts, run_id, script, kind, roi, tokens) "
            "VALUES (?, NULL, NULL, 'match', '[]', '[]')", (old,),
        )
        conn.execute(
            "INSERT INTO human_reports(created_at, occurred_at, source, activities, note) "
            "VALUES (?, ?, 'manual', '[]', 'old report')", (old, old),
        )
        conn.commit()

        self.store.prune()

        self.assertEqual(self.store.recent_events()[0]["event_type"], "old.result")
        self.assertEqual(self.store.recent_observations(), [])
        self.assertEqual(self.store.human_reports()[0]["note"], "old report")

    def test_summary_aggregates_full_activity_without_recent_page_limit(self):
        conn = self.store._conn()
        now = time.time()
        for index in range(1005):
            conn.execute(
                "INSERT INTO events(ts, run_id, script, event_type, payload) "
                "VALUES (?, NULL, 'osaka', 'osaka.floor_completed', ?)",
                (now - index, __import__('json').dumps({"selected_floor": 88})),
            )
        conn.execute(
            "INSERT INTO events(ts, run_id, script, event_type, payload) "
            "VALUES (?, NULL, 'practice', 'practice.result', ?)",
            (now, __import__('json').dumps({"result": "胜利"})),
        )
        conn.commit()

        summary = self.store.summary(days=365)

        self.assertEqual(len(self.store.recent_events(limit=1000)), 1000)
        self.assertEqual(summary["activity"]["sorties"], 1005)
        self.assertEqual(summary["activity"]["practice"]["wins"], 1)
        self.assertEqual(summary["activity"]["sortie_groups"][0]["count"], 1005)

    def test_record_pages_accept_stable_cursors(self):
        first = self.store.record_event("first", {})
        second = self.store.record_event("second", {})

        self.assertEqual(self.store.recent_events(limit=1)[0]["id"], second)
        self.assertEqual(self.store.recent_events(limit=1, before_id=second)[0]["id"], first)

    def test_record_pages_can_filter_one_day_without_losing_cursors(self):
        conn = self.store._conn()
        for ts, event_type in ((100, "old"), (200, "target"), (300, "new")):
            conn.execute(
                "INSERT INTO events(ts, run_id, script, event_type, payload) "
                "VALUES (?, NULL, 'daily', ?, '{}')", (ts, event_type),
            )
        for run_id, started_at in (("old", 100), ("target", 200), ("new", 300)):
            self.store.start_run(run_id, "daily", started_at=started_at)
            self.store.finish_run(run_id, "completed", ended_at=started_at + 10)
        conn.commit()

        events = self.store.recent_events(from_ts=150, to_ts=250)
        runs = self.store.recent_run_summaries(from_ts=150, to_ts=250)

        self.assertEqual([event["event_type"] for event in events], ["target"])
        self.assertEqual([run["run_id"] for run in runs], ["target"])

    def test_public_api_contract_uses_versioned_store(self):
        from panel.server import api_data_events, api_data_ocr, api_data_summary

        self.store.record_event("repair.queued", {"name": "测试刀"})
        self.store.record_ocr(kind="match", roi=[0, 0, 10, 10],
                              expected="确定", match_mode="exact",
                              matched=True, tokens=[])
        with patch("touken.telemetry._store", self.store), \
                patch("panel.server.STATUS_DIR", Path(self.temp.name)):
            summary = asyncio.run(api_data_summary(days=30))
            events = asyncio.run(api_data_events(
                limit=10, event_type="repair.queued", script=""))
            observations = asyncio.run(api_data_ocr(
                limit=10, script="", matched=True))

        self.assertEqual(summary["schema_version"], TELEMETRY_SCHEMA_VERSION)
        self.assertIn("current_state", summary)
        self.assertEqual(events["items"][0]["payload"]["name"], "测试刀")
        self.assertEqual(observations["items"][0]["expected"], "确定")


if __name__ == "__main__":
    unittest.main()
