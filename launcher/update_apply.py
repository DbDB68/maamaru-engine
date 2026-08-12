"""Hand an already verified installer to a detached updater with rollback."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from touken.runtime_paths import DATA_ROOT, UPDATES_DIR


RESULT_PATH = UPDATES_DIR / "last-result.json"


class ApplyError(RuntimeError):
    """The staged installer or update plan is unsafe to apply."""


def prepare_apply(installer: Path, expected_sha256: str, version: str) -> dict:
    """Recheck a staged installer, create a plan, and launch the detached helper."""
    installer = Path(installer).resolve()
    updates = UPDATES_DIR.resolve()
    if not installer.is_file() or not installer.is_relative_to(updates):
        raise ApplyError("安装包不在まあ丸的更新暂存区")
    if _sha256(installer) != expected_sha256.lower():
        raise ApplyError("安装前复核失败，安装包可能已经发生变化")

    program_dir = _program_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = updates / "backups" / f"before-{version}-{stamp}"
    plan_path = updates / f"apply-{version}.json"
    plan = {
        "version": version,
        "installer": str(installer),
        "sha256": expected_sha256.lower(),
        "program_dir": str(program_dir),
        "backup_dir": str(backup_dir),
        "previous_executable": str(Path(sys.executable).resolve()),
        "parent_pid": os.getpid(),
        "data_root": str(DATA_ROOT.resolve()),
    }
    _write_json(plan_path, plan)

    if getattr(sys, "frozen", False):
        helper = updates / "maamaru-update-helper.exe"
        shutil.copy2(Path(sys.executable).resolve(), helper)
        command = [str(helper), "--apply-update", str(plan_path)]
    else:
        command = [sys.executable, "-m", "launcher.update_apply", str(plan_path)]
    subprocess.Popen(command, close_fds=True, creationflags=_detached_flags())
    return {"plan": str(plan_path), "program_dir": str(program_dir)}


def run_plan(plan_path: Path) -> int:
    """Wait for the launcher, snapshot its program directory, then run Inno Setup."""
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    _validate_plan(plan)
    installer = Path(plan["installer"])
    program_dir = Path(plan["program_dir"])
    backup_dir = Path(plan["backup_dir"])
    previous_executable = Path(plan["previous_executable"])

    _wait_for_process(int(plan["parent_pid"]), timeout=30)
    if _sha256(installer) != plan["sha256"]:
        _record_result(False, plan, "安装前复核失败，未运行安装器", rolled_back=False)
        _restart(previous_executable)
        return 2

    had_program = program_dir.is_dir()
    if had_program:
        shutil.copytree(program_dir, backup_dir, dirs_exist_ok=False)

    result = subprocess.run([
        str(installer),
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        f"/DIR={program_dir}",
    ], check=False)
    if result.returncode == 0:
        target = program_dir / "まあ丸启动器.exe"
        _record_result(True, plan, f"已安装 v{plan['version']}", rolled_back=False)
        _restart(target)
        return 0

    rolled_back = False
    if had_program and backup_dir.is_dir():
        shutil.rmtree(program_dir, ignore_errors=True)
        shutil.copytree(backup_dir, program_dir)
        rolled_back = True
    message = f"安装器返回错误码 {result.returncode}"
    _record_result(False, plan, message, rolled_back=rolled_back)
    restart = program_dir / "まあ丸启动器.exe" if rolled_back else previous_executable
    _restart(restart)
    return result.returncode or 1


def consume_result() -> dict | None:
    try:
        result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        RESULT_PATH.unlink(missing_ok=True)
        return result
    except (OSError, ValueError, TypeError):
        return None


def _validate_plan(plan: dict) -> None:
    updates = UPDATES_DIR.resolve()
    installer = Path(plan["installer"]).resolve()
    backup = Path(plan["backup_dir"]).resolve()
    data_root = Path(plan["data_root"]).resolve()
    if not installer.is_relative_to(updates) or not backup.is_relative_to(updates / "backups"):
        raise ApplyError("更新计划指向了暂存区以外的文件")
    if data_root != DATA_ROOT.resolve():
        raise ApplyError("更新计划的用户数据目录不匹配")
    program_dir = Path(plan["program_dir"]).resolve()
    if program_dir != _program_dir().resolve():
        raise ApplyError("更新计划的程序目录不匹配")
    if program_dir == data_root or program_dir.is_relative_to(data_root):
        raise ApplyError("程序目录不能位于用户数据目录内")


def _program_dir() -> Path:
    if getattr(sys, "frozen", False):
        current = Path(sys.executable).resolve().parent
        if (current / "manifest.json").is_file():
            return current
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return (local / "Programs" / "Maamaru").resolve()


def _wait_for_process(pid: int, timeout: int) -> None:
    if os.name != "nt":
        return
    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if handle:
        try:
            ctypes.windll.kernel32.WaitForSingleObject(handle, timeout * 1000)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)


def _restart(executable: Path) -> None:
    if executable.is_file():
        subprocess.Popen([str(executable)], close_fds=True, creationflags=_detached_flags())


def _detached_flags() -> int:
    return getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _record_result(ok: bool, plan: dict, message: str, rolled_back: bool) -> None:
    _write_json(RESULT_PATH, {
        "ok": ok,
        "version": plan["version"],
        "message": message,
        "rolled_back": rolled_back,
        "backup_dir": plan["backup_dir"] if Path(plan["backup_dir"]).is_dir() else None,
    })


if __name__ == "__main__":
    raise SystemExit(run_plan(Path(sys.argv[1])))
