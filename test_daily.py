# -*- coding: utf-8 -*-
"""一键日课入口

用法:
  全流程: ./.venv/Scripts/python.exe test_daily.py
  只签到: ./.venv/Scripts/python.exe test_daily.py --signin
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from touken import MAAAdapter, ToukenAgent

maa = MAAAdapter(
    adb_path=r"D:\MUMU\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    adb_address="127.0.0.1:16384",
    resource_dir=str(Path(__file__).parent / "resource" / "base"),
    project_root=str(Path(__file__).parent),
    manager_path=r"D:\MUMU\MuMuPlayer\nx_main\MuMuManager.exe",
    emulator_instance=0,
)

if not maa.init():
    print("MAA 初始化失败")
    exit(1)

agent = ToukenAgent(str(Path(__file__).parent / "touken_config.json"), maa)

if "--signin" in sys.argv:
    print("=== 只跑签到 ===")
    for msg in agent.signin_stream():
        print(msg)
else:
    print("=== 一键日课 ===")
    for msg in agent.daily_stream(logout="--logout" in sys.argv):
        print(msg)
