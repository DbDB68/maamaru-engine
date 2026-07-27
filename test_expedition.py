# -*- coding: utf-8 -*-
"""远征实测入口：默认 时代1 × 鸟羽·伏见 × 部队二（短时图省钱省时间）

用法: ./.venv/Scripts/python.exe test_expedition.py [时代] [小图名] [部队号]
仅截图校准: ./.venv/Scripts/python.exe test_expedition.py --shot
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

# 仅截图模式：截当前画面存 calibration_shot.png，用于校准坐标
if len(sys.argv) > 1 and sys.argv[1] == "--shot":
    img = maa.screenshot(force=True)
    if img is not None:
        import numpy as np
        from PIL import Image
        Image.fromarray(np.array(img)[:, :, ::-1]).save("calibration_shot.png")
        print("已存 calibration_shot.png")
    else:
        print("截图失败")
    exit(0)

era = int(sys.argv[1]) if len(sys.argv) > 1 else 1
map_name = sys.argv[2] if len(sys.argv) > 2 else "鸟羽"
team_no = int(sys.argv[3]) if len(sys.argv) > 3 else 2

print(f"=== 远征试跑：时代{era}「{map_name}」部队{team_no} ===")
for msg in agent.expedition_stream(era=era, map_name=map_name, team_no=team_no):
    print(msg)

print("=== 结束 ===")
