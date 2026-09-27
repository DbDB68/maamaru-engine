"""今日安排的冲突核对和保存边界。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from panel.day_plan import load_plan, review_plan, save_plan


def _timeline():
    day = 2_000_000_000
    return {
        "day_start": day,
        "now": day + 8 * 3600,
        "activity": {
            "name": "联队战", "seconds_per_loop": 420,
            "remaining_runs": 36, "event_end_at": day + 24 * 3600,
            "occupied": [{"start_min": 598, "end_min": 605,
                          "label": "10:00 部队三派遣"}],
        },
    }


class DayPlanTests(unittest.TestCase):
    def test_good_plan_and_expedition_collision(self):
        timeline = _timeline()
        plan = {"day_start": timeline["day_start"],
                "event_end_at": timeline["activity"]["event_end_at"],
                "blocks": [{"start_min": 480, "runs": 16}]}
        self.assertEqual(review_plan(plan, timeline), [])
        plan["blocks"][0]["runs"] = 17
        self.assertIn("派遣", "".join(review_plan(plan, timeline)))

    def test_changed_schedule_and_rollover_are_not_silent(self):
        timeline = _timeline()
        plan = {"day_start": timeline["day_start"],
                "event_end_at": timeline["activity"]["event_end_at"],
                "blocks": [{"start_min": 480, "runs": 16}]}
        timeline["activity"]["occupied"][0]["start_min"] = 550
        self.assertIn("派遣", "".join(review_plan(plan, timeline)))
        timeline["day_start"] += 86400
        self.assertIn("不是今天", "".join(review_plan(plan, timeline)))

    def test_bad_values_rejected(self):
        timeline = _timeline()
        plan = {"day_start": timeline["day_start"],
                "event_end_at": "oops",
                "blocks": [{"start_min": True, "runs": 100}]}
        self.assertTrue(review_plan(plan, timeline))

    def test_unknown_version_keeps_file_and_failed_replace_keeps_old_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "day_plan.json"
            path.write_text('{"version":0,"old":"kept"}', encoding="utf-8")
            self.assertIsNone(load_plan(path))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["old"], "kept")
            path.write_text('{"version":1,"blocks":"broken"}', encoding="utf-8")
            self.assertIsNone(load_plan(path))
            old = save_plan(1, 2, [{"start_min": 480, "runs": 2}], path)
            self.assertEqual(json.loads(path.with_suffix(".json.bak").read_text(encoding="utf-8"))["blocks"], "broken")
            with patch.object(Path, "replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    save_plan(1, 2, [{"start_min": 500, "runs": 3}], path)
            self.assertEqual(load_plan(path), old)


if __name__ == "__main__":
    unittest.main()
