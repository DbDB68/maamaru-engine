# -*- coding: utf-8 -*-
"""
南瓜大作战【智能版】实测入口：认剪影，不是目标刀就烧令牌换板子

用法：python test_pumpkin_smart.py [目标刀,逗号分隔] [本窗口最多打几场]
  默认目标「小竜景光」、最多打 2 场（Bash 窗口 300 秒限制，分多窗跑，
  游戏状态在模拟器里持续，重跑本脚本会接着刷）

测试 hack：identify_min_battles 调成 0，每场回来都认一次——
反正黑像素不够时 identify 会拒答，正式跑还是用配置里的 4。
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from touken import MAAAdapter, ToukenAgent

watch = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] else ["小竜景光"]
cap = int(sys.argv[2]) if len(sys.argv) > 2 else 2

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
agent.config["pumpkin"]["identify_min_battles"] = 0  # 测试：立刻开始认

print(f"=== 冷启动检查 ===")
for msg in agent._ensure_game_started():
    print(msg)

print(f"=== 登录 ===")
agent.login()

print(f"=== 弹窗扫地 ===")
if agent._popup_sweep():
    print("落地本丸 ✓")
else:
    print("扫地没扫干净，硬跑试试")

print(f"=== 南瓜智能版试跑：目标 {watch}，本窗口最多 {cap} 场，令牌上限 2 ===")
battles = 0
for msg in agent.pumpkin_stream(max_rounds=1, team_no=3, difficulty=None,
                                watch_names=watch, max_skips=2):
    print(msg, flush=True)
    if "出阵回来" in msg:
        battles += 1
        if battles >= cap:
            print(f"=== 本窗口打够 {cap} 场，停（游戏还在模拟器里，重跑继续） ===")
            break

print("=== 结束 ===")
