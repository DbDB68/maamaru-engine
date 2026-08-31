import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from touken.ledger_onboarding import get_onboarding, update_onboarding
from touken.telemetry import TelemetryStore


class LedgerOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TelemetryStore(self.root / "telemetry.db")
        self.state_path = self.root / "status" / "ledger_onboarding.json"

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _event(self, event_type, payload):
        self.store._conn().execute(
            "INSERT INTO events(ts, run_id, script, event_type, payload) "
            "VALUES (100, 'run-1', 'daily', ?, ?)",
            (event_type, json.dumps(payload, ensure_ascii=False)),
        )
        self.store._conn().commit()

    def test_empty_ledger_is_visible_and_can_be_dismissed(self):
        initial = get_onboarding(self.store, self.state_path)

        self.assertTrue(initial["visible"])
        self.assertEqual(initial["status"], "pending")
        self.assertEqual(initial["step"], 1)
        dismissed = update_onboarding(self.store, self.state_path, "dismiss")
        self.assertFalse(dismissed["visible"])
        self.assertEqual(dismissed["status"], "dismissed")
        self.assertEqual(get_onboarding(self.store, self.state_path)["status"], "dismissed")

    def test_existing_ledger_never_interrupts_old_user(self):
        self._event("inventory.peek", {"木炭": 1234})

        result = get_onboarding(self.store, self.state_path)

        self.assertFalse(result["visible"])
        self.assertEqual(result["status"], "not_needed")
        self.assertEqual(result["reason"], "existing_ledger")
        self.assertFalse(self.state_path.exists())

    def test_started_flow_continues_after_first_inventory_and_completes(self):
        started = update_onboarding(self.store, self.state_path, "start")
        self.assertEqual(started["status"], "active")
        self.store.add_manual_inventory({"小判": 1000}, observed_at=100)

        resumed = get_onboarding(self.store, self.state_path)
        self.assertTrue(resumed["visible"])
        self.assertEqual(resumed["step"], 2)
        advanced = update_onboarding(self.store, self.state_path, "advance", step=3)
        self.assertEqual(advanced["step"], 3)
        completed = update_onboarding(self.store, self.state_path, "complete")
        self.assertFalse(completed["visible"])
        self.assertEqual(completed["status"], "completed")

    def test_inventory_event_requires_a_real_number(self):
        self._event("inventory.captured", {"resources": {"小判": None, "木炭": True}})
        self._event("resource.change", {"resource": "小判", "delta": 300})
        self.assertTrue(get_onboarding(self.store, self.state_path)["visible"])

        self._event("osaka.koban_session", {"before": 1000, "after": 1300})
        self.assertFalse(get_onboarding(self.store, self.state_path)["visible"])

    def test_public_api_roundtrip_uses_status_directory(self):
        from panel.server import api_ledger_onboarding, api_update_ledger_onboarding

        class _Req:
            async def json(self):
                return {"action": "start"}

        with patch("touken.telemetry._store", self.store), \
                patch("panel.server.STATUS_DIR", self.root / "api-status"):
            initial = asyncio.run(api_ledger_onboarding())
            started = asyncio.run(api_update_ledger_onboarding(_Req()))

        self.assertTrue(initial["visible"])
        self.assertTrue(started["ok"])
        self.assertEqual(started["status"], "active")
        self.assertTrue((self.root / "api-status" / "ledger_onboarding.json").is_file())


if __name__ == "__main__":
    unittest.main()
