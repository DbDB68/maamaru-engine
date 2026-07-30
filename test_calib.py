# -*- coding: utf-8 -*-
"""剪影标定v2：饱和度抠图 + 最大连通域，先保证 mask 干净再谈匹配"""
from pathlib import Path
import numpy as np
from PIL import Image
from collections import deque

ROOT = Path(__file__).parent
LIB = ROOT / "Silhouette1.0.2 (2)" / "silhouette"

# ---------- 1. 抠图：饱和度+亮度双条件，最大连通域 ----------
X0, Y0, X1, Y1 = 710, 215, 1013, 453
panel = np.array(Image.open(ROOT / "board_full.png").convert("RGB").crop((X0, Y0, X1, Y1))).astype(int)
mx = panel.max(axis=2)
mn = panel.min(axis=2)
sat = mx - mn
lum = panel.mean(axis=2)
figure = (sat > 25) | (lum < 230)

# 最大连通域（BFS）
visited = np.zeros(figure.shape, bool)
best_comp = None
best_size = 0
H, W = figure.shape
for sy in range(0, H, 3):
    for sx in range(0, W, 3):
        if figure[sy, sx] and not visited[sy, sx]:
            comp = []
            q = deque([(sy, sx)])
            visited[sy, sx] = True
            while q:
                y, x = q.popleft()
                comp.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W and figure[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        q.append((ny, nx))
            if len(comp) > best_size:
                best_size = len(comp)
                best_comp = comp

obs = np.zeros(figure.shape, bool)
for y, x in best_comp:
    obs[y, x] = True
Image.fromarray((obs * 255).astype(np.uint8)).save("calib_obs2.png")
print("observed 像素:", obs.sum(), " shape:", obs.shape)

# ---------- 2. 素材库 ----------
lib = {}
for f in sorted(LIB.glob("*_foot.png")):
    name = f.stem.split("_")[1]
    lib[name] = np.array(Image.open(f).convert("L")) < 127


def place(template, scale, dx, dy, canvas_shape):
    th, tw = template.shape
    nw, nh = max(1, int(tw * scale)), max(1, int(th * scale))
    t = Image.fromarray((template * 255).astype(np.uint8)).resize((nw, nh), Image.BILINEAR)
    t = np.array(t) > 127
    canvas = np.zeros(canvas_shape, bool)
    x0, y0 = int(round(dx)), int(round(dy))
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    cw = min(nw - sx0, canvas_shape[1] - dx0)
    ch = min(nh - sy0, canvas_shape[0] - dy0)
    if cw > 0 and ch > 0:
        canvas[dy0:dy0 + ch, dx0:dx0 + cw] = t[sy0:sy0 + ch, sx0:sx0 + cw]
    return canvas


def iou(a, b):
    inter = (a & b).sum()
    union = (a | b).sum()
    return inter / union if union else 0.0


# ---------- 3. 给肥前忠広搜最佳变换 ----------
target = lib["肥前忠広"]
best = (0, None)
for scale in np.arange(0.5, 1.51, 0.05):
    for dy in range(-100, H, 10):
        for dx in range(-100, W, 10):
            t = place(target, scale, dx, dy, obs.shape)
            v = iou(obs, t)
            if v > best[0]:
                best = (v, (scale, dx, dy))
print(f"肥前忠広 最佳: IoU={best[0]:.3f} @ scale={best[1][0]:.2f} dx={best[1][1]} dy={best[1][2]}")

# ---------- 4. 全员在同一变换下评分 ----------
scale, dx, dy = best[1]
rank = []
for name, t in lib.items():
    rank.append((iou(obs, place(t, scale, dx, dy, obs.shape)), name))
rank.sort(reverse=True)
print("\n=== 同变换 IoU 前 10 ===")
for v, n in rank[:10]:
    print(f"{v:.3f}  {n}")

ov = np.zeros((*obs.shape, 3), np.uint8)
ov[obs] = (0, 255, 0)
t_placed = place(target, scale, dx, dy, obs.shape)
ov[t_placed] = ov[t_placed] // 2 + (128, 0, 0)
ov[obs & t_placed] = (255, 255, 0)
Image.fromarray(ov).save("calib_overlay2.png")
print("saved calib_obs2.png / calib_overlay2.png")
