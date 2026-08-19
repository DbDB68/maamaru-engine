# -*- coding: utf-8 -*-
"""
地图实验室 · 王点距离（"王点前撤退"的决策原语）

决策屏（战后部队状态屏）右上角的小地图永远干净完整。
认节点 → 推拓扑 → 认旗标（当前位置）→ BFS 算当前节点到 BOSS 的图距离。
输出"距王点 N 步"，给"王点前撤退/指定点前撤退"当扳机。

用法：
    .venv/Scripts/python.exe -m lab.boss_distance lab/samples/5-4_step1.png
"""

import sys
from collections import deque
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "lab" / "out"

from lab.topology import build_graph, MINIMAP_ROI  # noqa: E402
from lab.position import current_node  # noqa: E402
from lab.detect_nodes import NODE_RULES  # noqa: E402


def boss_distance(img):
    """返回 (nodes, edges, cur_idx, boss_idx, dist)。认不出来就对应项为 None。"""
    nodes, edges = build_graph(img, roi=MINIMAP_ROI, scale=3,
                               edge_threshold=0.7, drop_isolated=True)
    _, flag, cur = current_node(img)
    boss = next((i for i, n in enumerate(nodes) if n["name"] == "boss"), None)
    # 注意：build_graph 的 drop_isolated 会重排下标，current_node 里的
    # detect 不带 drop_isolated，下标不一致——这里用坐标回认当前节点。
    if flag is not None:
        fx, fy = flag
        cur = None
        for i, n in enumerate(nodes):
            dx = n["cx"] - fx
            dy = n["cy"] - fy
            if abs(dx) <= 12 and 6 <= dy <= 22:
                cur = i
                break
    if cur is None or boss is None:
        return nodes, edges, cur, boss, None

    adj = {i: [] for i in range(len(nodes))}
    for i, j, _ in edges:
        adj[i].append(j)
        adj[j].append(i)
    # BFS 图距离
    dist = {cur: 0}
    q = deque([cur])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return nodes, edges, cur, boss, dist.get(boss)


def main():
    src = Path(sys.argv[1])
    img = cv2.imread(str(src))
    if img is None:
        print(f"读不了图: {src}")
        sys.exit(1)
    nodes, edges, cur, boss, d = boss_distance(img)
    print(f"节点 {len(nodes)} 个，边 {len(edges)} 条")
    if cur is None:
        print("当前位置没认出来")
        return
    print(f"当前: [{cur}] {nodes[cur]['label']} ({nodes[cur]['cx']},{nodes[cur]['cy']})")
    if boss is None:
        print("王点不在图上")
        return
    print(f"王点: [{boss}] ({nodes[boss]['cx']},{nodes[boss]['cy']})")
    if d is None:
        print("王点不可达（拓扑缺边）")
    else:
        print(f"📏 距王点 {d} 步" + (" —— ⚠️ 下一脚就是王点！" if d == 1 else ""))

    # 标注：橙圈=当前，红圈=王点
    out = img.copy()
    color_of = {r["name"]: r["color"] for r in NODE_RULES}
    for idx, n in enumerate(nodes):
        c = color_of[n["name"]]
        cv2.circle(out, (n["cx"], n["cy"]), 9, c, 1)
    if cur is not None:
        cv2.circle(out, (nodes[cur]["cx"], nodes[cur]["cy"]), 12,
                   (0, 200, 255), 3)
    if boss is not None:
        cv2.circle(out, (nodes[boss]["cx"], nodes[boss]["cy"]), 13,
                   (0, 0, 255), 3)
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{src.stem}_bossdist.png"
    cv2.imwrite(str(out_path), out)
    print(f"标注图: {out_path}")


if __name__ == "__main__":
    main()
