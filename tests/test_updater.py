import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import updater


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class UpdaterTests(unittest.TestCase):
    def _asset(self, payload=b"installer"):
        digest = hashlib.sha256(payload).hexdigest()
        return {
            "tag": "v0.1.6",
            "version": "0.1.6",
            "name": "maamaru-setup-v0.1.6.exe",
            "digest": f"sha256:{digest}",
            "url": "https://github.com/DbDB68/maamaru-engine/releases/download/v0.1.6/maamaru-setup-v0.1.6.exe",
            "size": len(payload),
        }

    def test_select_installer_accepts_only_the_expected_official_asset(self):
        asset = self._asset()
        release = {"tag_name": "v0.1.6", "assets": [{
            "name": asset["name"], "digest": asset["digest"],
            "browser_download_url": asset["url"], "size": asset["size"],
        }]}
        self.assertEqual(updater.select_installer(release), asset)

    def test_download_is_verified_and_moved_out_of_the_partial_name(self):
        payload = b"installer"
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(updater.urllib.request, "urlopen", return_value=_Response(payload)):
            result = updater.download_installer(self._asset(payload), Path(tmp))
            target = Path(result["path"])
            self.assertEqual(target.read_bytes(), payload)
            self.assertFalse(target.with_suffix(".exe.part").exists())
            self.assertTrue((target.parent / "download.json").is_file())

    def test_bad_download_is_deleted_instead_of_becoming_an_update(self):
        asset = self._asset(b"expected")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(updater.urllib.request, "urlopen", return_value=_Response(b"tampered")):
            with self.assertRaises(updater.UpdateError):
                updater.download_installer(asset, Path(tmp))
            self.assertEqual(list(Path(tmp).rglob("*.exe*")), [])


if __name__ == "__main__":
    unittest.main()
