from touken.inbox_receipts import build_inbox_receipts
from touken.sword_receipts import sync_receipts
from touken.game_sword_archive import candidate_pool, sync_archive
from touken.telemetry import TelemetryStore


def event(endpoint, payload):
    return dict(endpoint=endpoint, direction="S->C", status=200,
                ts="2026-10-01 12:00:00", payload={"status": 0, **payload})


def mail(**overrides):
    return dict(serial_id="100", item_type="2", item_id="228", item_num="1",
                created_at="2026-09-10 10:22:44", received_at="2026-09-20 21:31:15",
                message="已收到时之政府发放的任务奖励。", **overrides)


def test_history_links_only_exact_unique_instance(tmp_path):
    sword = dict(serial_id=999, sword_id=228, created_at="2026-09-20 21:31:15")
    events = [event("/receive/list", {"history": {"100": mail()}}),
              event("/party/list", {"sword": {"999": sword}})]
    receipt, = build_inbox_receipts(events)
    assert receipt["payload"]["swords"][0]["serial_id"] == 999
    assert receipt["payload"]["origin_label"] == "任务奖励"
    store = TelemetryStore(tmp_path / "telemetry.db")
    assert sync_receipts(events, store)["written"] == 1
    assert sync_receipts(events, store)["written"] == 0
    assert candidate_pool(store)["entries"][0]["acquisition"]["label"] == "任务奖励"
    sync_archive([event("/party/list", {"sword": {"999": sword}})], store)
    assert candidate_pool(store)["entries"][0]["acquisition"]["mailbox_id"] == "100"
    # 同名旧刀、同一秒出现两振，均不能瞎认。
    for rows in ({"999": {**sword, "created_at": "2017-11-12 00:00:00"}},
                 {"999": sword, "998": {**sword, "serial_id": 998}}):
        events[-1] = event("/party/list", {"sword": rows})
        assert build_inbox_receipts(events)[0]["payload"]["swords"][0]["serial_id"] is None


def test_pending_non_swords_and_full_claim_inventory_are_not_acquisitions():
    pending = mail()
    pending.pop("received_at")
    rows = {str(i): {"serial_id": i, "sword_id": 228} for i in range(1, 147)}
    events = [event("/receive/list", {"receive": {"100": pending}}),
              event("/receive/get", {"serial_ids": ["other-mail"], "sword": rows})]
    assert build_inbox_receipts(events) == []
    events[-1]["payload"]["serial_ids"] = ["100"]
    assert len(build_inbox_receipts(events)[0]["payload"]["swords"]) == 1
    events[-1]["payload"]["status"] = 1
    assert build_inbox_receipts(events) == []
    pending["item_type"] = "1"
    pending["received_at"] = "2026-09-20 21:31:15"
    assert build_inbox_receipts(events) == []
