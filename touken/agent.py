# -*- coding: utf-8 -*-
"""
ToukenAgent 主引擎 = 各层能力的组装
真正的实现分散在：
  - maa_adapter.py   底层：截图/点击/OCR/模板匹配
  - navigator.py     中层：通用识别 + 导航 + 弹窗
  - flows/           上层：登录、出战、领取等各业务
"""

import json
import time
from pathlib import Path

from .maa_adapter import MAAAdapter
from .navigator import NavigationMixin
from .runtime_paths import STATUS_DIR
from .flows import LoginMixin, BattleMixin, RewardsMixin, RaidMixin, PumpkinMixin, NaihankaMixin, SortieMixin, ExpeditionMixin, RepairMixin, PracticeMixin, SigninMixin, DailyMixin, SmithMixin, SynthesizeMixin, SugarMixin, SakuraMixin, LogoutMixin, SnapshotMixin, OsakaMixin


class ToukenAgent(LoginMixin, NavigationMixin, BattleMixin, RewardsMixin, RaidMixin, PumpkinMixin, NaihankaMixin, SortieMixin, ExpeditionMixin, RepairMixin, PracticeMixin, SigninMixin, DailyMixin, SmithMixin, SynthesizeMixin, SugarMixin, SakuraMixin, LogoutMixin, SnapshotMixin, OsakaMixin):
    """
    刀剑乱舞 Agent 主引擎
    所有操作基于配置文件，不硬编码任何游戏特定内容
    """

    def __init__(self, config_path: str, maa: MAAAdapter):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        self.maa = maa
        self.current_location = None
        self._root = Path(config_path).resolve().parent
        self._progress_file = STATUS_DIR / "progress.json"

    def set_progress(self, step: str):
        """上报当前进度给面板仪表盘横幅（如 'raid:lulian'、'daily:内番'）。

        写失败绝不许影响干活，所以全部异常吞掉。
        """
        try:
            self._progress_file.parent.mkdir(parents=True, exist_ok=True)
            self._progress_file.write_text(json.dumps({
                "step": step,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
