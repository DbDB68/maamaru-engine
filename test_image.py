from maa.controller import AdbController
from maa.pipeline import JRecognitionType, JTemplateMatch
from maa.resource import Resource
from maa.tasker import Tasker
from pathlib import Path
import time

# 初始化（用你的实际路径）
resource = Resource()
resource.post_bundle(str(Path("resource/base"))).wait()

controller = AdbController(adb_path=r"D:\MUMU\MuMuPlayer\nx_device\12.0\shell\adb.exe", address="127.0.0.1:16384")
controller.post_connection().wait()

tasker = Tasker()
tasker.bind(resource, controller)

# 截图
image = controller.post_screencap().wait().get()

# 测试本丸模板
tm_job = tasker.post_recognition(
    JRecognitionType.TemplateMatch,
    JTemplateMatch(template=["ui本丸.png"], roi=(0, 0, 0, 0), threshold=[0.5]),
    image,
).wait()

result = tm_job.get()
if result and result.nodes:
    reco = result.nodes[0].recognition
    print(f"命中: {reco.hit}, score: {reco.best_result.score if reco.best_result else 'N/A'}")
else:
    print("未命中")