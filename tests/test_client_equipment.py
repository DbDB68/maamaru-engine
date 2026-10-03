import pytest

from touken.client_equipment import name_client_assets


def test_confirmed_names_preserve_instances_and_original_observation():
    original = {"equip": [
        {"serial_id": "first", "equip_id": "30", "soldier": 10},
        {"serial_id": "second", "equip_id": 30, "soldier": 8},
        {"serial_id": "unknown", "equip_id": 999},
    ], "sword": [{"serial_id": "s", "item_id": "1"}], "observed_at": 123}
    named = name_client_assets(original)
    assert [row.get("name") for row in named["equip"]] == ["铳兵·特上", "铳兵·特上", None]
    assert [row["serial_id"] for row in named["equip"]] == ["first", "second", "unknown"]
    assert named["equip"][1]["soldier"] == 8
    assert named["sword"][0]["charm_name"] == "御守"
    assert named["observed_at"] == 123
    assert "name" not in original["equip"][0]
    assert "charm_name" not in original["sword"][0]


def test_unknown_and_missing_ids_are_not_named():
    original = {"equip": [{"equip_id": True}, {"serial_id": "missing"}],
                "artifact": [{"artifact_id": 999}], "sword": [{"item_id": 999}]}
    assert name_client_assets(original) == original


@pytest.mark.parametrize("identifier,name,kind", [
    (3, "投石兵·特上", "troop"), (6, "枪兵·特上", "troop"),
    (9, "轻步兵·特上", "troop"), (12, "重步兵·特上", "troop"),
    (15, "盾兵·特上", "troop"), (18, "轻骑兵·特上", "troop"),
    (21, "重骑兵·特上", "troop"), (24, "精锐兵·特上", "troop"),
    (27, "弓兵·特上", "troop"), (30, "铳兵·特上", "troop"),
    (34, "水炮兵·中", "troop"), (35, "水炮兵·上", "troop"),
    (36, "水炮兵·特上", "troop"), (109, "轻步兵·新春", "troop"),
    (118, "轻骑兵·新春", "troop"),
    (130, "铳兵·新春", "troop"),
    (10001, "01王庭", "horse"), (10008, "08望月", "horse"),
    (11011, "白毛", "horse"), (11021, "鹿毛", "horse"), (11031, "青毛", "horse"),
])
def test_player_calibrated_names(identifier, name, kind):
    row = name_client_assets({"equip": [{"equip_id": str(identifier)}]})["equip"][0]
    assert (row["name"], row["kind"]) == (name, kind)


def test_unconfirmed_grade_and_special_horse_are_not_inferred():
    original = {"equip": [{"equip_id": n} for n in (1, 2, 11050)]}
    assert name_client_assets(original) == original


def test_horses_calibrated_by_nine_successive_equipment_changes():
    names = ["祝九号", "祝八号", "祝七号", "祝六号", "祝五号", "祝四号", "祝三号", "祝二号", "祝一号"]
    rows = name_client_assets({"equip": [{"equip_id": n} for n in range(11049, 11040, -1)],
                               "sword": [{"item_id": 3155}]})
    assert [r["name"] for r in rows["equip"]] == names
    assert all(r["kind"] == "horse" for r in rows["equip"])
    assert rows["sword"][0]["charm_name"] == "御守·桃"
