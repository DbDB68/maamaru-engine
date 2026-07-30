# -*- coding: utf-8 -*-
"""边缘匹配实验：轮廓分数 vs 填充F1，三块已知板子对比"""
from pathlib import Path
import sys
import numpy as np
from PIL import Image
from collections import deque

sys.path.insert(0, str(Path(__file__).parent))
from touken.silhouette import extract_observed

LIB = Path("Silhouette1.0.2 (2)/silhouette")

CASES = [
    ("board01 五虎退 foot", "silhouette_lab/board01a/board_after_b08.png", "foot", "五虎退"),
    ("board02 小竜景光 head", "silhouette_lab/board02a/b09/f016.png", "head", "小竜景光"),
    ("board03 浦島虎徹 foot", "silhouette_lab/board03a/board_after_b08.png", "foot", "浦島虎徹"),
]


def largest_component(mask):
    """只保留最大连通域，清掉小碎块污染"""
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
    for y, x in best_comp:
        out[y, x] = True
    return out


def edge(mask):
    """轮廓 = mask 减去腐蚀后的自己"""
    m = mask
    eroded = m[1:-1, 1:-1] & m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]
    e = m.copy()
    e[1:-1, 1:-1] = m[1:-1, 1:-1] & ~eroded
    return e


def dilate(mask, r=2):
    """近似膨胀：8方向偏移或"""
    out = mask.copy()
    for _ in range(r):
        m = out
        out = m.copy()
        out[1:, :] |= m[:-1, :]
        out[:-1, :] |= m[1:, :]
        out[:, 1:] |= m[:, :-1]
        out[:, :-1] |= m[:, 1:]
    return out


def best_f1(O, T, o_sum, t_sum):
    nw = T.shape[0]
    H, W = O.shape
    fh, fw = H + nw, W + nw
    corr = np.fft.irfft2(np.fft.rfft2(O, (fh, fw)) * np.fft.rfft2(T[::-1, ::-1], (fh, fw)), (fh, fw))
    return corr.max() * 2 / (o_sum + t_sum)


SCALES = np.arange(0.8, 1.31, 0.05)

for label, shot, view, truth in CASES:
    img = np.array(Image.open(shot).convert("RGB"))
    obs = largest_component(extract_observed(img))
    O = obs.astype(np.float32)
    o_sum = O.sum()
    eO = edge(obs)
    d_eO = dilate(eO, 2).astype(np.float32)
    eO_sum = eO.sum()

    lib = {}
    for f in sorted(LIB.glob(f"*_{view}.png")):
        parts = f.stem.split("_")
        if len(parts) >= 3:
            lib[parts[1]] = np.array(Image.open(f).convert("L")) < 127

    fill_rank, edge_rank = [], []
    for name, tmask in lib.items():
        bf, be = 0.0, 0.0
        for s in SCALES:
            nw = int(round(300 * s))
            t = Image.fromarray((tmask * 255).astype(np.uint8)).resize((nw, nw), Image.BILINEAR)
            T = np.array(t) > 127
            Tf = T.astype(np.float32)
            bf = max(bf, best_f1(O, Tf, o_sum, Tf.sum()))
            # 边缘对称分：|eT∩dil(eO)|/|eT| + |eO∩dil(eT)|/|eO|
            eT = edge(T)
            eT_sum = eT.sum()
            if eT_sum == 0:
                continue
            H, W = O.shape
            fh, fw = H + nw, W + nw
            c1 = np.fft.irfft2(np.fft.rfft2(d_eO, (fh, fw)) * np.fft.rfft2(eT[::-1, ::-1].astype(np.float32), (fh, fw)), (fh, fw)).max() / eT_sum
            d_eT = dilate(eT, 2).astype(np.float32)
            c2 = np.fft.irfft2(np.fft.rfft2(eO.astype(np.float32), (fh, fw)) * np.fft.rfft2(d_eT[::-1, ::-1], (fh, fw)), (fh, fw)).max() / eO_sum
            be = max(be, (c1 + c2) / 2)
        fill_rank.append((bf, name))
        edge_rank.append((be, name))

    fill_rank.sort(reverse=True)
    edge_rank.sort(reverse=True)
    print(f"\n===== {label} =====")
    print("  [填充F1 前5]", "  ".join(f"{n}:{v:.3f}" for v, n in fill_rank[:5]))
    fr = next(i + 1 for i, (_, n) in enumerate(fill_rank) if n == truth)
    print(f"  真身填充排名: {fr}")
    print("  [边缘分 前5]", "  ".join(f"{n}:{v:.3f}" for v, n in edge_rank[:5]))
    er = next(i + 1 for i, (_, n) in enumerate(edge_rank) if n == truth)
    print(f"  真身边缘排名: {er}")
