import os
import threading
import unittest
from unittest.mock import patch

from panel import server


class LedgerModeTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        server.configure_app_mode(None)

    async def test_startup_skips_all_automation_services(self):
        with (
            patch.dict(os.environ, {"MAAMARU_LEDGER_MODE": "1"}),
            patch.object(server, "_start_broadcast") as broadcast,
            patch.object(server, "get_runner") as runner,
        ):
            await server._startup()

        broadcast.assert_not_called()
        runner.assert_not_called()

    async def test_mode_endpoint_reports_ledger(self):
        with patch.dict(os.environ, {"MAAMARU_LEDGER_MODE": "true"}):
            self.assertEqual(await server.api_app_mode(), {
                "mode": "ledger",
                "automation_enabled": False,
            })

    async def test_scripts_are_hidden_without_touching_runner(self):
        with (
            patch.dict(os.environ, {"MAAMARU_LEDGER_MODE": "1"}),
            patch.object(server, "get_runner") as runner,
        ):
            result = await server.api_scripts()

        self.assertEqual(result["scripts"], {})
        self.assertFalse(result["running"])
        runner.assert_not_called()

    def test_ledger_and_automation_server_threads_keep_separate_modes(self):
        barrier = threading.Barrier(2)
        results = {}

        def read_mode(name, ledger_mode):
            server.configure_app_mode(ledger_mode)
            barrier.wait()
            results[name] = server._ledger_mode()

        ledger = threading.Thread(target=read_mode, args=("ledger", True))
        automation = threading.Thread(target=read_mode, args=("automation", False))
        ledger.start()
        automation.start()
        ledger.join()
        automation.join()

        self.assertEqual(results, {"ledger": True, "automation": False})


if __name__ == "__main__":
    unittest.main()
