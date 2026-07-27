# -*- coding: utf-8 -*-
"""
上层业务入口：各玩法流程
每个文件管一件事，名字写清楚就是专用——要加新玩法就在这里新建文件。
"""

from .login import LoginMixin
from .battle import BattleMixin
from .rewards import RewardsMixin
from .raid import RaidMixin
from .naihanka import NaihankaMixin
from .sortie import SortieMixin
from .expedition import ExpeditionMixin
from .repair import RepairMixin
from .practice import PracticeMixin
from .signin import SigninMixin
from .daily import DailyMixin
from .smith import SmithMixin
from .synthesize import SynthesizeMixin
from .sugar import SugarMixin
from .sakura import SakuraMixin
from .logout import LogoutMixin
from .snapshot import SnapshotMixin

__all__ = ["LoginMixin", "BattleMixin", "RewardsMixin", "RaidMixin", "NaihankaMixin", "SortieMixin", "ExpeditionMixin", "RepairMixin", "PracticeMixin", "SigninMixin", "DailyMixin", "SmithMixin", "SynthesizeMixin", "SugarMixin", "SakuraMixin", "LogoutMixin", "SnapshotMixin"]
