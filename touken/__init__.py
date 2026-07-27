# -*- coding: utf-8 -*-
"""
刀剑乱舞 MAA Agent 引擎（分层版）

三层结构：
  maa_adapter.py  底层：只管设备和识别，不知道什么是刀剑乱舞
  navigator.py    中层：通用导航机械，不知道什么是联队战
  flows/          上层：每个业务一个文件，专用就写明专用
"""

from .maa_adapter import (
    MAAFW_AVAILABLE,
    MAAAdapter,
    ActionType,
    Point,
    RecognizeType,
    Region,
    roi_4to4,
)
from .agent import ToukenAgent

__all__ = [
    "MAAFW_AVAILABLE",
    "MAAAdapter",
    "ToukenAgent",
    "ActionType",
    "Point",
    "RecognizeType",
    "Region",
    "roi_4to4",
]
