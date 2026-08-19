# -*- coding: utf-8 -*-
"""
生产版小地图阅读器（"王点前撤退"的决策原语）

从 lab/ 地图实验室搬过来的已验证逻辑：
  认节点（HSV 填色 + 黑描边校验）→ 推拓扑（法线横带扫弧线 +
  边上躺/绕路规则）→ 认旗标（当前位置）→ BFS 算当前节点到 BOSS 的图距离。

只认"决策屏"（战后部队状态屏）右上角的迷你地图——那里永远干净完整。
阈值全是真机采样调出来的，别瞎改；要改先去 lab/ 里验证。

cv2 是可选依赖：没装 opencv 时所有函数安全返回 None，
调用方按"认不出来"处理（继续正常行军），绝不能因此误判撤退。
"""

from collections import deque
from itertools import combinations

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:  # pragma: no cover - 取决于运行环境
    cv2 = None
    np = None
    CV2_AVAILABLE = False

# 右上迷你地图的固定区域（1280x720 实测量）
MINIMAP_ROI = (890, 120, 1265, 360)
MINIMAP_SCALE = 3

# 节点填充色 HSV 阈值（真机采样，见 lab/detect_nodes.py 注释）：
#   BOSS 红 H>165/H<10 S>150 V>120；紫点 H110-160 S>100 V>60；
#   白点 S<60 V>180；绿点 H45-75 S>120 V>80（草地 H≈34 不撞）
_FLAG_MIN_W, _FLAG_MAX_W = 5, 20     # 旗子约 8x13px，竖的
_FLAG_MIN_H, _FLAG_MAX_H = 8, 28
_FLAG_DX, _FLAG_DY_MIN, _FLAG_DY_MAX = 12, 6, 22  # 旗底下 6-22px、±12px 内=当前节点


def _node_masks(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    masks = {
        "boss": ((h > 165) | (h < 10)) & (s > 150) & (v > 120),
        "battle": (h > 110) & (h < 160) & (s > 100) & (v > 60),
        "white": (s < 60) & (v > 180),
        "green": (h > 45) & (h < 75) & (s > 120) & (v > 80),
    }
    # 开运算：核比连线粗（连线约6-8px），细线消失，节点填充留下
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    return {name: cv2.morphologyEx(m.astype(np.uint8) * 255, cv2.MORPH_OPEN, k)
            for name, m in masks.items()}


def _outline_ratio(img, x, y, w, h, band=6):
    """外圈暗像素占比：真节点有一圈黑描边，白墙/建筑碎片没有。"""
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2]
    H, W = v.shape
    x1, y1 = max(0, x - band), max(0, y - band)
    x2, y2 = min(W, x + w + band), min(H, y + h + band)
    outer = v[y1:y2, x1:x2]
    if outer.size == 0:
        return 0.0
    ring = np.ones(outer.shape, bool)
    ring[y - y1:y - y1 + h, x - x1:x - x1 + w] = False
    ring_px = outer[ring]
    return float((ring_px < 100).mean()) if ring_px.size else 0.0


def _detect_nodes(img, roi, scale):
    """返回 [{name,cx,cy,w,h,area}]，坐标是原图坐标。"""
    x0, y0, x1, y1 = roi
    sub = img[y0:y1, x0:x1]
    if scale != 1:
        sub = cv2.resize(sub, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC)
    masks = _node_masks(sub)
    nodes = []
    for name, mask in masks.items():
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if not 200 < area < 4000 * scale * scale:
                continue
            x, y, w, h = cv2.boundingRect(c)
            aspect = w / max(h, 1)
            solidity = area / max(w * h, 1)
            if not (1.1 < aspect < 3.5 and solidity > 0.55):
                continue
            # 真节点黑描边占比≈0.6，白墙碎片≈0.18，多线枢纽≈0.33；阈值0.28卡中间
            if _outline_ratio(sub, x, y, w, h, band=6) < 0.28:
                continue
            nodes.append({
                "name": name,
                "cx": x0 + int((x + w / 2) / scale),
                "cy": y0 + int((y + h / 2) / scale),
                "w": int(w / scale), "h": int(h / scale),
                "area": int(area / (scale * scale)),
            })
    # 不同颜色掩码可能圈到同一个点，中心太近的去重（留面积大的）。
    # 半径定 15px：同点双色误检的中心几乎重合（<5px）；
    # 8-4 市街图有相距仅 24px 的真实相邻节点（紫点贴着王点），
    # 原来的 30px 会把真王点当重影误杀。
    nodes.sort(key=lambda n: -n["area"])
    deduped = []
    for n in nodes:
        if all((n["cx"] - m["cx"]) ** 2 + (n["cy"] - m["cy"]) ** 2 > 15 ** 2
               for m in deduped):
            deduped.append(n)
    return deduped


def _dark_mask(img):
    """纯黑线/描边：V 很低就行。连线是带暖棕底色的死黑，加 S 条件会误杀。"""
    return cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2] < 80


def _edge_score(dark, p1, p2, samples=24, margin=8, band=24):
    """两点间黑线得分。连线可能是弧线：每个采样点沿法线 ±band px 扫横带。"""
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy))
    if length < margin * 2 + 4:
        return 0.0
    nx, ny = -dy / length, dx / length
    hits = total = 0
    H, W = dark.shape
    for t in np.linspace(0, 1, samples):
        if min(t, 1 - t) * length < margin:
            continue
        xa, ya = x1 + dx * t, y1 + dy * t
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


def _build_graph(img, roi, scale, edge_threshold=0.7):
    """检测节点 + 推连线，返回 (nodes, edges)；丢弃没有连线的假节点。"""
    x0, y0, x1, y1 = roi
    sub = img[y0:y1, x0:x1]
    work = cv2.resize(sub, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_CUBIC)
    nodes = _detect_nodes(img, roi=roi, scale=scale)
    dark = _dark_mask(work)
    pts = [((n["cx"] - x0) * scale, (n["cy"] - y0) * scale) for n in nodes]
    max_edge_len = work.shape[1] * 0.45  # 不可能有横跨半张图的边
    edges = []
    for i, j in combinations(range(len(nodes)), 2):
        dist = float(np.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))
        if dist > max_edge_len:
            continue
        score = _edge_score(dark, pts[i], pts[j])
        if score < edge_threshold:
            continue
        # 边上躺规则：线段附近（12 原图 px 内）坐着第三个节点 → 不是直连
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
            if np.hypot(xk - (x1 + dx * t), yk - (y1 + dy * t)) < 12 * scale:
                blocked = True
                break
        if not blocked:
            edges.append((i, j, score))

    # 绕路规则：ik+kj ≈ ij（比值<1.18）说明 k 躺在 i-j 之间，i→j 是蹭线假边
    def _dist(a, b):
        return float(np.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]))
    edge_set = {(i, j) for i, j, _ in edges} | {(j, i) for i, j, _ in edges}
    edges = [(i, j, s) for i, j, s in edges
             if not any(k not in (i, j)
                        and (i, k) in edge_set and (k, j) in edge_set
                        and (_dist(i, k) + _dist(k, j)) < _dist(i, j) * 1.18
                        for k in range(len(nodes)))]

    if edges:
        keep = sorted({i for i, _, _ in edges} | {j for _, j, _ in edges})
        remap = {old: new for new, old in enumerate(keep)}
        nodes = [nodes[old] for old in keep]
        edges = [(remap[i], remap[j], s) for i, j, s in edges]
    return nodes, edges


def _find_flag_candidates(img, roi, scale):
    """白色小旗 = 竖直白色小块。返回所有候选中心（原图坐标），高的在前。

    市街图白天背景下，云/河面/建筑会贡献假的竖白块，而且可能比真旗还高，
    只返回"最高的一个"会被假旗抢走——所以全部返回，
    由调用方用"旗底下必须有节点"的几何闸门来筛。"""
    x0, y0, x1, y1 = roi
    sub = img[y0:y1, x0:x1]
    work = cv2.resize(sub, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 180)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    cands = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        w0, h0 = w / scale, h / scale
        if not (_FLAG_MIN_W < w0 < _FLAG_MAX_W
                and _FLAG_MIN_H < h0 < _FLAG_MAX_H):
            continue
        if w0 / max(h0, 1) >= 0.9:  # 要竖的，横椭圆是白点
            continue
        cx = x0 + (x + w / 2) / scale
        cy = y0 + (y + h / 2) / scale
        cands.append((cx, cy, h0))
    cands.sort(key=lambda c: -c[2])
    return [(cx, cy) for cx, cy, _ in cands]


def _node_under_flag(nodes, flag):
    """旗底下 6-22px、左右 ±12px 内的节点下标；没有就 None。"""
    fx, fy = flag
    for i, n in enumerate(nodes):
        if (abs(n["cx"] - fx) <= _FLAG_DX
                and _FLAG_DY_MIN <= n["cy"] - fy <= _FLAG_DY_MAX):
            return i
    return None


def boss_distance_from_image(img):
    """算当前节点到 BOSS 的图距离。

    Args:
        img: BGR numpy 截图（maa.screenshot() 的返回值）

    Returns:
        int: 距王点 N 步（1 = 下一脚就是王点）
        None: cv2 没装 / 图不对 / 节点、旗标或王点没认出来 / 王点不可达。
              调用方必须把 None 当"不知道"，继续正常行军，绝不能当撤退信号。
    """
    if not CV2_AVAILABLE or img is None:
        return None
    try:
        nodes, edges = _build_graph(img, roi=MINIMAP_ROI, scale=MINIMAP_SCALE,
                                    edge_threshold=0.7)
        boss = next((i for i, n in enumerate(nodes) if n["name"] == "boss"),
                    None)
        # _build_graph 丢孤立点会重排下标，拿旗标坐标回认当前节点最稳。
        # 旗标候选按几何闸门筛：底下有节点的才算真旗（挡市街图的假旗）。
        cur = None
        for flag in _find_flag_candidates(img, roi=MINIMAP_ROI,
                                          scale=MINIMAP_SCALE):
            cur = _node_under_flag(nodes, flag)
            if cur is not None:
                break
        if cur is None or boss is None:
            return None

        adj = {i: [] for i in range(len(nodes))}
        for i, j, _ in edges:
            adj[i].append(j)
            adj[j].append(i)
        dist = {cur: 0}
        q = deque([cur])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    q.append(v)
        return dist.get(boss)
    except Exception:
        return None
