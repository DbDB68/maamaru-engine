import json

from touken.telemetry import TelemetryStore


def test_stock_uses_latest_actual_client_count_without_window_or_manual_override(tmp_path):
    store = TelemetryStore(tmp_path / "stock.db")
    for ts, script, resources in [(10, "youzu_log", {"小判": 100, "木炭": 25}),
                                  (20, "youzu_log", {"小判": 0}),
                                  (30, "manual", {"小判": 999})]:
        store._conn().execute("INSERT INTO events(ts,script,event_type,payload) VALUES(?,?,'inventory.captured',?)",
                              (ts, script, json.dumps({"resources": resources})))
    store._conn().commit()
    stock = store.client_item_inventory(10000000)
    assert stock["resources"] == {"小判": {"count": 0, "observed_at": 20},
                                   "木炭": {"count": 25, "observed_at": 10}}
    assert "玉钢" not in stock["resources"]
    assert store.client_item_inventory(15)["resources"]["小判"]["count"] == 100
    store.close()
