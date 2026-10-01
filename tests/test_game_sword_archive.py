from touken.game_sword_archive import archive_path, candidate_pool, read_archive, sync_archive, update_archive
from touken.honmaru_profile import build_candidate_pool
from touken.sword_archive import build_sword_archive
from touken.telemetry import TelemetryStore


def event(endpoint, payload, minute=0, status=0):
    return {"direction": "S->C", "endpoint": endpoint, "status": 200,
            "ts": f"2026-10-01 12:{minute:02d}:00", "payload": {**payload, "status": status}}


def sword(serial, sid=3, level=10):
    return {"serial_id": serial, "sword_id": sid, "level": level, "hp": 30, "hp_max": 60,
            "fatigue": 55, "protect": 1, "created_at": "2023-01-27 17:19:10", "ranbu_level": 2,
            "atk": 40, "equip_serial_id1": 500, "session": "never-store-this"}


def full(*rows, minute=0):
    return event("/party/list", {"sword": {str(r["serial_id"]): r for r in rows}}, minute)


def test_partial_only_never_creates_inventory_or_removes_members():
    partial = event("/sally", {"sword_all": {"1": sword(1, level=99)}}, 1)
    assert update_archive([partial]) is None
    state = update_archive([full(sword(1), sword(2)), partial])
    assert len(state["swords"]) == 2
    assert state["swords"]["1"]["level"] == 99
    assert state["swords"]["2"]["level"] == 10
    unknown = event("/sally", {"sword_all": {"9": sword(9)}}, 2)
    assert update_archive([unknown], state) == state


def test_battle_updates_exact_serial_and_old_log_cannot_revert():
    battle = event("/battle/battle", {"result": {"player": {"party": {"slot": {
        "1": {"serial_id": 2, "sword_id": 3, "hp": 20, "hp_max": 60, "fatigue": 40, "level": 11}}}}}}, 2)
    state = update_archive([full(sword(1), sword(2)), battle])
    assert state["swords"]["2"]["hp"] == 20
    assert state["swords"]["1"]["hp"] == 30
    assert state["swords"]["2"]["created_at"] == "2023-01-27 17:19:10"
    assert update_archive([full(sword(1), sword(2))], state) == state
    # 新完整名单确认少了一振，后续旧的局部记录不能把它复活。
    newer = update_archive([full(sword(1), minute=3), battle], state)
    assert set(newer["swords"]) == {"1"}


def test_bad_or_failed_full_response_preserves_good_snapshot():
    state = update_archive([full(sword(1))])
    invalid = full(sword(1), minute=2)
    invalid["payload"]["sword"]["broken"] = {"serial_id": 1, "sword_id": 3}
    assert update_archive([invalid, event("/party/list", {"sword": {}}, 3, status=1)], state) == state


def test_persistence_backup_idempotence_and_credentials_are_excluded(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    assert sync_archive([full(sword(1))], store)
    old = archive_path(store).read_bytes()
    assert b"never-store-this" not in old
    assert not sync_archive([full(sword(1))], store)
    assert sync_archive([full(sword(1, level=20), minute=2)], store)
    assert archive_path(store).with_suffix(".json.bak").read_bytes() == old
    # 回滚只读旧快照，原 OCR 数据与标注均无迁移/覆盖。
    archive_path(store).write_bytes(old)
    assert candidate_pool(store)["entries"][0]["level"] == 10


def test_migration_fallback_and_manual_annotations_survive(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    catalog = "touken_003_mikazuki_munechika"
    snapshot = store.save_sword_snapshot([
        {"sword_id": catalog, "name_zh": "三日月宗近", "level": 10, "page_no": 1,
         "kiwame_date": "2023-1-27"}], owned=1, capacity=300, missing=0,
        captured_at=1, source="owned_inventory")
    store.save_sword_annotation(catalog, "2023-1-27", favorite=True, note="保留这振")
    assert build_candidate_pool(store)["source"]["snapshot_id"] == snapshot
    sync_archive([full(sword(1, sid=4, level=95))], store)
    archive = build_sword_archive(store)
    entry = archive["entries"][0]
    assert archive["data_source"] == "youzu_log"
    assert entry["form_status"] == "kiwame"
    assert entry["human"]["favorite"] and entry["human"]["note"] == "保留这振"
    assert entry["level"] == 95 and entry["observation_id"] == "youzu:1"
    assert entry["kiwame_date"] == "2023-1-27"
    assert store.sword_snapshot_detail(snapshot)["swords"][0]["level"] == 10
    archive_path(store).write_text('{"schema":999}', encoding="utf-8")
    assert build_candidate_pool(store)["source"]["snapshot_id"] == snapshot


def test_same_name_same_day_instances_remain_distinct_and_annotations_ambiguous(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    sync_archive([full(sword(1), sword(2))], store)
    store.save_sword_annotation("touken_003_mikazuki_munechika", "2023-1-27", keeper=True)
    archive = build_sword_archive(store)
    assert len({e["observation_id"] for e in archive["entries"]}) == 2
    assert all(e["human"]["stale"] for e in archive["entries"])
    assert candidate_pool(store)["entries"][0]["equipment_serials"]["equip_serial_id1"] == 500


def test_genji_special_stages_are_not_kiwame(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    sync_archive([full(*(sword(sid, sid=sid) for sid in (108, 109, 110, 111, 113, 114, 115)))], store)
    entries = {e["serial_id"]: e for e in candidate_pool(store)["entries"]}
    assert entries[111]["name_zh"] == "髭切"
    assert entries[115]["name_zh"] == "膝丸"
    assert all(entries[sid]["form_status"] == "normal" for sid in (108, 109, 110, 113, 114))
    assert all(entries[sid]["form_status"] == "kiwame" for sid in (111, 115))


def test_serial_annotations_distinguish_same_day_and_never_follow_replacement(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    catalog = "touken_003_mikazuki_munechika"
    sync_archive([full(sword(1), sword(2))], store)
    first = store.save_sword_annotation(catalog, "2023-1-27", serial_id=1, keeper=True)
    second = store.save_sword_annotation(catalog, "2023-1-27", serial_id=2, watch=True)
    assert first["id"] != second["id"]
    entries = {e["serial_id"]: e for e in build_sword_archive(store)["entries"]}
    assert entries[1]["human"]["keeper"] and not entries[1]["human"]["watch"]
    assert entries[2]["human"]["watch"] and not entries[2]["human"]["keeper"]
    assert not entries[1]["human"]["stale"]
    sync_archive([full(sword(2), sword(3), minute=3)], store)
    archive = build_sword_archive(store)
    assert [a["annotation_id"] for a in archive["historical_annotations"]] == [first["id"]]
    assert next(e for e in archive["entries"] if e["serial_id"] == 3)["human"] is None


def test_unique_legacy_annotation_binds_once_and_survives_form_and_date_change(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    catalog = "touken_003_mikazuki_munechika"
    old = store.save_sword_annotation(catalog, "2023-1-27", favorite=True)
    sync_archive([full(sword(1))], store)
    build_sword_archive(store)
    assert store.sword_annotations()[0]["serial_id"] == 1
    changed = sword(1, sid=4)
    changed["created_at"] = "2023-01-28 00:00:00"
    sync_archive([full(changed, minute=3)], store)
    entry = build_sword_archive(store)["entries"][0]
    assert entry["human"]["id"] == old["id"] and entry["human"]["favorite"]


def test_game_sword_types_match_player_filters(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    sync_archive([full(sword(1, sid=99), sword(2, sid=65))], store)
    assert {e["sword_type"] for e in build_sword_archive(store)["entries"]} == {"胁差", "枪"}

