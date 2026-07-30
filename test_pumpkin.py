# -*- coding: utf-8 -*-
"""南瓜大作战实测入口：部队三，1 局（九宫格翻完并更新出新板子）"""
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

print("=== 南瓜大作战试跑：部队三 × 1 局（不切难度，用当前 tab） ===")
for msg in agent.pumpkin_stream(max_rounds=1, team_no=3, difficulty=None):
    print(msg)

print("=== 结束 ===")
