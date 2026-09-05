import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from panel import scheduler as s


class CoordinationTests(unittest.TestCase):
    def config(self):
        cfg = s._defaults()
        cfg["automation"]["enabled"] = True
        return cfg

    def job(self, key="first"):
        return dict(key=key, team_no=2, map_code="B1", late_min=0)

    def test_busy_job_survives_grace_window(self):
        queue = s.DeferredDispatches()
        cfg = self.config()
        queue.update(cfg, [self.job()], 100)
        jobs = queue.update(cfg, [], 4000)
        self.assertEqual(jobs[0]["key"], "first")
        self.assertEqual(jobs[0]["observed_at"], 100)

    def test_preset_keeps_first_missed_departure(self):
        queue = s.DeferredDispatches()
        cfg = self.config()
        queue.update(cfg, [self.job()], 100)
        self.assertEqual(queue.update(cfg, [self.job("next")], 1000)[0]["key"], "first")

    def test_edit_invalidates_held_jobs(self):
        queue = s.DeferredDispatches()
        cfg = self.config()
        queue.update(cfg, [self.job()], 100)
        cfg["automation"]["teams"] = [3, 4, 5]
        self.assertEqual(queue.update(cfg, [], 200), [])

    def test_custom_uses_latest_not_backlog(self):
        cfg = self.config()
        cfg["automation"].update(mode="custom", capitalist=True)
        cfg["entries"] = [dict(time="08:00", team_no=2, map_code="B1"),
                          dict(time="09:00", team_no=2, map_code="B2")]
        jobs = s._custom_due(cfg, 600, "2026-09-05")
        self.assertEqual([j["map_code"] for j in jobs], ["B2"])
        cfg["automation"]["last_runs"][jobs[0]["key"]] = "done"
        self.assertEqual(s._custom_due(cfg, 600, "2026-09-05"), [])

    def test_departed_team_waits_without_runner(self):
        now = time.time()
        records = {"2": dict(dispatched_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), duration_min=30)}
        self.assertFalse(s.team_available(2, records, now))
        self.assertTrue(s.team_available(2, records, now + 1801))

    def test_disabled_scheduler_releases_teams(self):
        cfg = self.config()
        self.assertEqual(s.managed_teams(cfg), {2, 3, 4})
        cfg["automation"]["enabled"] = False
        self.assertEqual(s.managed_teams(cfg), set())

    def test_closed_game_never_launches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(dict(adb_path="adb", adb_address="device", daily=dict(logout=dict(package="game.pkg")))))
            with patch("touken.emulator._run", return_value=Mock(returncode=1, stdout="")) as run:
                self.assertFalse(s._emulator_ready(str(path)))
                self.assertEqual(run.call_args.args[0][-2:], ["pidof", "game.pkg"])

    def test_common_plan_does_not_redispatch_owned_team(self):
        from panel.server import _build_expedition_manager
        cfg = self.config()
        cfg["common_plan"] = [dict(team_no=2, map_code="B1", enabled=True)]
        agent = Mock()
        agent.collect_expedition_stream.return_value = iter(["collected"])
        with patch.object(s, "load_config", return_value=cfg):
            messages = list(_build_expedition_manager(agent, "unused", {}))
        agent.collect_expedition_stream.assert_called_once_with(redispatch=None)
        agent.expedition_stream.assert_not_called()
        self.assertIn("collected", messages)

    def test_dispatch_failure_not_marked_done(self):
        cfg = self.config()
        job = {**self.job(), "shift_key": "lane", "observed_at": 100}
        records = {"2": dict(map_code="B1", dispatched_at="old")}
        self.assertFalse(s.record_completed_dispatch(cfg, job, "old", records, 700))
        self.assertEqual(cfg["automation"]["last_runs"], {})
        self.assertEqual(cfg["automation"]["lane_shifts"], {})

    def test_verified_departure_shifts_following_lane(self):
        cfg = self.config()
        cfg["automation"]["lane_shifts"]["lane"] = 5
        job = {**self.job(), "shift_key": "lane", "observed_at": 100}
        records = {"2": dict(map_code="B1", dispatched_at="new")}
        self.assertTrue(s.record_completed_dispatch(cfg, job, "old", records, 700))
        self.assertEqual(cfg["automation"]["lane_shifts"]["lane"], 15)
        self.assertEqual(cfg["automation"]["last_runs"]["first"], "new")
