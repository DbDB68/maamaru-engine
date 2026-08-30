import os
import unittest
from unittest.mock import patch

from panel import server


class LedgerModeTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
