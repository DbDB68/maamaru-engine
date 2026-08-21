import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import app


class LauncherMaintenanceTests(unittest.TestCase):
    def test_version_comparison_handles_tags_and_prerelease_suffixes(self):
        self.assertEqual(app._version_tuple("v0.1.4"), (0, 1, 4))
        self.assertGreater(app._version_tuple("0.2.0"), app._version_tuple("0.1.9"))

    def test_repair_backs_up_invalid_json_before_restoring_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "touken_config.json"
            source = root / "default.json"
            target.write_text("{broken", encoding="utf-8")
            source.write_text('{"ok": true}', encoding="utf-8")

            fake_paths = ((target, source, "本丸配置"),)
            with patch.object(app, "_runtime_defaults", return_value=fake_paths), \
                    patch.object(app, "ensure_runtime_data"):
                repaired = app._repair_runtime_files()

            self.assertEqual(target.read_text(encoding="utf-8"), '{"ok": true}')
            self.assertTrue(list(root.glob("touken_config.json.broken-*")))
            self.assertIn("已备份并重建损坏的本丸配置", repaired)

    def test_launcher_uses_panel_sized_window_without_maximizing(self):
        with patch.object(app, "ensure_runtime_data"), \
                patch.object(app.webview, "create_window") as create_window, \
                patch.object(app.webview, "start") as start:
            app.main()

        kwargs = create_window.call_args.kwargs
        self.assertEqual((kwargs["width"], kwargs["height"]), (1080, 720))
        self.assertEqual(kwargs["min_size"], (860, 640))
        self.assertIn(f"v{app.CURRENT_VERSION}", kwargs["html"])
        self.assertIn("data:image/png;base64,", kwargs["html"])
        self.assertEqual(
            Path(start.call_args.kwargs["icon"]).name,
            "maamaru-launcher.ico",
        )
        self.assertTrue(app._launcher_icon_path().is_file())

    def test_launcher_exports_bundle_and_reveals_it_in_explorer(self):
        bundle = Path(r"C:\Temp\maamaru-diagnostics-test.zip")
        with patch.object(app, "create_diagnostic_bundle", return_value=bundle), \
                patch.object(app.subprocess, "Popen") as popen:
            result = app.Api().export_diagnostics()

        self.assertTrue(result["ok"])
        self.assertIn(bundle.name, result["message"])
        self.assertEqual(popen.call_args.args[0], ["explorer.exe", "/select,", str(bundle)])


if __name__ == "__main__":
    unittest.main()
