# -*- coding: utf-8 -*-
"""合战场实测入口：默认部队三 × 1-1 图 × 1 圈（含重伤保命测试）"""
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

chapter = int(sys.argv[1]) if len(sys.argv) > 1 else 1
map_no = int(sys.argv[2]) if len(sys.argv) > 2 else 1
team_no = int(sys.argv[3]) if len(sys.argv) > 3 else 3

print(f"=== 合战场试跑：{chapter}章-{map_no}图 部队{team_no} × 1 圈 ===")
for msg in agent.sortie_stream(chapter=chapter, map_no=map_no, team_no=team_no, auto_march=True, max_loops=1):
    print(msg)

print("=== 结束 ===")
