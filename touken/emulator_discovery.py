"""Conservative MuMu 12 discovery for first-run packaged installs."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .runtime_paths import CONFIG_PATH


@dataclass(frozen=True)
class EmulatorInstallation:
    adb_path: Path
    manager_path: Path
    adb_address: str = "127.0.0.1:16384"


_MANAGER_RELATIVE_PATHS = (
    Path("nx_main/MuMuManager.exe"),
    Path("shell/MuMuManager.exe"),
)

_ADB_RELATIVE_PATHS = (
    Path("nx_device/12.0/shell/adb.exe"),
    Path("nx_main/adb.exe"),
    Path("shell/adb.exe"),
)


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = Path(path).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def _root_candidates_from_value(value: object) -> list[Path]:
    text = os.path.expandvars(str(value or "").strip())
    if not text:
        return []
    if text.startswith('"'):
        closing = text.find('"', 1)
        text = text[1:closing] if closing > 1 else text.strip('"')
    else:
        exe_end = text.casefold().find(".exe")
        if exe_end >= 0:
            text = text[:exe_end + 4]
    path = Path(text)
    if path.suffix.casefold() == ".exe":
        path = path.parent
    return [path, path.parent, path.parent.parent, path.parent.parent.parent]


def _registry_install_roots() -> list[Path]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    roots: list[Path] = []
    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    views = tuple(dict.fromkeys((
        getattr(winreg, "KEY_WOW64_64KEY", 0),
        getattr(winreg, "KEY_WOW64_32KEY", 0),
        0,
    )))
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in views:
            try:
                with winreg.OpenKey(
                        hive, uninstall_key, 0, winreg.KEY_READ | view) as parent:
                    count = winreg.QueryInfoKey(parent)[0]
                    for index in range(count):
                        try:
                            name = winreg.EnumKey(parent, index)
                            with winreg.OpenKey(parent, name) as child:
                                display_name = str(winreg.QueryValueEx(child, "DisplayName")[0])
                                if "mumu" not in display_name.casefold():
                                    continue
                                for value_name in ("InstallLocation", "DisplayIcon", "UninstallString"):
                                    try:
                                        value = winreg.QueryValueEx(child, value_name)[0]
                                    except OSError:
                                        continue
                                    roots.extend(_root_candidates_from_value(value))
                        except OSError:
                            continue
            except OSError:
                continue
    return _unique_paths(roots)


def _common_install_roots() -> list[Path]:
    bases: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(variable, "").strip()
        if value:
            bases.append(Path(value))
    drives = getattr(os, "listdrives", lambda: (os.environ.get("SystemDrive", "C:") + "/",))()
    for drive_name in drives:
        drive = Path(drive_name)
        bases.extend((drive, drive / "Program Files", drive / "Program Files (x86)"))

    roots: list[Path] = []
    names = (
        Path("Netease/MuMuPlayer"),
        Path("Netease/MuMuPlayer-12.0"),
        Path("Netease/MuMuPlayerGlobal-12.0"),
        Path("Netease/MuMu Player 12"),
        Path("MUMU/MuMuPlayer"),
        Path("MuMu/MuMuPlayer"),
    )
    for base in bases:
        roots.extend(base / name for name in names)

    manager_on_path = shutil.which("MuMuManager.exe")
    if manager_on_path:
        roots.extend(_root_candidates_from_value(manager_on_path))
    return _unique_paths(roots)


def _probe_root(root: Path) -> EmulatorInstallation | None:
    managers = [root / relative for relative in _MANAGER_RELATIVE_PATHS]
    adbs = [root / relative for relative in _ADB_RELATIVE_PATHS]
    manager = next((path for path in managers if path.is_file()), None)
    adb = next((path for path in adbs if path.is_file()), None)
    if manager is None or adb is None:
        return None
    return EmulatorInstallation(adb.resolve(), manager.resolve())


def discover_mumu_installation(
    *,
    extra_roots: Iterable[Path] = (),
    include_system: bool = True,
) -> EmulatorInstallation | None:
    roots = list(extra_roots)
    if include_system:
        roots.extend(_registry_install_roots())
        roots.extend(_common_install_roots())
    for root in _unique_paths(roots):
        found = _probe_root(root)
        if found is not None:
            return found
    return None


def _read_config(path: Path) -> dict | None:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return config if isinstance(config, dict) else None


def _write_config(path: Path, config: dict) -> bool:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return True
    except OSError:
        temporary.unlink(missing_ok=True)
        return False


def auto_configure_emulator(
    config_path: Path = CONFIG_PATH,
    *,
    extra_roots: Iterable[Path] = (),
    include_system: bool = True,
) -> EmulatorInstallation | None:
    """Fill only blank emulator fields; never replace a user's chosen path."""
    path = Path(config_path)
    config = _read_config(path)
    if config is None:
        return None

    adb_value = str(config.get("adb_path", "")).strip()
    manager_value = str(config.get("emulator_manager", "")).strip()
    if adb_value and manager_value:
        return None

    configured_roots: list[Path] = []
    configured_roots.extend(_root_candidates_from_value(adb_value))
    configured_roots.extend(_root_candidates_from_value(manager_value))
    found = discover_mumu_installation(
        extra_roots=(*configured_roots, *extra_roots),
        include_system=include_system,
    )
    if found is None:
        return None

    changed = False
    if not adb_value:
        config["adb_path"] = str(found.adb_path)
        changed = True
    if not manager_value:
        config["emulator_manager"] = str(found.manager_path)
        changed = True
    if not str(config.get("adb_address", "")).strip():
        config["adb_address"] = found.adb_address
        changed = True
    if not changed:
        return None

    if not _write_config(path, config):
        return None
    return found


def configure_mumu_from_folder(
    selected_folder: str | Path,
    config_path: Path = CONFIG_PATH,
) -> EmulatorInstallation | None:
    """Apply an explicit user-selected MuMu folder after validating both tools."""
    selected = Path(selected_folder).expanduser()
    roots = _root_candidates_from_value(selected)
    found = discover_mumu_installation(extra_roots=roots, include_system=False)
    if found is None:
        return None
    path = Path(config_path)
    config = _read_config(path)
    if config is None:
        return None
    config["adb_path"] = str(found.adb_path)
    config["emulator_manager"] = str(found.manager_path)
    if not str(config.get("adb_address", "")).strip():
        config["adb_address"] = found.adb_address
    return found if _write_config(path, config) else None
