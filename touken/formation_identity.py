# -*- coding: utf-8 -*-
"""编队实例比对用的内番证据；不修改刀账原始快照。"""

from datetime import datetime

GROWTH_STATS = ("生存", "侦察")
OTHER_STATS = ("打击", "防御", "机动", "冲力", "隐蔽", "必杀")


def cultivation_pairs(state: dict, snapshot_at=None, snapshot_id=None) -> dict:
    """当前耕作表及已核对的涨值；历史证据只在同一份刀账内有效。"""
    pairs = {}
    history = state.get("cultivation_evidence") or {}
    for oid, item in (history.items() if isinstance(history, dict) else ()):
        if (isinstance(item, dict) and item.get("snapshot_id") == snapshot_id
                and snapshot_id is not None
                and all(isinstance(item.get(key), int) for key in GROWTH_STATS)):
            pairs[f"oid:{oid}"] = {key: item[key] for key in GROWTH_STATS}
    try:
        table_at = datetime.strptime(state["stats_at"], "%Y-%m-%d %H:%M:%S").timestamp()
        if snapshot_at is None or table_at < float(snapshot_at):
            return pairs
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return pairs
    for name, stats in (state.get("stats") or {}).items():
        if not isinstance(stats, dict):
            continue
        survival, recon = (stats.get(key) for key in GROWTH_STATS)
        if all(isinstance(v, int) and not isinstance(v, bool) for v in
               (survival, recon)):
            pairs[name] = {"生存": survival, "侦察": recon}
    return pairs


def record_cultivation_growth(state: dict, table: dict, pool: dict) -> dict:
    """内番前后数值各涨至多 1，且旧值在完整刀账中唯一时，记到那一振。"""
    if not pool.get("done"):
        return state
    snapshot_id = (pool.get("source") or {}).get("snapshot_id")
    if snapshot_id is None:
        return state
    prior_evidence = state.get("cultivation_evidence") or {}
    evidence = dict(prior_evidence) if isinstance(prior_evidence, dict) else {}
    by_oid = {e.get("observation_id"): e for e in pool.get("entries") or []}
    for name, current in table.items():
        previous = (state.get("stats") or {}).get(name) or {}
        if not all(isinstance(previous.get(k), int) and
                   isinstance(current.get(k), int) for k in GROWTH_STATS):
            continue
        deltas = [current[k] - previous[k] for k in GROWTH_STATS]
        if not any(deltas) or any(delta not in (0, 1) for delta in deltas):
            continue
        matches = []
        for oid, entry in by_oid.items():
            if not oid or entry.get("name_zh") != name:
                continue
            prior = evidence.get(oid)
            old_stats = (prior if isinstance(prior, dict) and
                         prior.get("snapshot_id") == snapshot_id
                         else entry.get("stats") or {})
            if all(old_stats.get(k) == previous[k] for k in GROWTH_STATS):
                matches.append(oid)
        if len(matches) == 1:
            evidence[matches[0]] = {"snapshot_id": snapshot_id, "name": name,
                                    **{k: current[k] for k in GROWTH_STATS}}
    state["cultivation_evidence"] = evidence
    return state


def growth_stats_match(old: dict, new: dict, name: str,
                       cultivation: dict, *, old_survival_max=None,
                       new_survival_max=None, observation_id=None) -> bool:
    """普通刀只比生存/侦察；耕作涨值要当前表数值和其余六项作证。"""
    old_pair = tuple(old.get(key) for key in GROWTH_STATS)
    new_pair = tuple(new.get(key) for key in GROWTH_STATS)
    if any(not isinstance(v, int) or isinstance(v, bool)
           for v in old_pair + new_pair):
        return False
    same_pair = old_pair == new_pair
    same_max = (old_survival_max is None
                or old_survival_max == new_survival_max)
    if same_pair and same_max:
        return True
    table_pair = cultivation.get(name) or {}
    history_pair = cultivation.get(f"oid:{observation_id}") or {}
    table_confirmed = (
        new_pair == tuple(table_pair.get(key) for key in GROWTH_STATS)
        and all(new - old <= 1 for old, new in zip(old_pair, new_pair)))
    history_confirmed = new_pair == tuple(
        history_pair.get(key) for key in GROWTH_STATS)
    if (not (table_confirmed or history_confirmed)
            or any(new < old for old, new in zip(old_pair, new_pair))
            or (old_survival_max is not None and new_survival_max is None)
            or (old_survival_max is not None and new_survival_max is not None
                and new_survival_max < old_survival_max)
            or (new_survival_max is not None
                and new_survival_max != new["生存"])):
        return False
    return all(old.get(key) is not None and old.get(key) == new.get(key)
               for key in OTHER_STATS)
