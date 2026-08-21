"""Create a small, privacy-conscious bundle for user bug reports."""

from __future__ import annotations

import io
import os
import platform
import re
import sqlite3
import sys
import tempfile
import time
import zipfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from launcher.version import CURRENT_VERSION
from touken.runtime_paths import BUNDLE_ROOT, DATA_ROOT, DEBUG_DIR, LOG_DIR


_TEXT_TAIL_BYTES = 512 * 1024
_DEBUG_FILE_LIMIT = 6
_PANEL_LOG_LIMIT = 1000
_SECRET_PATTERN = re.compile(
    r"(?i)(token|secret|password|passwd|api[_-]?key|access[_-]?key)"
    r"(\s*[\"']?\s*[:=]\s*[\"']?)([^\s,;\"']+)"
)
_BEARER_PATTERN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;\"']+)")
_TOKEN_SHAPE_PATTERN = re.compile(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}\b")
_WINDOWS_USER_PATTERN = re.compile(r"(?i)[A-Z]:\\Users\\[^\\\r\n]+")


@dataclass(frozen=True)
class DiagnosticBundle:
    filename: str
    content: bytes


def _replacement_paths(data_root: Path, bundle_root: Path) -> list[tuple[str, str]]:
    values = [
        (str(data_root.resolve()), "<DATA_ROOT>"),
        (str(bundle_root.resolve()), "<PROGRAM_ROOT>"),
        (str(Path.home().resolve()), "<USER_HOME>"),
    ]
    # Longest first so a child data path is not partially replaced by the home path.
    return sorted(set(values), key=lambda item: len(item[0]), reverse=True)


def sanitize_text(text: str, *, data_root: Path = DATA_ROOT, bundle_root: Path = BUNDLE_ROOT) -> str:
    """Hide common local identity paths and accidental credentials in text logs."""
    sanitized = str(text)
    for original, replacement in _replacement_paths(Path(data_root), Path(bundle_root)):
        sanitized = sanitized.replace(original, replacement)
        sanitized = sanitized.replace(original.replace("\\", "/"), replacement)
    sanitized = _WINDOWS_USER_PATTERN.sub("<USER_HOME>", sanitized)
    sanitized = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}<REDACTED>", sanitized)
    sanitized = _BEARER_PATTERN.sub(lambda match: f"{match.group(1)}<REDACTED>", sanitized)
    sanitized = _TOKEN_SHAPE_PATTERN.sub("<REDACTED>", sanitized)
    return sanitized


def _tail_text(path: Path, limit: int = _TEXT_TAIL_BYTES) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        payload = stream.read(limit)
    text = payload.decode("utf-8", errors="replace")
    if size > limit:
        text = "[Earlier content omitted]\n" + text
    return text


def _recent_panel_logs(database: Path, limit: int = _PANEL_LOG_LIMIT) -> str:
    if not database.is_file():
        return "No panel log database was found.\n"
    try:
        with closing(sqlite3.connect(str(database), timeout=1)) as connection:
            rows = connection.execute(
                "SELECT ts, run_id, script, message FROM logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        return f"Panel logs could not be read: {type(exc).__name__}: {exc}\n"
    rows.reverse()
    if not rows:
        return "No panel logs have been recorded yet.\n"
    lines = []
    for timestamp, run_id, script, message in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(timestamp)))
        lines.append(f"[{stamp}] [{script}] [{run_id}] {message}")
    return "\n".join(lines) + "\n"


def _debug_logs(debug_dir: Path) -> list[tuple[str, str]]:
    if not debug_dir.is_dir():
        return []
    candidates = [
        path for path in debug_dir.rglob("*")
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".log", ".txt"}
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    output = []
    for index, path in enumerate(candidates[:_DEBUG_FILE_LIMIT], start=1):
        try:
            relative = path.relative_to(debug_dir).as_posix()
            content = f"Source file: {relative}\n\n{_tail_text(path)}"
            output.append((f"debug/{index:02d}.log", content))
        except OSError:
            continue
    return output


def build_diagnostic_bundle(
    *,
    data_root: Path = DATA_ROOT,
    log_dir: Path = LOG_DIR,
    debug_dir: Path = DEBUG_DIR,
    bundle_root: Path = BUNDLE_ROOT,
    version: str = CURRENT_VERSION,
    frozen: bool | None = None,
) -> DiagnosticBundle:
    """Build an in-memory zip without copying configuration, screenshots, or raw databases."""
    data_root = Path(data_root)
    log_dir = Path(log_dir)
    debug_dir = Path(debug_dir)
    bundle_root = Path(bundle_root)
    generated = time.strftime("%Y-%m-%d %H:%M:%S %z")
    filename = f"maamaru-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    packaged = getattr(sys, "frozen", False) if frozen is None else frozen

    files: list[tuple[str, str]] = []
    launcher_log = log_dir / "launcher.log"
    if launcher_log.is_file():
        try:
            files.append(("launcher.log", _tail_text(launcher_log)))
        except OSError as exc:
            files.append(("launcher.log", f"Launcher log could not be read: {exc}\n"))
    else:
        files.append(("launcher.log", "No launcher failure has been recorded.\n"))
    files.append(("recent-panel-logs.txt", _recent_panel_logs(log_dir / "maamaru_logs.db")))
    files.extend(_debug_logs(debug_dir))

    included = "\n".join(f"- {name}" for name, _ in files)
    summary = f"""まあ丸诊断包

Generated: {generated}
Maamaru version: {version}
Run mode: {'packaged installer' if packaged else 'source/development'}
Operating system: {platform.platform()}
Architecture: {platform.machine() or 'unknown'}
Python: {platform.python_version()}

Included files:
{included}

Privacy boundary:
- Includes text-only startup, recent task, and MaaFramework diagnostic logs.
- Does not include configuration, API keys, chat history, screenshots, inventory/state data, or raw databases.
- Local user paths and common credential fields are replaced before export.
"""
    files.insert(0, ("diagnostic-summary.txt", summary))

    replacements = {"data_root": data_root, "bundle_root": bundle_root}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr(name, sanitize_text(content, **replacements).encode("utf-8"))
    return DiagnosticBundle(filename=filename, content=stream.getvalue())


def create_diagnostic_bundle(destination_dir: Path | None = None, **kwargs) -> Path:
    """Write the bundle atomically and return a path suitable for Explorer selection."""
    target_dir = Path(destination_dir or (DATA_ROOT / "diagnostics"))
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_diagnostic_bundle(**kwargs)
    target = target_dir / bundle.filename
    suffix = 2
    while target.exists():
        target = target_dir / bundle.filename.replace(".zip", f"-{suffix}.zip")
        suffix += 1
    with tempfile.NamedTemporaryFile(dir=target_dir, suffix=".tmp", delete=False) as temporary:
        temporary.write(bundle.content)
        temporary_path = Path(temporary.name)
    temporary_path.replace(target)
    return target
