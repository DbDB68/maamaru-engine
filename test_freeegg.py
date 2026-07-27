from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from touken_agent_engine_v2 import MAAAdapter, ToukenAgent

maa = MAAAdapter(
    adb_path=r"D:\MUMU\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    adb_address="127.0.0.1:16384",
    resource_dir=str(Path(__file__).parent / "resource" / "base"),
    project_root=str(Path(__file__).parent)
)

if not maa.init():
    exit(1)

agent = ToukenAgent(str(Path(__file__).parent / "touken_config.json"), maa)

# 领取暖心礼包
agent.claim_free_gift()