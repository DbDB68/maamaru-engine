import re
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "maamaru.iss"


class InstallerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = INSTALLER.read_text(encoding="utf-8")

    def test_installs_per_user_without_elevation(self):
        self.assertIn(r"DefaultDirName={localappdata}\Programs\Maamaru", self.script)
        self.assertIn("PrivilegesRequired=lowest", self.script)

    def test_installer_only_packages_program_files(self):
        sources = re.findall(r'^Source:\s*"([^"]+)"', self.script, flags=re.MULTILINE)
        self.assertEqual(
            sources,
            [
                r"{#PackageDir}\まあ丸启动器.exe",
                r"{#PackageDir}\manifest.json",
            ],
        )

    def test_shortcuts_are_registered_to_the_installed_launcher(self):
        self.assertIn(r'Name: "{group}\まあ丸"; Filename: "{app}\まあ丸启动器.exe"', self.script)
        self.assertIn(r'Name: "{autodesktop}\まあ丸"; Filename: "{app}\まあ丸启动器.exe"', self.script)
        self.assertIn('Flags: unchecked', self.script)

    def test_uninstall_cannot_delete_user_data(self):
        self.assertNotRegex(self.script, r"(?im)^\[UninstallDelete\]\s*$")
        self.assertNotRegex(self.script, r"(?im)^Type:\s*filesandordirs")
        self.assertNotRegex(self.script, r"(?im)^Name:\s*.*\\Maamaru(?:\\|\s*$)")


if __name__ == "__main__":
    unittest.main()
