import json
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from touken import incidents
from touken.incidents import list_incidents, report_incident, resolve_incidents, set_status


def _kwargs(**over):
    base = dict(
        severity="urgent",
        title="大阪城半路崩溃",
        cause="可能是画面识别卡住",
        action="去看成绩单和日志",
        needs_human=True,
        entry={"tab": "report"},
    )
    base.update(over)
    return base


class IncidentStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "incidents.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_new_incident_is_saved_with_unified_fields(self):
        item, is_new = report_incident("crash:osaka", path=self.path, **_kwargs())
        self.assertTrue(is_new)
        self.assertEqual(item["code"], "crash:osaka")
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["count"], 1)
        for field in ("title", "cause", "action", "needs_human", "entry"):
            self.assertIn(field, item)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["items"][0]["code"], "crash:osaka")

    def test_same_code_dedups_and_counts(self):
        report_incident("crash:osaka", path=self.path, **_kwargs())
        item, is_new = report_incident("crash:osaka", path=self.path, **_kwargs())
        self.assertFalse(is_new)
        self.assertEqual(item["count"], 2)
        self.assertEqual(len(list_incidents(path=self.path)), 1)

    def test_different_codes_coexist(self):
        report_incident("crash:osaka", path=self.path, **_kwargs())
        report_incident("watchdog:osaka", path=self.path, **_kwargs())
        self.assertEqual(len(list_incidents(path=self.path)), 2)

    def test_acknowledged_incident_stays_quiet_within_cooldown(self):
        report_incident("crash:osaka", path=self.path, **_kwargs())
        set_status("crash:osaka", "acknowledged", path=self.path)
        item, reactivated = report_incident("crash:osaka", path=self.path, **_kwargs())
        self.assertFalse(reactivated)
        self.assertEqual(item["status"], "acknowledged")

    def test_acknowledged_incident_reactivates_after_cooldown(self):
        report_incident("crash:osaka", path=self.path, **_kwargs())
        acked = set_status("crash:osaka", "acknowledged", path=self.path)
        # 把确认时间拨到冷却期之前，模拟老毛病隔了很久复发
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["items"][0]["last_seen_ack"] = time.time() - incidents._REACTIVATE_COOLDOWN_SEC - 1
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertIsNotNone(acked)
        item, reactivated = report_incident("crash:osaka", path=self.path, **_kwargs())
        self.assertTrue(reactivated)
        self.assertEqual(item["status"], "active")

    def test_resolve_then_reopen_creates_fresh_incident(self):
        report_incident("daily-fail", path=self.path, **_kwargs())
        resolve_incidents("daily-fail", path=self.path)
        item, is_new = report_incident("daily-fail", path=self.path, **_kwargs())
        self.assertTrue(is_new)
        self.assertEqual(item["count"], 1)

    def test_resolve_by_prefix(self):
        report_incident("crash:osaka", path=self.path, **_kwargs())
        report_incident("crash:daily", path=self.path, **_kwargs())
        self.assertEqual(resolve_incidents("crash:", path=self.path), 2)
        remaining = [i for i in list_incidents(path=self.path) if i["status"] != "resolved"]
        self.assertEqual(remaining, [])

    def test_set_status_rejects_unknown_status(self):
        report_incident("crash:osaka", path=self.path, **_kwargs())
        self.assertIsNone(set_status("crash:osaka", "bogus", path=self.path))

    def test_store_is_capped(self):
        for index in range(incidents._MAX_INCIDENTS + 5):
            report_incident(f"crash:s{index}", path=self.path, **_kwargs())
        self.assertEqual(len(list_incidents(path=self.path)), incidents._MAX_INCIDENTS)

    def test_unknown_severity_falls_back_to_warning(self):
        item, _ = report_incident("crash:osaka", path=self.path, **_kwargs(severity="ohno"))
        self.assertEqual(item["severity"], "warning")


if __name__ == "__main__":
    unittest.main()


class IncidentFeedTests(unittest.TestCase):
    """消息检测器：崩溃/看门狗立案，日课按成绩单立案或销案。"""

    def _feed(self):
        from panel import incident_feed
        return incident_feed

    def test_crash_message_files_urgent_incident(self):
        feed = self._feed()
        calls = []
        with unittest.mock.patch.object(feed, "report_incident", lambda *a, **k: calls.append((a, k)) or ({}, True)):
            feed.feed({"script": "osaka", "run_id": "r1", "message": "[面板] 脚本崩溃: boom"})
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[0], "crash:osaka")
        self.assertEqual(kwargs["severity"], "urgent")
        self.assertTrue(kwargs["needs_human"])

    def test_watchdog_message_files_urgent_incident(self):
        feed = self._feed()
        calls = []
        with unittest.mock.patch.object(feed, "report_incident", lambda *a, **k: calls.append((a, k)) or ({}, True)):
            feed.feed({"script": "daily", "run_id": "r1", "message": "[看门狗] ⚠️ 工人进程 300 秒一行输出都没有"})
        self.assertEqual(calls[0][0][0], "watchdog:daily")

    def test_normal_message_files_nothing(self):
        feed = self._feed()
        calls = []
        with unittest.mock.patch.object(feed, "report_incident", lambda *a, **k: calls.append((a, k)) or ({}, True)):
            feed.feed({"script": "osaka", "run_id": "r1", "message": "[大阪城] 第 3 圈收工"})
        self.assertEqual(calls, [])

    def test_daily_all_green_resolves_daily_fail(self):
        feed = self._feed()
        report = {"steps": [{"name": "锻刀", "status": "✓"}, {"name": "远征", "status": "✓"}]}
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(feed, "STATE_DIR", Path(tmp)), \
                unittest.mock.patch.object(feed, "report_incident") as mock_report, \
                unittest.mock.patch.object(feed, "resolve_incidents") as mock_resolve:
            (Path(tmp) / "latest_report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            feed.feed({"script": "daily", "run_id": "r1", "message": "[脚本] 完成"})
        mock_report.assert_not_called()
        mock_resolve.assert_called_once_with("daily-fail")

    def test_daily_failure_files_warning_without_human(self):
        feed = self._feed()
        report = {"steps": [{"name": "锻刀", "status": "✗ 超时"}]}
        calls = []
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(feed, "STATE_DIR", Path(tmp)), \
                unittest.mock.patch.object(feed, "report_incident", lambda *a, **k: calls.append((a, k)) or ({}, True)):
            (Path(tmp) / "latest_report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            feed.feed({"script": "daily", "run_id": "r1", "message": "[脚本] 完成"})
        self.assertEqual(calls[0][0][0], "daily-fail")
        self.assertEqual(calls[0][1]["severity"], "warning")
        self.assertFalse(calls[0][1]["needs_human"])
