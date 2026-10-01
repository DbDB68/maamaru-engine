import json

from touken.sword_receipts import build_receipts, write_receipts
from touken.telemetry import TelemetryStore


def event(endpoint, payload, second=0, direction="S->C", status=200):
    return {"endpoint": endpoint, "payload": payload, "direction": direction,
            "ts": f"2026-10-01 12:00:{second:02d}", "status": status}


def forge(second=0):
    return [event("/forge/completemultiple", {"slot_no": "1"}, second, "C->S"),
            event("/forge/completemultiple", {
                "finish_count": 2, "sword": [
                    {"sword_id": 99, "serial_id": n} for n in range(1, 11)]}, second)]


def test_batch_preserves_ten_instances_and_ignores_remaining_slots():
    receipt = build_receipts(forge())[0]
    assert receipt["payload"]["count"] == 10
    assert len({s["serial_id"] for s in receipt["payload"]["swords"]}) == 10
    assert receipt["payload"]["slot"] == 1


def test_drops_use_route_and_no_party_member_serial():
    events = [event("/sally/sally", {"episode_id": "8", "field_id": "2", "party_no": "4"}, direction="C->S"),
              event("/sally/sally", {}), event("/sally/forward", {"square_id": 17}),
              event("/battle/battle", {"result": {"get_sword_id": "81", "player": {"serial_id": 123}}}),
              event("/battle/battle", {"result": {"get_sword_id": 0}})]
    receipt, = build_receipts(events)
    p = receipt["payload"]
    assert (p["chapter"], p["map_no"], p["team_no"], p["square_id"]) == (8, 2, 4, 17)
    assert p["name"] == "宗三左文字"
    assert "serial_id" not in p
    events += [event("/sally/eventsally", {}, direction="C->S"), events[3]]
    assert "chapter" not in build_receipts(events)[-1]["payload"]


def test_failed_and_non_drop_responses_are_ignored():
    assert build_receipts([event("/forge/completemultiple", forge()[1]["payload"], status=500),
                           event("/battle/battle", {"status": 1, "result": {"get_sword_id": 99}})]) == []


def test_raid_drop_does_not_reuse_normal_map():
    receipt, = build_receipts([event("/battle/alloutbattle", {"result": {"get_sword_id": 99}})])
    assert receipt["payload"]["source"] == "raid.drop"
    assert "chapter" not in receipt["payload"]


def test_idempotence_and_ocr_upgrade_preserve_run(tmp_path):
    store = TelemetryStore(tmp_path / "events.db")
    receipts = build_receipts(forge())
    conn = store._conn()
    conn.execute("INSERT INTO events(ts,run_id,script,event_type,payload) VALUES (?,NULL,'forge','forge.collected',?)",
                 (receipts[0]["ts"] + 3, json.dumps({"slot": 1, "name": "堀川国广", "duration": "01:30"})))
    conn.commit()
    assert write_receipts(store, receipts) == {"written": 0, "reconciled": 1}
    assert write_receipts(store, receipts) == {"written": 0, "reconciled": 0}
    row = store.recent_events()[0]
    assert row["payload"]["count"] == 10
    assert row["payload"]["ocr_evidence"]["duration"] == "01:30"
    assert row["payload"]["execution_script"] == "forge"
    # 名册翻译调整不改变一笔游戏领取的身份。
    receipts[0]["payload"]["swords"][0]["name"] = "更新的译名"
    assert write_receipts(store, receipts) == {"written": 0, "reconciled": 0}


def test_two_nearby_same_swords_are_not_collapsed(tmp_path):
    store = TelemetryStore(tmp_path / "events.db")
    receipts = build_receipts([event("/battle/battle", {"result": {"get_sword_id": 99}}, second=n) for n in (1, 30)])
    assert write_receipts(store, receipts)["written"] == 2
    assert write_receipts(store, receipts)["written"] == 0
    assert len(store.recent_events()) == 2
