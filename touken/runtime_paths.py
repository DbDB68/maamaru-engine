"""Runtime paths shared by source mode and the packaged launcher."""

import os
import shutil
from pathlib import Path


BUNDLE_ROOT = Path(__file__).resolve().parent.parent
_data_override = os.environ.get("MAAMARU_DATA_DIR", "").strip()
DATA_ROOT = Path(_data_override).expanduser().resolve() if _data_override else BUNDLE_ROOT
STATUS_DIR = DATA_ROOT / "status"
CONFIG_PATH = DATA_ROOT / "touken_config.json"
PANEL_CONFIG_PATH = DATA_ROOT / "panel_config.json"
SCHEDULE_PATH = DATA_ROOT / "expedition_schedule.json"
PROFILES_DIR = DATA_ROOT / "profiles"
RESOURCE_DIR = BUNDLE_ROOT / "resource" / "base"


def ensure_runtime_data() -> None:
    """Create writable runtime data without overwriting an existing user config."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    defaults = (
        (BUNDLE_ROOT / "touken_config.json", CONFIG_PATH),
        (BUNDLE_ROOT / "panel" / "panel_config.json", PANEL_CONFIG_PATH),
        (BUNDLE_ROOT / "panel" / "panel_config.example.json", PANEL_CONFIG_PATH),
        (BUNDLE_ROOT / "panel" / "expedition_schedule.json", SCHEDULE_PATH),
    )
    claimed = set()
    for source, target in defaults:
        if target in claimed or target.exists() or not source.exists() or source == target:
            continue
        shutil.copy2(source, target)
        claimed.add(target)
    # profiles/：首次运行时把内置素材库展开到数据目录
    # 不覆盖用户已有的（如果用户在群里拿到了更新版，删掉数据目录的再让程序自动展开）
    src_profiles = BUNDLE_ROOT / "profiles"
    if src_profiles.is_dir() and not PROFILES_DIR.exists():
        shutil.copytree(src_profiles, PROFILES_DIR)
