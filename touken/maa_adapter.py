# -*- coding: utf-8 -*-
"""
底层：MAA 适配器
只管跟模拟器/maa 模块打交道：截图、点击、OCR、模板匹配。
不知道什么是刀剑乱舞，不知道什么是联队战。
（从 touken_agent_engine_v2.py 原样搬家，逻辑未改）
"""

import time  # noqa: F401  # 保留原文件的模块级导入，防止外部有人 from 这里拿
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum

# MaaFramework 导入
try:
    from maa.controller import AdbController
    from maa.pipeline import JOCR, JRecognitionType, JTemplateMatch
    from maa.resource import Resource
    from maa.tasker import Tasker
    MAAFW_AVAILABLE = True
except ImportError:
    MAAFW_AVAILABLE = False
    print("[警告] maa 模块未安装，MAAAdapter 将无法使用")


class RecognizeType(Enum):
    """识别方式"""
    OCR = "OCR"
    TEMPLATE_MATCH = "TemplateMatch"


class ActionType(Enum):
    """操作类型"""
    CLICK = "Click"
    DO_NOTHING = "DoNothing"
    STOP = "Stop"
    SHELL = "Shell"


@dataclass
class Point:
    """坐标点"""
    x: int
    y: int

    def to_list(self) -> list:
        return [self.x, self.y]

    def to_tuple(self) -> tuple:
        return (self.x, self.y)


@dataclass
class Region:
    """ROI 区域: (x, y, w, h) —— MaaFW 用的格式"""
    x: int
    y: int
    w: int
    h: int

    def to_list(self) -> list:
        return [self.x, self.y, self.w, self.h]

    def to_tuple(self) -> tuple:
        return (self.x, self.y, self.w, self.h)

    @property
    def center(self) -> Point:
        return Point(self.x + self.w // 2, self.y + self.h // 2)

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h


def roi_4to4(x1: int, y1: int, x2: int, y2: int) -> Region:
    """把 [x1, y1, x2, y2] 转成 MaaFW 的 (x, y, w, h)"""
    return Region(x1, y1, x2 - x1, y2 - y1)


class MAAAdapter:
    """
    MaaFramework 适配器
    封装所有对 maa 模块的调用
    """

    def __init__(self, adb_path: str, adb_address: str, resource_dir: str,
                 project_root: Optional[str] = None,
                 manager_path: Optional[str] = None,
                 emulator_instance: int = 0):
        """
        初始化 MAA 适配器

        Args:
            adb_path: ADB 可执行文件路径
            adb_address: ADB 设备地址，如 "127.0.0.1:16384"
            resource_dir: 资源包目录路径（如 "resource/base"）
            project_root: 项目根目录（用于设置日志目录）
            manager_path: MuMuManager.exe 路径（给了就支持模拟器自启动）
            emulator_instance: MuMu 实例编号
        """
        if not MAAFW_AVAILABLE:
            raise RuntimeError("maa 模块未安装，请先执行 `uv sync`")

        self.adb_path = adb_path
        self.adb_address = adb_address
        self.resource_dir = resource_dir
        self.project_root = project_root or "."
        self.manager_path = manager_path
        self.emulator_instance = emulator_instance

        self.resource: Optional[Resource] = None
        self.controller: Optional[AdbController] = None
        self.tasker: Optional[Tasker] = None
        self._last_image: Optional[Any] = None  # 缓存上次截图

        self._initialized = False

    def init(self) -> bool:
        """初始化资源、连接 ADB、绑定 Tasker"""
        if self._initialized:
            return True

        # 1. 设置日志目录
        log_dir = Path(self.project_root) / "debug"
        log_dir.mkdir(parents=True, exist_ok=True)
        Tasker.set_log_dir(str(log_dir))

        # 2. 加载资源
        print(f"[MAA] 加载资源: {self.resource_dir}")
        self.resource = Resource()
        job = self.resource.post_bundle(self.resource_dir).wait()
        if not job.succeeded:
            print("[MAA 错误] 资源加载失败，请检查资源目录是否完整")
            return False
        print("[MAA] 资源加载成功")

        # 3. 连接 ADB
        print(f"[MAA] 连接 ADB: {self.adb_address}")
        if not Path(self.adb_path).exists():
            print(f"[MAA 错误] 找不到 adb: {self.adb_path}")
            return False

        self.controller = AdbController(adb_path=self.adb_path, address=self.adb_address)
        if not self.controller.post_connection().wait().succeeded:
            # 连不上就试试把模拟器拉起来再连一次（配了 MuMuManager 才会）
            if self.manager_path:
                from .emulator import ensure_emulator
                if ensure_emulator(self.adb_path, self.adb_address,
                                   manager_path=self.manager_path,
                                   instance=self.emulator_instance):
                    self.controller = AdbController(
                        adb_path=self.adb_path, address=self.adb_address)
                    if self.controller.post_connection().wait().succeeded:
                        print("[MAA] ADB 连接成功（模拟器自启动）")
                        return self._bind_tasker()
            print("[MAA 错误] ADB 连接失败，请确认模拟器已启动")
            return False
        print("[MAA] ADB 连接成功")

        return self._bind_tasker()

    def _bind_tasker(self) -> bool:
        """绑定 Tasker（init 的收尾，自启动重连也走这）"""
        self.tasker = Tasker()
        if not self.tasker.bind(self.resource, self.controller) or not self.tasker.inited:
            print("[MAA 错误] Tasker 绑定失败")
            return False

        self._initialized = True
        print("[MAA] 初始化完成")
        return True

    def screenshot(self, force: bool = False) -> Optional[Any]:
        """
        截图并返回图像对象

        Args:
            force: 是否强制重新截图（否则用缓存）

        Returns:
            numpy 数组（BGR 格式）或 None
        """
        if not self._initialized:
            print("[MAA 错误] 未初始化，请先调用 init()")
            return None

        if not force and self._last_image is not None:
            return self._last_image

        try:
            image = self.controller.post_screencap().wait().get()
            if image is None or image.size == 0:
                print("[MAA 错误] 截图失败")
                return None
            self._last_image = image
            return image
        except Exception as exc:
            print(f"[MAA 错误] 截图异常: {exc}")
            return None

    def save_screenshot(self, path: str, force: bool = True) -> bool:
        """截图存盘（调试用）。BGR numpy → RGB → PNG"""
        image = self.screenshot(force=force)
        if image is None:
            return False
        try:
            from PIL import Image as _PILImage
            _PILImage.fromarray(image[:, :, ::-1]).save(path)
            print(f"[MAA] 截图已存: {path}")
            return True
        except Exception as exc:
            print(f"[MAA 错误] 截图存盘异常: {exc}")
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> bool:
        """滑动（用于列表翻页）"""
        if not self._initialized:
            print("[MAA 错误] 未初始化")
            return False
        try:
            result = self.controller.post_swipe(x1, y1, x2, y2, duration_ms).wait().succeeded
            print(f"[MAA] 滑动 ({x1},{y1}) → ({x2},{y2})")
            return result
        except Exception as exc:
            print(f"[MAA 错误] 滑动异常: {exc}")
            return False

    def click(self, target: Point) -> bool:
        """
        点击坐标

        Args:
            target: 点击位置

        Returns:
            是否成功
        """
        if not self._initialized:
            print("[MAA 错误] 未初始化")
            return False

        try:
            result = self.controller.post_click(target.x, target.y).wait().succeeded
            if result:
                print(f"[MAA] 点击 ({target.x}, {target.y})")
            else:
                print(f"[MAA 错误] 点击 ({target.x}, {target.y}) 失败")
            return result
        except Exception as exc:
            print(f"[MAA 错误] 点击异常: {exc}")
            return False

    def ocr(self, expected: str, roi: Region,
            match_mode: str = "contains") -> Optional[Point]:
        """
        OCR 识别文字

        Args:
            expected: 期望识别的文字
            roi: 识别区域
            match_mode: 匹配模式
                - "exact": 精确匹配整个文字
                - "contains": 识别结果包含 expected 即可（逐字匹配）

        Returns:
            识别成功返回区域中心坐标，失败返回 None
        """
        image = self.screenshot()
        if image is None:
            return None

        try:
            ocr_job = self.tasker.post_recognition(
                JRecognitionType.OCR,
                JOCR(roi=roi.to_tuple()),
                image,
            ).wait()
            ocr_detail = ocr_job.get()
            ocr_reco = ocr_detail.nodes[0].recognition if ocr_detail and ocr_detail.nodes else None

            if ocr_reco is None or not ocr_reco.hit:
                print(f"[MAA] OCR 未命中: expected=\"{expected}\" in {roi.to_list()}")
                return None

            # 检查所有识别结果，不只是 best_result
            all_results = ocr_reco.all_results if hasattr(ocr_reco, 'all_results') else []
            if ocr_reco.best_result:
                all_results = [ocr_reco.best_result] + [r for r in all_results if r != ocr_reco.best_result]

            # 遍历所有结果，找包含目标文字的
            for result in all_results:
                text = result.text if hasattr(result, 'text') else str(result)
                score = result.score if hasattr(result, 'score') else 0.0

                matched = False
                if match_mode == "exact":
                    matched = (text == expected)
                elif match_mode == "contains":
                    matched = (expected in text) or (text in expected)

                if matched:
                    # 获取位置（兼容对象和列表两种格式）
                    center = roi.center  # 默认用 ROI 中心
                    if hasattr(result, 'box') and result.box:
                        box = result.box
                        # box 可能是对象（有 .x .y .w .h）或列表 [x, y, w, h]
                        if hasattr(box, 'x'):
                            center = Point(box.x + box.w // 2, box.y + box.h // 2)
                        elif isinstance(box, (list, tuple)) and len(box) >= 4:
                            center = Point(box[0] + box[2] // 2, box[1] + box[3] // 2)

                    print(f'[MAA] OCR 命中: "{text}" (目标: "{expected}") '
                          f'at ({center.x}, {center.y}), score={score:.3f}')
                    return center

            # 没有匹配到
            texts = [r.text if hasattr(r, 'text') else str(r) for r in all_results]
            print(f"[MAA] OCR 识别到文字但未匹配: {texts}, expected=\"{expected}\"")
            return None

        except Exception as exc:
            print(f"[MAA 错误] OCR 异常: {exc}")
            return None

    def ocr_all(self, roi: Region) -> list:
        """
        识别区域内所有文字（不筛选，全都要）

        用途：读取界面上的信息文本（第几部队、地图名、刀名），
        拿到文字后由上层自己做解析判断。

        Returns:
            [(文本, 中心点Point), ...]，识别失败返回 []
        """
        image = self.screenshot()
        if image is None:
            return []

        try:
            ocr_job = self.tasker.post_recognition(
                JRecognitionType.OCR,
                JOCR(roi=roi.to_tuple()),
                image,
            ).wait()
            ocr_detail = ocr_job.get()
            ocr_reco = ocr_detail.nodes[0].recognition if ocr_detail and ocr_detail.nodes else None

            if ocr_reco is None or not ocr_reco.hit:
                return []

            all_results = ocr_reco.all_results if hasattr(ocr_reco, 'all_results') else []
            if ocr_reco.best_result:
                all_results = [ocr_reco.best_result] + [r for r in all_results if r != ocr_reco.best_result]

            out = []
            for result in all_results:
                text = result.text if hasattr(result, 'text') else str(result)
                center = roi.center
                if hasattr(result, 'box') and result.box:
                    box = result.box
                    if hasattr(box, 'x'):
                        center = Point(box.x + box.w // 2, box.y + box.h // 2)
                    elif isinstance(box, (list, tuple)) and len(box) >= 4:
                        center = Point(box[0] + box[2] // 2, box[1] + box[3] // 2)
                out.append((text, center))

            print(f"[MAA] OCR 全量识别: {[t for t, _ in out]}")
            return out

        except Exception as exc:
            print(f"[MAA 错误] OCR 全量识别异常: {exc}")
            return []

    def template_match(self, template: str, roi: Optional[Region] = None,
                       threshold: float = 0.7) -> Optional[Point]:
        """
        模板匹配

        Args:
            template: 模板图片名（相对 resource/base/image 目录）
            roi: 搜索区域，None 表示全屏
            threshold: 匹配阈值

        Returns:
            匹配成功返回中心坐标，失败返回 None
        """
        image = self.screenshot()
        if image is None:
            return None

        roi_tuple = roi.to_tuple() if roi else (0, 0, 0, 0)

        try:
            tm_job = self.tasker.post_recognition(
                JRecognitionType.TemplateMatch,
                JTemplateMatch(
                    template=[template],
                    roi=roi_tuple,
                    threshold=[threshold]
                ),
                image,
            ).wait()
            tm_detail = tm_job.get()
            tm_reco = tm_detail.nodes[0].recognition if tm_detail and tm_detail.nodes else None

            if tm_reco is None or not tm_reco.hit or tm_reco.box is None:
                print(f"[MAA] 模板未命中: {template} in {roi.to_list() if roi else 'full'}, threshold={threshold}")
                return None

            box = tm_reco.box
            center = Point(box.x + box.w // 2, box.y + box.h // 2)
            score = tm_reco.best_result.score if tm_reco.best_result else 0.0
            print(f"[MAA] 模板命中: {template} at ({center.x}, {center.y}), score={score:.3f}")
            return center

        except Exception as exc:
            print(f"[MAA 错误] 模板匹配异常: {exc}")
            return None

    def exists(self, template: str, roi: Optional[Region] = None,
               threshold: float = 0.7) -> bool:
        """判断模板是否存在"""
        result = self.template_match(template, roi, threshold)
        return result is not None
