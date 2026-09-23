# -*- coding: utf-8 -*-
"""耕作涨值只在能认到唯一实例时留作编队证据。"""

from touken.formation_identity import cultivation_pairs, record_cultivation_growth


def _pool(second_pair=None):
    entries = [{"observation_id": "24:1", "name_zh": "测试刀",
                "stats": {"生存": 55, "侦察": 39}}]
    if second_pair:
        entries.append({"observation_id": "24:2", "name_zh": "测试刀",
                        "stats": dict(zip(("生存", "侦察"), second_pair))})
    return {"done": True, "source": {"snapshot_id": 24}, "entries": entries}


def test_growth_evidence_survives_roster_rotation_in_same_snapshot():
    state = {"stats": {"测试刀": {"生存": 55, "侦察": 39}},
             "stats_at": "2026-09-22 21:33:18"}
    table = {"测试刀": {"生存": 56, "侦察": 39}}
    record_cultivation_growth(state, table, _pool())
    state["stats"] = {"另一振": {"生存": 60, "侦察": 40}}
    pairs = cultivation_pairs(state, 1789992100, 24)
    assert pairs["oid:24:1"] == table["测试刀"]
    assert "测试刀" not in pairs
    assert "oid:24:1" not in cultivation_pairs(state, 1789992100, 25)


def test_same_name_same_old_pair_never_gets_growth_assigned():
    state = {"stats": {"测试刀": {"生存": 55, "侦察": 39}}}
    record_cultivation_growth(state,
                              {"测试刀": {"生存": 56, "侦察": 39}},
                              _pool(second_pair=(55, 39)))
    assert state["cultivation_evidence"] == {}


def test_missing_or_jumping_values_are_not_growth_evidence():
    state = {"stats": {"测试刀": {"生存": 55, "侦察": 39}}}
    record_cultivation_growth(state,
                              {"测试刀": {"生存": 57, "侦察": 39}}, _pool())
    assert state["cultivation_evidence"] == {}
    assert cultivation_pairs({"stats": {"测试刀": {"生存": 55,
                                                     "侦察": 39}}},
                             1789992100, 24) == {}
