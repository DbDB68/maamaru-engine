import time
import unittest

from panel.server import _dashboard_expeditions, _dashboard_inventory


class DashboardStateTests(unittest.TestCase):
    def setUp(self):
        self.now_text = "2026-08-09 20:00:00"
        self.now = time.mktime(time.strptime(self.now_text, "%Y-%m-%d %H:%M:%S"))

    def test_furnace_countdown_accounts_for_snapshot_age(self):
        inventory = {
            "captured_at": "2026-08-09 19:59:30",
            "furnaces": [
                {"slot": 1, "state": "锻造中", "remain": "00:01:00"},
                {"slot": 2, "state": "锻造中", "remain": None},
            ],
        }

        result = _dashboard_inventory(inventory, self.now)

        self.assertEqual(result["furnaces"][0]["remain_sec"], 30)
        self.assertIsNone(result["furnaces"][1]["remain_sec"])

    def test_recently_finished_expedition_stays_visible(self):
        records = {"2": {
            "duration_min": 60,
            "dispatched_at": "2026-08-09 18:30:00",
            "map_code": "1-1",
        }}

        result = _dashboard_expeditions(records, self.now)

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["done"])

    def test_long_expired_expedition_is_hidden(self):
        records = {"5": {
            "duration_min": 60,
            "dispatched_at": "2026-08-08 18:00:00",
            "map_code": "E2",
        }}

        self.assertEqual(_dashboard_expeditions(records, self.now), [])


if __name__ == "__main__":
    unittest.main()
