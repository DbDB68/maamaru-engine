# -*- coding: utf-8 -*-
"""剪影匹配实验：把全揭面板的下半身跟素材库 foot 图对比，验证算法可行性"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
LIB = ROOT / "Silhouette1.0.2 (2)" / "silhouette"

# ---------- 1. 抠出面板里的立绘 mask ----------
# 面板区域（1280×720 下）：右侧面板内部，避开左侧绿箭头和边框
panel = Image.open(ROOT / "board_full.png").convert("RGB").crop((725, 185, 1015, 455))
arr = np.array(panel)

# 从四角洪泛填充背景（白色容差），剩下的就是立绘
flood = panel.copy()
for seed in [(0, 0), (panel.width - 1, 0), (0, panel.height - 1), (panel.width - 1, panel.height - 1)]:
    ImageDraw.floodfill(flood, seed, (255, 0, 255), thresh=40)
farr = np.array(flood)
bg = (farr[:, :, 0] == 255) & (farr[:, :, 1] == 0) & (farr[:, :, 2] == 255)
figure = ~bg  # 立绘 mask

ys, xs = np.where(figure)
print(f"立绘像素数: {figure.sum()}, bbox: x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}")


def bbox_crop(mask):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return mask
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def resize_mask(mask, h, w):
    im = Image.fromarray((mask * 255).astype(np.uint8))
    return np.array(im.resize((w, h), Image.BILINEAR)) > 127


# ---------- 2. 跟素材库 foot 图逐个比 IoU ----------
# 游戏立绘可能是全身像的下半截，素材 foot 也是下半截，bbox 归一化后比
fg_bbox = bbox_crop(figure)
H = 300

results = []
for f in sorted(LIB.glob("*_foot.png")):
    name = f.stem.split("_")[1]
    lib = np.array(Image.open(f).convert("L")) < 127  # 黑=剪影
    lib_bbox = bbox_crop(lib)
    # 等高归一化（保持各自宽高比，按高度对齐到 H，宽度居中到统一画布）
    def norm(m):
        h, w = m.shape
        nw = max(1, round(w * H / h))
        r = resize_mask(m, H, nw)
        canvas = np.zeros((H, 400), bool)
        x0 = max(0, (400 - nw) // 2)
        if nw <= 400:
            canvas[:, x0:x0 + nw] = r
        else:
            canvas = r[:, :400]
        return canvas
    a, b = norm(fg_bbox), norm(lib_bbox)
    inter = (a & b).sum()
    union = (a | b).sum()
    iou = inter / union if union else 0
    results.append((iou, name))

results.sort(reverse=True)
print("\n=== IoU 前 10 名 ===")
for iou, name in results[:10]:
    print(f"{iou:.3f}  {name}")
