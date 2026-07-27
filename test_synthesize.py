# -*- coding: utf-8 -*-
"""合成实测入口

用法:
  演习: ./.venv/Scripts/python.exe test_synthesize.py
  真合: ./.venv/Scripts/python.exe test_synthesize.py --real
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

dry = "--real" not in sys.argv
print("=== 合成%s ===" % ("演习（只报决策）" if dry else "真合"))
for msg in agent.synthesize_stream(dry_run=dry):
    print(msg)
