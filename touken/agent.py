# -*- coding: utf-8 -*-
"""
ToukenAgent 主引擎 = 各层能力的组装
真正的实现分散在：
  - maa_adapter.py   底层：截图/点击/OCR/模板匹配
  - navigator.py     中层：通用识别 + 导航 + 弹窗
  - flows/           上层：登录、出战、领取等各业务
"""

import json

from .maa_adapter import MAAAdapter
from .navigator import NavigationMixin
from .flows import LoginMixin, BattleMixin, RewardsMixin, RaidMixin, NaihankaMixin, SortieMixin, ExpeditionMixin, RepairMixin, PracticeMixin, SigninMixin, DailyMixin, SmithMixin, SynthesizeMixin, SugarMixin, SakuraMixin, LogoutMixin, SnapshotMixin


class ToukenAgent(LoginMixin, NavigationMixin, BattleMixin, RewardsMixin, RaidMixin, NaihankaMixin, SortieMixin, ExpeditionMixin, RepairMixin, PracticeMixin, SigninMixin, DailyMixin, SmithMixin, SynthesizeMixin, SugarMixin, SakuraMixin, LogoutMixin, SnapshotMixin):
    """
    刀剑乱舞 Agent 主引擎
    所有操作基于配置文件，不硬编码任何游戏特定内容
    """

    def __init__(self, config_path: str, maa: MAAAdapter):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        self.maa = maa
        self.current_location = None
