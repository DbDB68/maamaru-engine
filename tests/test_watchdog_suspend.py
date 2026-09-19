"""看门狗对系统休眠的容忍：电脑睡着时工人被一起冻结，醒来不得误杀。"""
import tempfile
import unittest
from unittest.mock import Mock, patch

_data = tempfile.TemporaryDirectory(prefix="watchdog_suspend_")
with patch.dict("os.environ", {"MAAMARU_DATA_DIR": _data.name}):
    from panel.script_runner import ScriptRunner


class FakeClock:
    """time 替身：sleep 按剧本推进表针，模拟看门狗线程被系统冻结。"""

    def __init__(self, steps):
        self.now = 1000.0
        self.steps = list(steps)

    def time(self):
        return self.now

    def sleep(self, _seconds):
        self.now += self.steps.pop(0) if self.steps else 5.0


class WatchdogSuspendTests(unittest.TestCase):
    def setUp(self):
        self.runner = ScriptRunner()
        self.proc = Mock()
        patches = [
            patch.object(self.runner, "_emit"),
            patch("panel.script_runner.get_store"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def run_watchdog(self, clock):
        with patch("panel.script_runner.time", clock):
            self.runner._watchdog(self.proc, "run1", "workflow")

    def test_system_suspend_resets_silence_baseline_instead_of_killing(self):
        # 工人已经 500 秒没出声，随后整台电脑睡了 200 秒——没有容错会被冤杀
        self.runner._last_output = 500.0
        clock = FakeClock([200, 5, 5])
        self.proc.poll.side_effect = [None, 0]
        self.run_watchdog(clock)
        self.proc.kill.assert_not_called()
        self.assertEqual(self.runner._stop_reason, "")
        note = self.runner._emit.call_args_list[0][0][2]
        self.assertIn("系统休眠", note)
        # 静默基线被清零到苏醒时刻，不再追究睡前欠下的沉默
        self.assertEqual(self.runner._last_output, 1200.0)

    def test_real_hang_is_still_killed(self):
        # 没有系统休眠、工人真卡死：照杀不误
        self.runner._last_output = 100.0
        clock = FakeClock([5, 5])
        self.proc.poll.return_value = None
        self.run_watchdog(clock)
        self.proc.kill.assert_called_once()
        self.assertEqual(self.runner._stop_reason, "watchdog")


if __name__ == "__main__":
    unittest.main()
