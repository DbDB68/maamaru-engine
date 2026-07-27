# -*- coding: utf-8 -*-
"""联队战断点续跑：直接进入战斗循环（当前画面停在行动选择/战斗中时用）"""
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

print("=== 续跑战斗循环 ===")
for msg in agent.battle_loop_stream():
    print(msg)

done, battles = agent._battle_loop_result
print(f"=== 结束：round_done={done}, battles={battles} ===")
