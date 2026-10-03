from touken.client_equipment import name_client_assets


def test_confirmed_names_preserve_instances_and_original_observation():
    original = {"equip": [
        {"serial_id": "first", "equip_id": "30", "soldier": 10},
        {"serial_id": "second", "equip_id": 30, "soldier": 8},
        {"serial_id": "unknown", "equip_id": 130},
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
                "artifact": [{"artifact_id": 999}], "sword": [{"item_id": 3155}]}
    assert name_client_assets(original) == original
