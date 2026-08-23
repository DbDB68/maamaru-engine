# -*- coding: utf-8 -*-
"""
刀剑名册：OCR 认人的"字典"

用途：修复/演练等界面 OCR 出刀名 → 查表得到标准身份
  （编号、刀种、刀派、稀有度），顺便校正 OCR 错字。

数据来源：vendor_review/generate_touken_data.py（外包生成，2026-07-26）
存放位置：touken/data/swords.json

注意：
  - 游戏界面显示的是日文名（name 字段），OCR 匹配优先用日文
  - 数据未区分"极化"——极化标记按约定另外用模板/OCR 单独识别
  - 个别刀派字段为空、罗马音有拼写小瑕疵，不影响认人；发现错漏改 swords.json 即可
"""

import difflib
import json
import unicodedata
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).parent / "data" / "swords.json"

_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is None:
        with open(_DATA_PATH, encoding="utf-8") as f:
            _cache = json.load(f)["chars"]
    return _cache


def _normalize(text: str) -> str:
    """OCR 文本清洗：去空白、全角半角统一"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return "".join(text.split())


def all_swords() -> dict:
    """全部刀剑 {id: info}"""
    return _load()


def find_by_name(ocr_text: str, fuzzy: bool = True) -> Optional[tuple]:
    """
    用 OCR 出的文字查刀

    匹配顺序：
      1. 日文名精确等于
      2. 互相包含（OCR 多读/少读了字，如"长谷部"对"へし切長谷部"）
      3. 中文名兜底

    fuzzy=False 时跳过第 4 步模糊兜底——锻刀获得画面认人这类
    「认错比认不到更糟」的场景用严格模式。

    Returns:
        (id, info) 或 None
    """
    target = _normalize(ocr_text)
    if not target:
        return None

    chars = _load()

    # 1. 日文精确
    for sid, info in chars.items():
        if _normalize(info["name"]) == target:
            return sid, info

    # 2. 互相包含（要求目标至少 2 个字，避免单字乱撞）
    if len(target) >= 2:
        for sid, info in chars.items():
            name = _normalize(info["name"])
            if target in name or (len(name) >= 2 and name in target):
                return sid, info

    # 3. 中文名兜底
    for sid, info in chars.items():
        if _normalize(info.get("name_zh", "")) == target:
            return sid, info

    # 4. 模糊兜底（OCR 错一个字的情况，如"源清磨"对"源清麿"）
    #    只在相似度够高且目标不短时用，避免乱撞
    if fuzzy and len(target) >= 2:
        best = (0.0, None)
        for sid, info in chars.items():
            for cand in (info["name"], info.get("name_zh", "")):
                cand = _normalize(cand)
                if not cand:
                    continue
                score = difflib.SequenceMatcher(None, target, cand).ratio()
                if score > best[0]:
                    best = (score, (sid, info))
        if best[0] >= 0.6:
            return best[1]

    return None


def display_name(ocr_text: str) -> str:
    """OCR 名字校正成标准中文名，日志展示用（"夜左文字"→"小夜左文字"）。
    认不出返回清洗后的原文——校正只影响给人看的文字，不影响任何动作。"""
    found = find_by_name(ocr_text)
    if found:
        return found[1].get("name_zh") or found[1]["name"]
    return _normalize(ocr_text) or str(ocr_text or "")


def find_by_id(id_num: int) -> Optional[tuple]:
    """按图鉴编号查（如 118 → 长谷部）"""
    prefix = f"touken_{id_num:03d}_"
    for sid, info in _load().items():
        if sid.startswith(prefix):
            return sid, info
    return None
