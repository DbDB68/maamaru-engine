# -*- coding: utf-8 -*-
"""
执务页常用功能自定义布局 —— 现有功能可隐藏/排序，工作流预设可钉进来一键跑

- 布局存用户数据目录 STATUS_DIR/home_layout.json，不进程序目录/发布包；
  新文件，老安装没有它也照跑（回落默认清单）。
- order 里脚本用注册名、工作流预设用 "wf:<预设id>"；hidden 同理。
- 解析规则：order 顺序在前 → 追加「既不在 order 也不在 hidden」的合法脚本
  （新版本新功能自动冒到末尾，不会被误藏）；悬空 wf:（预设被删）和
  不认识的 key 解析时静默丢弃，不崩。
- 坏文件备份 .bad-时间戳 后回落默认，绝不让面板崩（workflow.py 同款约定）。

依赖方向：本模块 import workflow / script_runner，**不许 import panel.server**
（server 接线路由时会反过来 import 本模块，循环依赖）。
"""

import json
import os
import shutil
import time
from pathlib import Path

from touken.runtime_paths import STATUS_DIR

from . import workflow
from .script_runner import _SCRIPTS

# 默认清单 = 旧版前端 App.vue 硬编码 homeScriptOrder，后端自持一份。
# 注意只管照抄，不保证每个 key 都注册了（比如 smith）——
# 解析时不认识的 key 静默丢弃。
DEFAULT_ORDER = ["daily", "sortie", "yosari", "osaka", "edocastle",
                 "expedition", "smith", "pumpkin", "raid", "sugar",
                 "sakura", "practice", "snapshot"]


class HomeLayoutError(ValueError):
    """布局校验失败（API 层转成 400）。"""


def _layout_path() -> Path:
    return STATUS_DIR / "home_layout.json"


def _default_layout() -> dict:
    return {"order": list(DEFAULT_ORDER), "hidden": []}


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _unify_daily(order, hidden):
    """默认日课的两种入口共用 daily；只投影，读取不改原文件。"""
    alias = f"wf:{workflow.DAILY_PRESET_ID}"
    if alias not in order and alias not in hidden:
        return {"order": order, "hidden": hidden}
    # 曾收起旧入口、再钉上默认流程的用户，仍然保留可见的日课。
    visible = any(key in order and key not in hidden for key in ("daily", alias))
    mapped_order = list(dict.fromkeys("daily" if key == alias else key for key in order))
    mapped_hidden = list(dict.fromkeys("daily" if key == alias else key for key in hidden))
    if visible:
        mapped_hidden = [key for key in mapped_hidden if key != "daily"]
    return {"order": mapped_order, "hidden": mapped_hidden}


# ── 存取（STATUS_DIR/home_layout.json）──

def load_layout() -> dict:
    """读布局；坏文件备份后回落默认，绝不让面板崩。"""
    path = _layout_path()
    if not path.exists():
        return _default_layout()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        try:
            bad = path.with_name(path.name + ".bad-"
                                 + time.strftime("%Y%m%d-%H%M%S"))
            path.replace(bad)
        except OSError:
            pass
        return _default_layout()
    if not isinstance(data, dict):
        return _default_layout()
    order = data.get("order")
    hidden = data.get("hidden")
    if not _is_str_list(order) or not _is_str_list(hidden):
        return _default_layout()
    # 去重；手改文件造成的 order∩hidden 交集以 hidden 为准（resolve 时过滤）
    return _unify_daily(list(dict.fromkeys(order)), list(dict.fromkeys(hidden)))


def save_layout(layout: dict):
    path = _layout_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 保存前保留旧结构，替换失败时原文件仍在（workflow.save_presets 同款）
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"order": layout["order"],
                                "hidden": layout["hidden"]},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8")
    os.replace(temp, path)


def normalize_layout(body) -> dict:
    """校验并规范化 {order, hidden}；非法输入抛 HomeLayoutError。

    只校验形状（字符串列表、去重、两集不相交），不认识的 key 照单全收——
    悬空项在 resolve 时静默丢弃，存文件不拦用户。
    """
    if not isinstance(body, dict):
        raise HomeLayoutError("布局必须是对象")
    order = body.get("order")
    hidden = body.get("hidden")
    if not _is_str_list(order):
        raise HomeLayoutError("order 必须是字符串列表")
    if not _is_str_list(hidden):
        raise HomeLayoutError("hidden 必须是字符串列表")
    order = list(dict.fromkeys(order))
    hidden = list(dict.fromkeys(hidden))
    overlap = set(order) & set(hidden)
    if overlap:
        raise HomeLayoutError(
            "同一项不能既在常用又在收起来: " + "、".join(sorted(overlap)))
    return _unify_daily(order, hidden)


# ── 解析 ──

def resolve_layout() -> list[dict]:
    """解析成有序可见项 [{kind, key, label}]。

    - kind "script"：key = 脚本注册名，label 取注册表显示名；
    - kind "workflow"：key = "wf:<预设id>"，label 取预设名；
    - 悬空 wf:（预设已删）、不认识的 key、被 hidden 的项，全部静默丢弃；
    - order/hidden 都没提到的合法脚本按注册顺序追加末尾。
      未钉的工作流预设**不**自动出现（编辑面板里作为候选单独列出）。
    """
    layout = load_layout()
    order, hidden = layout["order"], layout["hidden"]
    hidden_set = set(hidden)
    script_keys = {k for k, v in _SCRIPTS.items() if not v.get("hidden")}
    preset_names = {p["id"]: p.get("name", "")
                    for p in workflow.load_presets() if p.get("id")}

    entries: list[dict] = []
    seen: set[str] = set()

    def _append(item: str):
        if item in seen:
            return
        if item.startswith("wf:"):
            preset_id = item[3:]
            if item in hidden_set or preset_id not in preset_names:
                return
            entries.append({"kind": "workflow", "key": item,
                            "label": preset_names[preset_id]})
        else:
            if item in hidden_set or item not in script_keys:
                return
            entries.append({"kind": "script", "key": item,
                            "label": _SCRIPTS[item]["label"]})
        seen.add(item)

    for item in order:
        _append(item)
    for key in _SCRIPTS:  # 注册顺序，保证追加顺序稳定
        if key in script_keys and key not in hidden_set:
            _append(key)
    return entries
