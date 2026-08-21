import re
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "maamaru.iss"
RELEASE_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
INSTALLER_SMOKE = Path(__file__).resolve().parents[1] / "scripts" / "smoke_test_installer.ps1"


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

    def test_release_smoke_runs_before_publishing(self):
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        smoke_step = "验证安装、首次启动与卸载"
        publish_step = "发布 Release"
        self.assertIn(smoke_step, workflow)
        self.assertIn("scripts/smoke_test_installer.ps1", workflow)
        self.assertLess(workflow.index(smoke_step), workflow.index(publish_step))
        self.assertIn("if: startsWith(github.ref, 'refs/tags/v')", workflow)

    def test_installer_smoke_covers_clean_install_and_data_survival(self):
        script = INSTALLER_SMOKE.read_text(encoding="utf-8")
        for required in (
            "/DIR=",
            "--panel",
            "http://127.0.0.1:8080/api/status",
            "installer-smoke-preserve.txt",
            "uninstall_preserved_user_data",
        ):
            self.assertIn(required, script)


if __name__ == "__main__":
    unittest.main()
