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
                patch.object(app.webview, "start"):
            app.main()

        kwargs = create_window.call_args.kwargs
        self.assertEqual((kwargs["width"], kwargs["height"]), (1360, 900))
        self.assertIn(f"v{app.CURRENT_VERSION}", kwargs["html"])


if __name__ == "__main__":
    unittest.main()
