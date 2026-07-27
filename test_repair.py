# -*- coding: utf-8 -*-
"""手入实测入口：默认演习模式（只认人不点按钮）

用法:
  演习: ./.venv/Scripts/python.exe test_repair.py
  真修: ./.venv/Scripts/python.exe test_repair.py --real
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
print(f"=== 手入{'演习扫描' if dry else '真修'} ===")
for msg in agent.repair_stream(dry_run=dry):
    print(msg)

print("=== 结束 ===")
