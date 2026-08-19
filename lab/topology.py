# -*- coding: utf-8 -*-
"""
地图实验室 · 连线识别 v0（节点 → 拓扑图）

原理：节点间的连线是纯黑粗线（约 6-8px）。对每一对节点，
沿中心连线均匀采样，采样点里黑像素占比够高 = 有边。
真值校验靠人眼看标注图。

用法：
    .venv/Scripts/python.exe -m lab.topology lab/samples/5-4_step1.png --minimap
    .venv/Scripts/python.exe -m lab.topology lab/samples/march_175551.png
输出：终端打印邻接表 + lab/out/<图名>_graph.png 标注图
"""

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "lab" / "out"

from lab.detect_nodes import detect, NODE_RULES  # noqa: E402

# 右上迷你地图的固定区域（1280x720 实测量）
MINIMAP_ROI = (890, 120, 1265, 360)


def _dark_mask(img):
    """纯黑线/描边：V 很低就行。连线是带暖棕底色的死黑（V=0-53, S 很高），
    加 S 条件反而会把它误杀；草地 V>150 天然不撞，深蓝山影（V≈46）靠
    高得分阈值和"线段得连续黑"来挡。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return hsv[:, :, 2] < 80


def edge_score(dark, p1, p2, samples=24, margin=8, band=24):
    """两点间黑线得分。连线可能是弧线：每个采样点沿法线方向 ±band px
    扫一条横带，带里有暗像素就算命中。band 取 24（放大3倍下≈原图8px），
    既容得下弧线的弯曲，又蹭不到邻近节点（实测最近干扰距离≈17原图px）。
    margin: 两端各跳过多少像素（避开节点自身的黑描边）"""
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy))
    if length < margin * 2 + 4:
        return 0.0
    # 法线单位向量
    nx, ny = -dy / length, dx / length
    hits = 0
    total = 0
    H, W = dark.shape
    for t in np.linspace(0, 1, samples):
        xa = x1 + dx * t
        ya = y1 + dy * t
        # 跳过两端节点描边范围
        if min(t, 1 - t) * length < margin:
            continue
        hit = False
        for off in range(-band, band + 1, 2):
            x = int(round(xa + nx * off))
            y = int(round(ya + ny * off))
            if 0 <= x < W and 0 <= y < H and dark[y, x]:
                hit = True
                break
        total += 1
        hits += int(hit)
    return hits / total if total else 0.0


def build_graph(img, roi=None, scale=1, edge_threshold=0.75,
                max_edge_len=None, drop_isolated=False):
    """检测节点 + 推连线，返回 (nodes, edges)。edges=[(i,j,score)]

    drop_isolated=True 时丢弃没有任何连线的"节点"（树丛/石头补丁会
    长成节点样但没有线连着）。只在线上永远干净完整的迷你地图里用，
    全屏地图有骰子盘/立绘遮挡，孤立点可能是被盖住真节点，不能丢。
    """
    if roi:
        x0, y0, x1, y1 = roi
        sub = img[y0:y1, x0:x1]
    else:
        x0, y0 = 0, 0
        sub = img
    work = cv2.resize(sub, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_CUBIC) if scale != 1 else sub
    nodes = detect(img, roi=roi, scale=scale)
    dark = _dark_mask(work)
    # 节点中心换算到 work 坐标
    pts = [((n["cx"] - x0) * scale, (n["cy"] - y0) * scale) for n in nodes]
    if max_edge_len is None:
        max_edge_len = work.shape[1] * 0.45  # 不可能有横跨半张图的边
    edges = []
    for i, j in combinations(range(len(nodes)), 2):
        dist = float(np.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))
        if dist > max_edge_len:
            continue
        score = edge_score(dark, pts[i], pts[j])
        if score < edge_threshold:
            continue
        # 边上躺规则：线段附近（12 原图 px 内）坐着第三个节点，
        # 那这条"边"其实是经过它的两条边，不是直连
        x1, y1 = pts[i]
        x2, y2 = pts[j]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        blocked = False
        for k, (xk, yk) in enumerate(pts):
            if k in (i, j):
                continue
            t = max(0.0, min(1.0,
                             ((xk - x1) * dx + (yk - y1) * dy) / L2))
            d = np.hypot(xk - (x1 + dx * t), yk - (y1 + dy * t))
            if d < 12 * scale:
                blocked = True
                break
        if not blocked:
            edges.append((i, j, round(score, 2)))
    if drop_isolated and edges:
        keep = sorted({i for i, _, _ in edges} | {j for _, j, _ in edges})
        remap = {old: new for new, old in enumerate(keep)}
        nodes = [nodes[old] for old in keep]
        edges = [(remap[i], remap[j], s) for i, j, s in edges]
    return nodes, edges


def annotate_graph(img, nodes, edges, roi=None):
    out = img.copy()
    ox, oy = (roi[0], roi[1]) if roi else (0, 0)
    color_of = {r["name"]: r["color"] for r in NODE_RULES}
    for i, j, score in edges:
        p1 = (nodes[i]["cx"], nodes[i]["cy"])
        p2 = (nodes[j]["cx"], nodes[j]["cy"])
        cv2.line(out, p1, p2, (0, 200, 255), 1, cv2.LINE_AA)
    for idx, n in enumerate(nodes):
        c = color_of[n["name"]]
        cv2.circle(out, (n["cx"], n["cy"]), 8, c, 2)
        cv2.putText(out, f'{idx}:{n["label"]}', (n["cx"] + 9, n["cy"] + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, c, 1, cv2.LINE_AA)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--minimap", action="store_true",
                    help="只检测右上迷你地图（放大3倍）")
    ap.add_argument("--threshold", type=float, default=0.75)
    args = ap.parse_args()

    src = Path(args.image)
    img = cv2.imread(str(src))
    if img is None:
        print(f"读不了图: {src}")
        sys.exit(1)

    roi = MINIMAP_ROI if args.minimap else None
    scale = 3 if args.minimap else 1
    nodes, edges = build_graph(img, roi=roi, scale=scale,
                               edge_threshold=args.threshold,
                               drop_isolated=args.minimap)

    print(f"节点 {len(nodes)} 个，连线 {len(edges)} 条:")
    for idx, n in enumerate(nodes):
        print(f"  [{idx}] {n['label']} ({n['cx']},{n['cy']})")
    print("邻接表:")
    adj = {i: [] for i in range(len(nodes))}
    for i, j, s in edges:
        adj[i].append(j)
        adj[j].append(i)
    for i in sorted(adj):
        if adj[i]:
            print(f"  [{i}] -> {sorted(adj[i])}")

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{src.stem}_graph.png"
    cv2.imwrite(str(out_path), annotate_graph(img, nodes, edges, roi))
    print(f"标注图: {out_path}")


if __name__ == "__main__":
    main()
