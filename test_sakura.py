# -*- coding: utf-8 -*-
"""刷花入口（1-1 刷疲劳到 100）

用法:
  默认部队5队长:  ./.venv/Scripts/python.exe test_sakura.py
  指定部队/位置:  ./.venv/Scripts/python.exe test_sakura.py --team 5 --slot 1
  只读疲劳不动手: ./.venv/Scripts/python.exe test_sakura.py --check
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from touken import MAAAdapter, ToukenAgent


def _arg(name, default):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


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

team = int(_arg("--team", 5))
slot = int(_arg("--slot", 1))

if "--check" in sys.argv:
    print(f"=== 只读疲劳：部队{team} {slot}号位 ===")
    fatigue = None
    for msg in agent._check_fatigue(team, slot):
        print(msg)
    # yield from 的返回值拿不到，直接再调一次底层（_check_fatigue 是生成器）
    gen = agent._check_fatigue(team, slot)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        fatigue = stop.value
    print(f"疲劳值: {fatigue}")
else:
    print(f"=== 刷花：部队{team} {slot}号位 刷到100 ===")
    for msg in agent.sakura_stream(team_no=team, slot=slot):
        print(msg)
