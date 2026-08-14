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
