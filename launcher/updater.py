"""Download release installers into the user data area without installing them."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from touken.runtime_paths import UPDATES_DIR


REPOSITORY = "DbDB68/maamaru-engine"
_SHA256 = re.compile(r"sha256:([0-9a-fA-F]{64})\Z")


class UpdateError(RuntimeError):
    """A release is unsuitable or could not be downloaded safely."""


def select_installer(release: dict) -> dict:
    """Return the signed-by-GitHub metadata for this release's Windows installer."""
    tag = str(release.get("tag_name") or "")
    version = tag.removeprefix("v")
    expected_name = f"maamaru-setup-v{version}.exe"
    for asset in release.get("assets") or []:
        if asset.get("name") != expected_name:
            continue
        digest = str(asset.get("digest") or "")
        url = str(asset.get("browser_download_url") or "")
        size = asset.get("size")
        parsed = urllib.parse.urlparse(url)
        expected_prefix = f"/{REPOSITORY}/releases/download/"
        if not _SHA256.fullmatch(digest):
            raise UpdateError("GitHub 没有提供可核对的安装包指纹")
        if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.startswith(expected_prefix):
            raise UpdateError("安装包下载地址不是まあ丸官方仓库")
        if not isinstance(size, int) or size <= 0:
            raise UpdateError("安装包大小信息无效")
        return {"tag": tag, "version": version, "name": expected_name, "digest": digest, "url": url, "size": size}
    raise UpdateError("这个版本没有找到 Windows 安装包")


def download_installer(asset: dict, updates_dir: Path = UPDATES_DIR, progress=None) -> dict:
    """Download and verify an installer, atomically exposing only a complete file.

    ``progress`` is an optional callback invoked as ``progress(downloaded, total)``
    after each chunk so callers can render a live progress bar."""
    digest_match = _SHA256.fullmatch(str(asset.get("digest") or ""))
    if not digest_match:
        raise UpdateError("安装包指纹无效")
    expected_hash = digest_match.group(1).lower()
    expected_size = int(asset["size"])
    version = str(asset["version"])
    name = Path(str(asset["name"])).name
    if name != asset["name"] or not name.endswith(".exe"):
        raise UpdateError("安装包文件名无效")

    target_dir = Path(updates_dir) / version
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    partial = target.with_suffix(target.suffix + ".part")

    if target.is_file() and target.stat().st_size == expected_size and _file_sha256(target) == expected_hash:
        return {"path": str(target), "size": expected_size, "sha256": expected_hash, "reused": True}

    partial.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(asset["url"], headers={"User-Agent": "MaamaruLauncher/0.1"})
        hasher = hashlib.sha256()
        downloaded = 0
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                downloaded += len(chunk)
                if downloaded > expected_size:
                    raise UpdateError("安装包大小与 GitHub 记录不一致")
                hasher.update(chunk)
                output.write(chunk)
                if progress is not None:
                    progress(downloaded, expected_size)
        if downloaded != expected_size or hasher.hexdigest() != expected_hash:
            raise UpdateError("安装包校验失败，未保留这次下载")
        partial.replace(target)
        _write_metadata(target_dir / "download.json", asset, expected_hash)
        return {"path": str(target), "size": downloaded, "sha256": expected_hash, "reused": False}
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _write_metadata(path: Path, asset: dict, digest: str) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "version": asset["version"],
        "asset": asset["name"],
        "size": asset["size"],
        "sha256": digest,
        "source": asset["url"],
        "verified": True,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
