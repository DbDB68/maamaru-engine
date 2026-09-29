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


def _raid_plan(timeline, blocks):
    return {"day_start": timeline["day_start"],
            "event_end_at": timeline["activity"]["event_end_at"],
            "blocks": blocks}


class DayPlanTests(unittest.TestCase):
    def test_good_plan_and_expedition_collision(self):
        timeline = _timeline()
        plan = _raid_plan(timeline, [{"start_min": 480, "kind": "raid",
                                      "runs": 16}])
        self.assertEqual(review_plan(plan, timeline), [])
        plan["blocks"][0]["runs"] = 17
        self.assertIn("派遣", "".join(review_plan(plan, timeline)))

    def test_changed_schedule_and_rollover_are_not_silent(self):
        timeline = _timeline()
        plan = _raid_plan(timeline, [{"start_min": 480, "kind": "raid",
                                      "runs": 16}])
        timeline["activity"]["occupied"][0]["start_min"] = 550
        self.assertIn("派遣", "".join(review_plan(plan, timeline)))
        timeline["day_start"] += 86400
        self.assertIn("不是今天", "".join(review_plan(plan, timeline)))

    def test_past_start_is_not_an_issue_anymore(self):
        # 新语义：开工时间已经过去不算错误——过点块保存即「尽快排队开工」。
        timeline = _timeline()
        plan = _raid_plan(timeline, [{"start_min": 300, "kind": "raid",
                                      "runs": 8}])
        self.assertEqual(review_plan(plan, timeline), [])

    def test_bad_values_rejected(self):
        timeline = _timeline()
        plan = {"day_start": timeline["day_start"],
                "event_end_at": "oops",
                "blocks": [{"start_min": True, "runs": 100}]}
        self.assertTrue(review_plan(plan, timeline))

    def test_v1_plan_migrates_to_v2_in_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "day_plan.json"
            path.write_text(json.dumps({
                "version": 1, "day_start": 123, "event_end_at": 456,
                "blocks": [{"start_min": 480, "runs": 2},
                           {"start_min": 600, "runs": 3}]}),
                encoding="utf-8")
            plan = load_plan(path)
        self.assertEqual(plan["version"], 2)
        self.assertEqual(plan["blocks"], [
            {"start_min": 480, "kind": "raid", "runs": 2},
            {"start_min": 600, "kind": "raid", "runs": 3},
        ])

    def test_workflow_and_daily_blocks_need_no_activity(self):
        # 纯 workflow/daily 安排：没有联队战活动卡片也能存，也不报进度核对。
        timeline = _timeline()
        timeline["activity"] = None
        plan = {"day_start": timeline["day_start"], "event_end_at": None,
                "blocks": [{"start_min": 480, "kind": "workflow",
                            "workflow_id": "wf1"},
                           {"start_min": 600, "kind": "daily"}]}
        self.assertEqual(review_plan(plan, timeline), [])

    def test_workflow_block_requires_workflow_id(self):
        timeline = _timeline()
        timeline["activity"] = None
        plan = {"day_start": timeline["day_start"], "event_end_at": None,
                "blocks": [{"start_min": 480, "kind": "workflow"}]}
        self.assertIn("任务流", "".join(review_plan(plan, timeline)))

    def test_raid_block_still_requires_activity(self):
        timeline = _timeline()
        timeline["activity"] = None
        plan = {"day_start": timeline["day_start"], "event_end_at": None,
                "blocks": [{"start_min": 480, "kind": "raid", "runs": 8}]}
        self.assertIn("联队战进度", "".join(review_plan(plan, timeline)))

    def test_mixed_blocks_overlap_uses_generic_estimates(self):
        # workflow/daily 块按时长 30 分钟估算占用：raid 480+56=536 与 570 不撞，
        # 与 510 撞。
        timeline = _timeline()
        base = [{"start_min": 480, "kind": "raid", "runs": 8},
                {"start_min": 570, "kind": "daily"}]
        plan = {"day_start": timeline["day_start"], "event_end_at": None,
                "blocks": base}
        self.assertEqual(review_plan(plan, timeline), [])
        plan["blocks"][1]["start_min"] = 510
        self.assertIn("重叠", "".join(review_plan(plan, timeline)))

    def test_blocks_must_be_sorted_and_capped(self):
        timeline = _timeline()
        plan = {"day_start": timeline["day_start"], "event_end_at": None,
                "blocks": [{"start_min": 600, "kind": "daily"},
                           {"start_min": 480, "kind": "daily"}]}
        self.assertIn("排列", "".join(review_plan(plan, timeline)))
        plan["blocks"] = [{"start_min": 60 + i * 40, "kind": "daily"}
                          for i in range(7)]
        self.assertIn("一至六个", "".join(review_plan(plan, timeline)))

    def test_unknown_version_keeps_file_and_failed_replace_keeps_old_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "day_plan.json"
            path.write_text('{"version":0,"old":"kept"}', encoding="utf-8")
            self.assertIsNone(load_plan(path))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["old"], "kept")
            path.write_text('{"version":1,"blocks":"broken"}', encoding="utf-8")
            self.assertIsNone(load_plan(path))
            old = save_plan(1, 2, [{"start_min": 480, "kind": "raid",
                                    "runs": 2}], path)
            self.assertEqual(json.loads(path.with_suffix(".json.bak").read_text(encoding="utf-8"))["blocks"], "broken")
            with patch.object(Path, "replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    save_plan(1, 2, [{"start_min": 500, "kind": "raid",
                                      "runs": 3}], path)
            self.assertEqual(load_plan(path), old)


if __name__ == "__main__":
    unittest.main()
