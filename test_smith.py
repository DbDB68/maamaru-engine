# -*- coding: utf-8 -*-
"""锻刀/刀解实测入口

用法:
  锻刀3炉: ./.venv/Scripts/python.exe test_smith.py
  刀解演习: ./.venv/Scripts/python.exe test_smith.py --dismantle
"""
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

if "--dismantle" in sys.argv:
    print("=== 刀解演习（只报决策） ===")
    for msg in agent.dismantle_stream(max_dismantle=1, dry_run=True):
        print(msg)
else:
    print("=== 锻刀 ===")
    for msg in agent.forge_stream(times=3):
        print(msg)
