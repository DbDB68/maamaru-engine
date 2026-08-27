# -*- coding: utf-8 -*-
"""
江户城潜入调查：地图档案与巡游选路逻辑（纯函数，无 IO 依赖）

数据来源：resource/base/maps/edocastle-4.json
策略：老大审定的固定巡游顺序 + 悲观零回步不变量。
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Iterable


# 难度四·超难固定巡游顺序（跳过节点 3）
EDOCASTLE_TOUR: list[int] = [
    21, 20, 19, 17, 18, 6, 4, 10, 14, 13, 15, 16, 9, 8, 11, 12, 1, 7, 2
]


def load_archive(path: str | Path) -> dict:
    """加载地图档案 JSON。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_graph(archive: dict) -> dict[int, set[int]]:
    """把档案的 edges 转成邻接表。"""
    graph: dict[int, set[int]] = {node["id"]: set() for node in archive["nodes"]}
    for a, b in archive["edges"]:
        graph[a].add(b)
        graph[b].add(a)
    return graph


def bfs_distance(graph: dict[int, set[int]], start: int, goal: int) -> int | None:
    """BFS 最短距离（边数）。不可达返回 None。"""
    if start == goal:
        return 0
    visited = {start}
    queue = deque([(start, 0)])
    while queue:
        cur, dist = queue.popleft()
        for nxt in graph.get(cur, ()):
            if nxt == goal:
                return dist + 1
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, dist + 1))
    return None


def bfs_path(graph: dict[int, set[int]], start: int, goal: int) -> list[int] | None:
    """BFS 最短路径（节点序列，含起止）。不可达返回 None。"""
    if start == goal:
        return [start]
    visited = {start}
    parent = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in graph.get(cur, ()):
            if nxt in visited:
                continue
            visited.add(nxt)
            parent[nxt] = cur
            if nxt == goal:
                path = [nxt]
                while parent[path[-1]] is not None:
                    path.append(parent[path[-1]])
                return list(reversed(path))
            queue.append(nxt)
    return None


def _first_unvisited_target(tour: Iterable[int], visited: set[int]) -> int | None:
    """按巡游顺序找第一个未访问节点。"""
    for node in tour:
        if node not in visited:
            return node
    return None


def _next_toward(graph: dict[int, set[int]], cur: int, goal: int) -> int | None:
    """从 cur 向 goal 走一短步（BFS 路径的第二个节点）。"""
    path = bfs_path(graph, cur, goal)
    if path and len(path) > 1:
        return path[1]
    return None


def decide_next(
    archive: dict,
    tour: Iterable[int],
    cur: int,
    visited: set[int],
    steps: int,
) -> tuple[int, str]:
    """
    江户城单步决策。

    巡游序给出「还想踩哪些点」的优先级。每步先找巡游序中第一个未访问节点
    target；能直接到/经 BFS 一步到且满足不变量就走，否则沿 BFS 直奔王点。

    Args:
        archive: 地图档案（含 nodes/edges/boss）
        tour: 巡游顺序
        cur: 当前节点 id
        visited: 已访问节点集合（应已包含 cur）
        steps: 剩余行动步数（移动前）

    Returns:
        (next_node, mode)，mode ∈ {"tour", "rush"}
        rush 表示按 BFS 直奔王点。
    """
    graph = build_graph(archive)
    boss = archive.get("boss", 2)
    node_ids = {node["id"] for node in archive["nodes"]}

    tour_set = set(tour)
    if cur not in node_ids or cur not in tour_set:
        # 防御：当前点不在档案里或不在巡游序上，直接按图上 BFS 奔王点
        nxt = _next_toward(graph, cur, boss)
        return (nxt if nxt is not None else boss), "rush"

    target = _first_unvisited_target(tour, visited)
    if target is None:
        # 巡游序已清完，直奔王点
        nxt = _next_toward(graph, cur, boss)
        return (nxt if nxt is not None else boss), "rush"

    # 确定迈向 target 的下一格
    if target in graph.get(cur, set()):
        nxt = target
    else:
        nxt = _next_toward(graph, cur, target)
        if nxt is None:
            # 连 target 都到不了，保守奔王点
            nxt = _next_toward(graph, cur, boss)
            return (nxt if nxt is not None else boss), "rush"

    # 不变量：悲观零回步，移动到 nxt 后 steps-1 必须 >= BFS(nxt, boss)
    dist_to_boss = bfs_distance(graph, nxt, boss)
    if dist_to_boss is not None and steps - 1 >= dist_to_boss:
        return nxt, "tour"

    # 否则沿 BFS 最短直奔王点
    nxt = _next_toward(graph, cur, boss)
    return (nxt if nxt is not None else boss), "rush"
