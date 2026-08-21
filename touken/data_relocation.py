"""Verified, two-phase relocation of writable user data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable

from .runtime_paths import (
    BUNDLE_ROOT,
    DATA_ROOT,
    DEFAULT_DATA_ROOT,
    clear_previous_data_root,
    registered_previous_data_root,
    set_registered_data_root,
)


RELOCATION_MARKER = ".maamaru-relocation.json"


class DataRelocationError(RuntimeError):
    pass


def suggested_data_root(selected_folder: str | Path) -> Path:
    selected = Path(selected_folder).expanduser().resolve()
    if selected.name.casefold() in {"maamaru", "まあ丸"}:
        return selected
    return selected / "Maamaru"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _file_manifest(root: Path) -> dict[str, tuple[int, str]]:
    manifest: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == RELOCATION_MARKER:
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest[path.relative_to(root).as_posix()] = (path.stat().st_size, digest.hexdigest())
    return manifest


def _validate_roots(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        raise DataRelocationError("新目录与当前用户数据目录相同")
    if target == Path(target.anchor):
        raise DataRelocationError("不能直接把磁盘根目录作为用户数据目录")
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise DataRelocationError("新旧用户数据目录不能互相包含")
    bundle = BUNDLE_ROOT.resolve()
    if target == bundle or target.is_relative_to(bundle):
        raise DataRelocationError("用户数据目录不能放进程序目录")
    if target.exists() and any(target.iterdir()):
        raise DataRelocationError(f"目标目录不是空的：{target}")


def relocate_user_data(
    selected_folder: str | Path,
    *,
    source_root: Path = DATA_ROOT,
    location_writer: Callable[[Path, Path], None] = set_registered_data_root,
) -> dict:
    """Copy and hash-verify data, then switch future packaged launches.

    The source is deliberately retained.  A later launch from the verified target
    may remove it only through ``cleanup_previous_data`` with the matching token.
    """
    if os.environ.get("MAAMARU_DATA_DIR", "").strip():
        raise DataRelocationError("当前目录由 MAAMARU_DATA_DIR 控制，不能在启动器里迁移")
    source = Path(source_root).resolve()
    target = suggested_data_root(selected_folder)
    _validate_roots(source, target)
    if not source.is_dir():
        raise DataRelocationError(f"当前用户数据目录不存在：{source}")
    if pending_relocation_cleanup(data_root=source):
        raise DataRelocationError("请先清理上一次迁移留下的旧副本")

    before = _file_manifest(source)
    total_bytes = sum(size for size, _ in before.values())
    target.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(target.parent).free
    if free_bytes < total_bytes + 16 * 1024 * 1024:
        raise DataRelocationError("目标磁盘空间不足，无法安全复制用户数据")

    token = uuid.uuid4().hex
    staging = target.parent / f".{target.name}.migrating-{token[:8]}"
    if staging.exists():
        raise DataRelocationError(f"迁移暂存目录已存在：{staging}")

    try:
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns(RELOCATION_MARKER))
        copied = _file_manifest(staging)
        after = _file_manifest(source)
        if before != after:
            raise DataRelocationError("复制期间原目录发生变化，已停止切换，请关闭面板后重试")
        if copied != before:
            raise DataRelocationError("复制校验失败，仍保留原目录")
        if target.exists():
            target.rmdir()  # only allowed because validation proved it empty
        staging.replace(target)

        record = {
            "schema": 1,
            "token": token,
            "source": str(source),
            "target": str(target),
            "files": len(before),
            "bytes": total_bytes,
            "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cleaned_at": None,
        }
        _write_json(source / RELOCATION_MARKER, record)
        _write_json(target / RELOCATION_MARKER, record)
        try:
            location_writer(target, source)
        except Exception:
            (source / RELOCATION_MARKER).unlink(missing_ok=True)
            shutil.rmtree(target, ignore_errors=True)
            raise
        return record
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def pending_relocation_cleanup(*, data_root: Path = DATA_ROOT) -> dict | None:
    target = Path(data_root).resolve()
    marker = target / RELOCATION_MARKER
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
        source = Path(record["source"]).resolve()
        if record.get("cleaned_at") or Path(record["target"]).resolve() != target:
            return None
        source_record = json.loads((source / RELOCATION_MARKER).read_text(encoding="utf-8"))
        if source_record.get("token") != record.get("token"):
            return None
        registered = registered_previous_data_root()
        if registered is not None and registered.resolve() != source:
            return None
        return record
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _safe_cleanup_source(source: Path, target: Path) -> bool:
    source = source.resolve()
    target = target.resolve()
    protected = {
        Path(source.anchor),
        Path.home().resolve(),
        DEFAULT_DATA_ROOT.parent.resolve(),
        BUNDLE_ROOT.resolve(),
        BUNDLE_ROOT.resolve().parent,
        target,
    }
    source_contains_protected_path = any(
        protected_path == source or protected_path.is_relative_to(source)
        for protected_path in protected
    )
    return not source_contains_protected_path and not target.is_relative_to(source)


def cleanup_previous_data(
    confirmation_token: str,
    *,
    data_root: Path = DATA_ROOT,
    clear_previous: Callable[[], None] = clear_previous_data_root,
) -> dict:
    """Delete only the verified source copy after an explicit token confirmation."""
    target = Path(data_root).resolve()
    record = pending_relocation_cleanup(data_root=target)
    if not record or record.get("token") != confirmation_token:
        raise DataRelocationError("没有可安全清理的旧数据副本")
    source = Path(record["source"]).resolve()
    if not _safe_cleanup_source(source, target):
        raise DataRelocationError("旧目录安全校验失败，未删除任何内容")

    shutil.rmtree(source)
    record["cleaned_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_json(target / RELOCATION_MARKER, record)
    clear_previous()
    return record
