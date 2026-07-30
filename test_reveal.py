# -*- coding: utf-8 -*-
"""剪影识别前期侦察：打一场翻几格，截图看剪影长啥样"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from touken import MAAAdapter, ToukenAgent

maa = MAAAdapter(
    adb_path=r"D:\MUMU\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    adb_address="127.0.0.1:16384",
    resource_dir=str(Path(__file__).parent / "resource" / "base"),
    project_root=str(Path(__file__).parent)
)

if not maa.init():
    print("MAA 初始化失败")
    exit(1)

agent = ToukenAgent(str(Path(__file__).parent / "touken_config.json"), maa)

print("=== 侦察：打到九宫格全翻完就停（不点剪影更新） ===")
stopped = False
for msg in agent.pumpkin_stream(max_rounds=1, team_no=3, difficulty=None):
    print(msg)
    if "九宫格翻完了" in msg or "剪影更新没生效" in msg:
        stopped = True
        break

print("=== 全翻完，停住了 ===" if stopped else "=== 跑完了 ===")
