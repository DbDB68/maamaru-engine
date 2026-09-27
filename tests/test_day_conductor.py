"""今日联队战大总管：只在授权时段启动一次，不抢远征、不补跑。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from panel import day_conductor as dc
from panel import server  # noqa: F401 - register gameplay workflow nodes
from panel.day_plan import save_plan
from touken.flow_control import FlowAborted


DAY = 2_000_000_000


def timeline(*, occupied=None, now=DAY + 8 * 3600):
    return {"day_start": DAY, "now": now, "expeditions": [],
            "activity": {"name": "联队战", "seconds_per_loop": 420,
                         "remaining_runs": 36, "event_end_at": DAY + 24 * 3600,
                         "occupied": occupied or []}}


class FakeRunner:
    def __init__(self):
        self.is_running = False
        self.current_run_id = None
        self.last_status = "completed"
        self.calls = []

    @property
    def last_run_result(self):
        return self.current_run_id, self.last_status

    def start(self, script, config_path, params):
        self.calls.append((script, config_path, params))
        self.is_running = True
        self.current_run_id = "run-1"
        return "run-1"


class DayConductorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.state_path = Path(self.folder.name) / "conductor.json"
        self.plan_path = Path(self.folder.name) / "plan.json"
        self.plan = save_plan(DAY, DAY + 24 * 3600,
                              [{"start_min": 600, "runs": 8}], self.plan_path)
        self.runner = FakeRunner()
        self.messages = []
        self.team_patch = patch.object(dc, "_for_team", side_effect=lambda tl, team: tl)
        self.team_patch.start()
        self.addCleanup(self.team_patch.stop)

    def arm(self):
        return dc.arm(self.plan, timeline(), dc.BUILTIN_ID, {}, self.state_path)

    def tick(self, now, tl=None):
        dc.tick(now, self.runner, lambda: tl or timeline(), lambda: {},
                "config.json", lambda script, msg: self.messages.append(msg),
                self.state_path, self.plan_path)

    def test_arm_starts_workflow_once_with_exact_block_runs(self):
        self.arm()
        self.tick(DAY + 600 * 60 - 1)
        self.assertEqual(self.runner.calls, [])
        self.tick(DAY + 600 * 60)
        self.assertEqual(len(self.runner.calls), 1)
        script, _, params = self.runner.calls[0]
        self.assertEqual(script, "workflow")
        self.assertEqual(params["scheduled_raid_runs"], 8)
        self.assertEqual(params["workflow_id"], dc.BUILTIN_ID)
        self.tick(DAY + 600 * 60 + 5)
        self.assertEqual(len(self.runner.calls), 1)
        self.runner.is_running = False
        self.tick(DAY + 600 * 60 + 10)
        self.assertEqual(dc.load_state(self.state_path)["blocks"][0]["status"], "ended")
        self.tick(DAY + 600 * 60 + 15)
        self.assertEqual(len(self.runner.calls), 1)

    def test_busy_or_offline_at_due_is_missed_without_catchup(self):
        self.arm()
        self.runner.is_running = True
        self.runner.current_run_id = "other"
        self.tick(DAY + 600 * 60)
        self.assertEqual(dc.load_state(self.state_path)["blocks"][0]["status"], "pending")
        self.tick(DAY + 600 * 60 + dc.START_GRACE_SEC + 1)
        self.assertEqual(dc.load_state(self.state_path)["blocks"][0]["status"], "missed")
        self.runner.is_running = False
        self.tick(DAY + 600 * 60 + 300)
        self.assertEqual(self.runner.calls, [])

    def test_new_expedition_collision_blocks_at_start(self):
        self.arm()
        blocked = timeline(occupied=[{"start_min": 598, "end_min": 605,
                                      "label": "10:00 部队三派遣"}])
        self.tick(DAY + 600 * 60, blocked)
        state = dc.load_state(self.state_path)
        self.assertEqual(state["blocks"][0]["status"], "blocked")
        self.assertIn("派遣", state["blocks"][0]["reason"])
        self.assertEqual(self.runner.calls, [])

    def test_changed_plan_disarms_before_start(self):
        self.arm()
        save_plan(DAY, DAY + 24 * 3600, [{"start_min": 610, "runs": 8}],
                  self.plan_path)
        self.tick(DAY + 600 * 60)
        self.assertFalse(dc.load_state(self.state_path)["enabled"])
        self.assertEqual(self.runner.calls, [])

    def test_changed_workflow_settings_disarm_before_start(self):
        self.arm()
        dc.tick(DAY + 600 * 60, self.runner, timeline,
                lambda: {"team_no": "4"}, "config.json",
                lambda script, msg: self.messages.append(msg),
                self.state_path, self.plan_path)
        self.assertFalse(dc.load_state(self.state_path)["enabled"])
        self.assertEqual(self.runner.calls, [])

    def test_interrupted_run_disarms_next_block(self):
        self.arm()
        self.tick(DAY + 600 * 60)
        self.runner.is_running = False
        self.runner.current_run_id = None  # 服务重启后不再掌握旧工人
        self.tick(DAY + 600 * 60 + 10)
        state = dc.load_state(self.state_path)
        self.assertFalse(state["enabled"])
        self.assertEqual(state["blocks"][0]["status"], "interrupted")

    def test_failed_worker_disarms_later_blocks(self):
        self.arm()
        self.tick(DAY + 600 * 60)
        self.runner.is_running = False
        self.runner.last_status = "failed"
        self.tick(DAY + 600 * 60 + 10)
        state = dc.load_state(self.state_path)
        self.assertFalse(state["enabled"])
        self.assertEqual(state["blocks"][0]["status"], "interrupted")

    def test_disarm_preserves_current_run_but_prevents_next_block(self):
        self.arm()
        self.tick(DAY + 600 * 60)
        dc.disarm(self.state_path)
        self.assertFalse(dc.load_state(self.state_path)["enabled"])
        self.assertTrue(self.runner.is_running)
        self.assertEqual(len(self.runner.calls), 1)

    def test_unknown_version_and_backup_preserve_previous_file(self):
        self.state_path.write_text('{"version":0,"old":"kept"}', encoding="utf-8")
        self.assertIsNone(dc.load_state(self.state_path))
        self.arm()
        backup = json.loads(self.state_path.with_suffix(".json.bak").read_text(
            encoding="utf-8"))
        self.assertEqual(backup["old"], "kept")
        before = self.state_path.read_text(encoding="utf-8")
        with patch.object(Path, "replace", side_effect=OSError("busy")):
            with self.assertRaises(OSError):
                dc.disarm(self.state_path)
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)

    def test_only_single_raid_step_can_be_scheduled(self):
        with patch.object(dc.workflow, "find_preset", return_value={
            "id": "mixed", "name": "混合", "after": "none", "daily_mode": False,
            "nodes": [{"type": "raid", "params": {}},
                      {"type": "wait_until", "params": {"time": "04:05"}}],
        }):
            with self.assertRaisesRegex(ValueError, "单个联队战"):
                dc.workflow_spec("mixed", {})

    def test_worker_uses_booked_runs_without_changing_saved_settings(self):
        settings = {"team_no": "3", "runs": 99}
        signature = dc.workflow_spec(dc.BUILTIN_ID, settings)["signature"]
        with patch.object(server, "_load_panel_settings", return_value={
            "params": {"raid": settings}}), \
             patch.object(server._workflow, "run_workflow", return_value=iter(["ok"])) as run:
            messages = list(server._build_workflow("config.json", {
                "workflow_id": dc.BUILTIN_ID, "scheduled_raid_runs": 8,
                "scheduled_workflow_signature": signature}))
            self.assertEqual(messages, ["ok"])
            self.assertEqual(run.call_args.args[1][0]["params"]["runs"], 8)
            self.assertEqual(settings["runs"], 99)
            run.reset_mock()
            with self.assertRaises(FlowAborted):
                list(server._build_workflow("config.json", {
                    "workflow_id": dc.BUILTIN_ID, "scheduled_raid_runs": 8,
                    "scheduled_workflow_signature": "old"}))
            run.assert_not_called()

    def test_failed_workflow_step_exits_as_failed_worker(self):
        def failed_flow(*args, **kwargs):
            yield "【工作流】这块翻车了"
            return False

        signature = dc.workflow_spec(dc.BUILTIN_ID, {})["signature"]
        with patch.object(server, "_load_panel_settings", return_value={"params": {}}), \
             patch.object(server._workflow, "run_workflow", side_effect=failed_flow):
            with self.assertRaises(FlowAborted):
                list(server._build_workflow("config.json", {
                    "workflow_id": dc.BUILTIN_ID, "scheduled_raid_runs": 8,
                    "scheduled_workflow_signature": signature}))

    def test_ledger_mode_cannot_arm_through_api(self):
        client = TestClient(server.app)
        with patch.object(server, "_ledger_mode", return_value=True):
            response = client.put("/api/day-conductor", json={
                "enabled": True, "workflow_id": dc.BUILTIN_ID})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
