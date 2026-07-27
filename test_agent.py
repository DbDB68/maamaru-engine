from pathlib import Path
import sys

# 确保能找到引擎文件
sys.path.insert(0, str(Path(__file__).parent))

from touken_agent_engine_v2 import MAAAdapter, ToukenAgent

# 初始化 MAA
maa = MAAAdapter(
    adb_path=r"D:\MUMU\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    adb_address="127.0.0.1:16384",
    resource_dir=str(Path(__file__).parent / "resource" / "base"),
    project_root=str(Path(__file__).parent)
)

if not maa.init():
    print("MAA 初始化失败")
    exit(1)

# 创建 Agent
agent = ToukenAgent(str(Path(__file__).parent / "touken_config.json"), maa)

# 测试导航
print("=== 测试导航到本丸 ===")
agent.navigate_to("本丸")

print("=== 测试导航到出阵 ===")  
agent.navigate_to("出阵")