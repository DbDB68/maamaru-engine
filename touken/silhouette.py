# -*- coding: utf-8 -*-
"""
剪影识别：把刮刮乐板子上的黑色剪影认出是哪把刀

原理：
  - 游戏板子右侧的剪影窗是固定位置，分「头部视角」和「腿部视角」两种板子，
    纯黑剪影 on 白底；全翻完也不一定变彩色（头版一直是黑的）
  - 素材库（群友制作）是 300×300 白底黑影 PNG，分 _head / _foot 两套
  - 匹配用「轮廓对称分」：双方轮廓线在各自 2px 容差带里的覆盖率取平均，
    FFT 互相关做全偏移搜索。填充 F1 对头部大黑团区分度不够，轮廓才分得清发型
  - 实测真身 0.58~0.62，亚军 ≤0.42，阈值按这个间隙定的（见 is_confident）

性能注意：半分辨率（WORK_SCALE=0.5）下单次识别约 5~15 秒（231 个模板 × 5 个比例）。
一局只认一两次，可接受；以后要做预计算再说。
"""

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

# 剪影窗在游戏截图里的位置（1280×720）
# y 从 215 起是为了躲开压在上面的「南瓜Pt」计数条
PANEL = (700, 215, 1020, 460)

# 黑色像素少于这个数就不认（格子翻太少，认了也不准）
MIN_BLACK_PIXELS = 800

# 匹配时搜索的缩放比例（实测游戏剪影 ≈ 素材 ×1.1 左右，但头版没标定过，放宽搜）
DEFAULT_SCALES = (1.0, 1.05, 1.1, 1.15, 1.2)

# 识别时在半分辨率下跑（快 4 倍，轮廓特征经得起缩）
WORK_SCALE = 0.5

# 置信阈值（实测：真身 ≥0.57，亚军 ≤0.42，留足安全边）
CONFIDENT_SCORE = 0.50   # 第一名至少要这个分
CONFIDENT_MARGIN = 0.08  # 且领先第二名至少这么多


def load_library(lib_dir):
    """
    加载素材库 → [(名字, view, 300×300 bool mask)]，黑影=True
    文件名格式：00047_五虎退_foot.png / 00107_小竜景光_head.png
    """
    lib = []
    for f in sorted(Path(lib_dir).glob("*.png")):
        parts = f.stem.split("_")
        if len(parts) < 3 or parts[2] not in ("head", "foot"):
            continue
        name, view = parts[1], parts[2]
        mask = np.array(Image.open(f).convert("L")) < 127
        lib.append((name, view, mask))
    return lib


def largest_component(mask):
    """只保留最大连通域，清掉弹窗文字之类的小碎块污染"""
    visited = np.zeros(mask.shape, bool)
    H, W = mask.shape
    best_comp, best_size = None, 0
    for sy in range(0, H, 2):
        for sx in range(0, W, 2):
            if mask[sy, sx] and not visited[sy, sx]:
                comp = []
                q = deque([(sy, sx)])
                visited[sy, sx] = True
                while q:
                    y, x = q.popleft()
                    comp.append((y, x))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            q.append((ny, nx))
                if len(comp) > best_size:
                    best_size, best_comp = len(comp), comp
    out = np.zeros(mask.shape, bool)
    if best_comp:
        for y, x in best_comp:
            out[y, x] = True
    return out


def extract_observed(img_bgr):
    """
    从游戏截图（BGR numpy）抠剪影窗的黑色剪影 mask。
    纯黑剪影 on 白底，亮度阈值 + 外圈 3px 清零 + 最大连通域净化。
    """
    x0, y0, x1, y1 = PANEL
    crop = img_bgr[y0:y1, x0:x1].astype(np.float32)
    lum = crop.mean(axis=2)
    obs = lum < 60
    obs[:3, :] = False
    obs[-3:, :] = False
    obs[:, :3] = False
    obs[:, -3:] = False
    return largest_component(obs)


def _edge(mask):
    """轮廓 = mask 减去四向腐蚀后的自己"""
    m = mask
    eroded = m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]
    e = np.zeros_like(m)
    e[1:-1, 1:-1] = m[1:-1, 1:-1] & ~eroded
    return e


def _dilate(mask, r=2):
    """近似膨胀 r 次（4 方向）"""
    out = mask.copy()
    for _ in range(r):
        m = out
        out = m.copy()
        out[1:, :] |= m[:-1, :]
        out[:-1, :] |= m[1:, :]
        out[:, 1:] |= m[:, :-1]
        out[:, :-1] |= m[:, 1:]
    return out


def _resize_mask(mask, n):
    im = Image.fromarray((mask * 255).astype(np.uint8)).resize((n, n), Image.BILINEAR)
    return np.array(im) > 127


def _downscale(mask, scale):
    """等比缩小 mask（PIL 双线性 + 阈值回二值）"""
    h, w = mask.shape
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    im = Image.fromarray((mask * 255).astype(np.uint8)).resize((nw, nh), Image.BILINEAR)
    return np.array(im) > 127


def identify(obs, lib, scales=DEFAULT_SCALES, top_n=5):
    """
    认剪影。

    Returns:
        None = 黑色像素太少，拒答
        [(score, name, view), ...] 按轮廓对称分降序
    """
    if obs.sum() < MIN_BLACK_PIXELS:
        return None

    # 半分辨率跑：FFT 计算量 ~1/16，轮廓特征经得起缩
    if WORK_SCALE != 1.0:
        obs = _downscale(obs, WORK_SCALE)

    O = obs.astype(np.float32)
    eO = _edge(obs)
    eO_sum = float(eO.sum())
    if eO_sum == 0:
        return None
    d_eO = _dilate(eO, 2).astype(np.float32)
    H, W = O.shape
    pad = int(round(400 * WORK_SCALE))
    fh, fw = H + pad, W + pad

    FO1 = np.fft.rfft2(d_eO, (fh, fw))
    FO2 = np.fft.rfft2(eO.astype(np.float32), (fh, fw))

    results = []
    for name, view, tmask in lib:
        best = 0.0
        for s in scales:
            nw = int(round(300 * s * WORK_SCALE))
            T = _resize_mask(tmask, nw)
            eT = _edge(T)
            eT_sum = float(eT.sum())
            if eT_sum == 0:
                continue
            # eT 落进 eO 容差带的比例
            c1 = np.fft.irfft2(FO1 * np.fft.rfft2(eT[::-1, ::-1].astype(np.float32), (fh, fw)), (fh, fw)).max() / eT_sum
            # eO 落进 eT 容差带的比例
            d_eT = _dilate(eT, 2).astype(np.float32)
            c2 = np.fft.irfft2(FO2 * np.fft.rfft2(d_eT[::-1, ::-1], (fh, fw)), (fh, fw)).max() / eO_sum
            best = max(best, (float(c1) + float(c2)) / 2)
        results.append((best, name, view))

    results.sort(reverse=True)
    return results[:top_n]


def is_confident(results):
    """识别结果可不可信（第一名高且甩开第二名）"""
    if not results or len(results) < 2:
        return False
    top1, top2 = results[0], results[1]
    return top1[0] >= CONFIDENT_SCORE and (top1[0] - top2[0]) >= CONFIDENT_MARGIN
