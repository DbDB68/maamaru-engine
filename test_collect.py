# -*- coding: utf-8 -*-
"""远征收菜实测入口：回一次本丸，把回来的远征奖励都领掉"""
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

print("=== 远征收菜试跑 ===")
# 参数：无=只收不派  same=派回原图  小判/加速符等=按资源目标派
mode = sys.argv[1] if len(sys.argv) > 1 else None
for msg in agent.collect_expedition_stream(redispatch=mode):
    print(msg)

print("=== 结束 ===")
