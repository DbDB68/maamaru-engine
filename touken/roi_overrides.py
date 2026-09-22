# -*- coding: utf-8 -*-
"""代码 ROI 覆盖层：把 roi_registry 里的读取型区域临时改成别的矩形。

覆盖只写用户数据目录 DEBUG_DIR/template_lab/code-rois.json（结构
{id: [x1,y1,x2,y2]}），不碰仓库；删覆盖即恢复注册表默认。读取走
内容缓存，面板改完文件下一次读就生效。

宽容原则：这些全是读取型区域，读岔了顶多 OCR 读空，不能因此把流程
跑崩——所以坏覆盖（格式烂、越界、不是整数）一律静默回落注册表默认；
只有 save_override 这层（面板有前置校验）才对非法矩形亮红牌。
"""

import json
from pathlib import Path

from .roi_registry import ROI_REGISTRY
from .runtime_paths import DEBUG_DIR

_OVERRIDES_PATH = ("template_lab", "code-rois.json")
_FRAME_W, _FRAME_H = 1280, 720

# 文件内容缓存：Windows CI 上连续等长写入可能拿到相同 mtime，
# 不能靠时间戳判定外部修改。path 也进 key，避免测试 patch DEBUG_DIR 后串目录。
_cache: dict = {"path": None, "content": None, "overrides": {}}


def _overrides_file() -> Path:
    return Path(DEBUG_DIR, *_OVERRIDES_PATH)


def _is_valid_rect(rect) -> bool:
    """xyxy 四条 int、0≤x1<x2≤1280、0≤y1<y2≤720 才算合法覆盖。"""
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return False
    if any(isinstance(v, bool) or not isinstance(v, int) for v in rect):
        return False
    x1, y1, x2, y2 = rect
    return 0 <= x1 < x2 <= _FRAME_W and 0 <= y1 < y2 <= _FRAME_H


def _load_overrides() -> dict:
    """读覆盖文件（内容缓存）：只收合法条目，读不出来一律空表。"""
    path = _overrides_file()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        content = None
    if _cache["path"] == str(path) and _cache["content"] == content:
        return _cache["overrides"]
    overrides = {}
    try:
        data = json.loads(content) if content is not None else None
    except ValueError:
        data = None
    if isinstance(data, dict):
        for roi_id, rect in data.items():
            if isinstance(roi_id, str) and _is_valid_rect(rect):
                overrides[roi_id] = (int(rect[0]), int(rect[1]),
                                     int(rect[2]), int(rect[3]))
    _cache["path"] = str(path)
    _cache["content"] = content
    _cache["overrides"] = overrides
    return overrides


def _write_overrides(overrides: dict) -> None:
    path = _overrides_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {roi_id: list(rect) for roi_id, rect in overrides.items()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    _cache["path"] = None  # 废缓存，下次读按新文件重载


def get_roi(roi_id: str, default):
    """取生效矩形（xyxy tuple）：有合法覆盖用覆盖，没有/坏了都回落默认。

    返回类型刻意保持 tuple——现有调用方直接 roi_4to4(*get_roi(...))
    解包，别改成 list。
    """
    rect = _load_overrides().get(roi_id)
    return rect if rect is not None else tuple(default)


def list_overrides() -> dict:
    """当前生效的合法覆盖 {id: (x1,y1,x2,y2)} 副本。"""
    return dict(_load_overrides())


def save_override(roi_id: str, rect) -> None:
    """存/换一条覆盖。id 得是注册表里的（面板层先查 404），矩形必须合法。"""
    if not isinstance(roi_id, str) or not roi_id:
        raise ValueError("ROI id 必须是字符串。")
    if not _is_valid_rect(rect):
        raise ValueError(
            f"矩形必须是 [x1,y1,x2,y2] 四个整数，且 0≤x1<x2≤{_FRAME_W}、"
            f"0≤y1<y2≤{_FRAME_H}。")
    overrides = dict(_load_overrides())
    overrides[roi_id] = tuple(int(v) for v in rect)
    _write_overrides(overrides)


def delete_override(roi_id: str) -> bool:
    """删一条覆盖（恢复默认）。没有这条也算完事，返回有没有真删。"""
    overrides = dict(_load_overrides())
    if roi_id not in overrides:
        return False
    del overrides[roi_id]
    _write_overrides(overrides)
    return True


def effective_rois() -> list[dict]:
    """注册表 × 覆盖合并成 API 直出列表（xyxy，default/override/effective
    都是 list——这层管序列化，tuple 约定只管 get_roi）。"""
    overrides = _load_overrides()
    out = []
    for entry in ROI_REGISTRY:
        roi_id = entry["id"]
        default = tuple(entry["default"])
        override = overrides.get(roi_id)
        out.append({
            "id": roi_id,
            "label": entry["label"],
            "used_in": entry["used_in"],
            "purpose": entry["purpose"],
            "default": list(default),
            "override": list(override) if override is not None else None,
            "effective": list(override) if override is not None else list(default),
            "overridden": override is not None,
        })
    return out
