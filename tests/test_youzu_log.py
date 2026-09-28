# -*- coding: utf-8 -*-
"""youzu_log：国服 HttpRequestCollect 日志解析测试（全部合成数据）"""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from touken import youzu_log


def _c2s(ts, method, url, data=""):
    return f"【{ts}】【C->S】[{method}] {url} Data:[{data}]"


def _s2c(ts, url, payload):
    return (f"【{ts}】【S->C】{url} readyState:4 status:200 "
            f"data:{json.dumps(payload, ensure_ascii=False)}")


SAMPLE = "\n".join([
    _c2s("2026-09-28 11:34:37", "GET",
         "https://mp-djlw.youzu.com/enter",
         "op_id=2106&opgame_id=2297"),
    _s2c("2026-09-28 11:34:38", "https://s39-ios-djlw.youzu.com/login/start?uid=1",
         {"user_id": 1, "name": "测试婶", "level": "290", "exp": "100",
          "server_name": "备前国", "created_at": "2017-06-03 22:50:37",
          "secretary": "119", "status": 0, "t": "x" * 128}),
    _s2c("2026-09-28 11:34:39", "https://s39-ios-djlw.youzu.com/home?uid=1",
         {"resource": {"charcoal": 100, "steel": 200, "coolant": 300,
                       "file": 400, "bill": 5},
          "currency": {"money": "999"},
          "duty": {"type": "3"}, "season_id": "25",
          "season_end_at": "2026-12-17 10:00:00",
          "status": 0, "now": "2026-09-28 11:34:39"}),
    _s2c("2026-09-28 11:34:40", "https://s39-ios-djlw.youzu.com/party/list?uid=1",
         {"sword": {"111": {"serial_id": "111", "sword_id": "118",
                            "rarity": "2", "level": "99", "hp": "45",
                            "hp_max": "45", "fatigue": "100",
                            "evol_num": "0", "protect": "1"}},
          "party": {"1": {"party_no": "1", "status": "1",
                          "party_name": "主力",
                          "slot": {"1": {"serial_id": "111"},
                                   "2": {"serial_id": None}},
                          "finished_at": None}},
          "status": 0}),
    _s2c("2026-09-28 11:34:41", "https://s39-ios-djlw.youzu.com/home/situation?uid=1",
         {"party": {"1": {"status": "1", "equip_full": 1, "member_full": 1}},
          "repair": [], "forge": {"1": {"slot_no": "1",
                                        "finished_at": "2026-09-28 12:00:00"}},
          "status": 0}),
    # 后来的 /home 覆盖先前的（latest-wins）
    _s2c("2026-09-28 11:35:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
         {"resource": {"charcoal": 50, "steel": 60, "coolant": 70,
                       "file": 80, "bill": 6},
          "currency": {"money": "1000"}, "status": 0,
          "now": "2026-09-28 11:35:00"}),
    "这不是日志行，应该被计进坏行",
])


def test_parse_events(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    events = youzu_log.parse_events(f)
    meta = events[-1]["payload"]
    assert meta["bad_lines"] == 1
    assert meta["event_count"] == 6  # 6 条收发，META 条不计入

    c2s = events[0]
    assert c2s["direction"] == "C->S"
    assert c2s["method"] == "GET"
    assert c2s["endpoint"] == "/enter"
    assert c2s["payload"] == {"op_id": "2106", "opgame_id": "2297"}

    s2c = events[1]
    assert s2c["endpoint"] == "/login/start"
    assert s2c["payload"]["name"] == "测试婶"


def test_snapshot_latest_wins(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    snap = youzu_log.build_snapshot(youzu_log.parse_events(f))

    # 敏感字段一律不进快照（盗号两件套防御）
    assert "name" not in snap["profile"]
    assert "server_name" not in snap["profile"]
    assert "user_id" not in snap["profile"]
    assert snap["profile"]["level"] == 290
    # 后一条 /home 的资源覆盖前一条
    assert snap["resources"]["charcoal"] == 50
    assert snap["resources"]["koban"] == 1000

    assert snap["sword_count"] == 1
    party1 = snap["parties"][0]
    assert party1["party_name"] == "主力"
    assert party1["status"] == 1
    assert len(party1["members"]) == 1
    assert party1["members"][0]["serial_id"] == 111
    assert party1["members"][0]["level"] == 99

    assert snap["forge_slots"] == [
        {"slot_no": 1, "finished_at": "2026-09-28 12:00:00"}]
    assert snap["season"]["end_at"] == "2026-12-17 10:00:00"
    assert snap["server_time"] == "2026-09-28 11:35:00"


def test_snapshot_without_swords(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    snap = youzu_log.build_snapshot(youzu_log.parse_events(f),
                                    with_swords=False)
    assert "swords" not in snap
    assert snap["sword_count"] == 1


def test_home_situation_keeps_source_times_and_excludes_credentials(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    path = tmp_path / "state" / "youzu_home_situation.json"
    situation = youzu_log.save_home_situation(youzu_log.parse_events(f), path)
    saved = path.read_text(encoding="utf-8")
    assert situation["secretary"]["observed_at"] == "2026-09-28 11:34:38"
    assert situation["parties_observed_at"] == "2026-09-28 11:34:40"
    assert situation["parties"][0]["members"][0]["name"] == "压切长谷部"
    assert situation["forge_slots"][0]["finished_at"] == "2026-09-28 12:00:00"
    assert json.loads(saved) == situation
    for secret in ("测试婶", "user_id", "uid=1", '"t"', "serial_id"):
        assert secret not in saved


def test_empty_home_situation_preserves_previous_record(tmp_path):
    path = tmp_path / "youzu_home_situation.json"
    path.write_text('{"schema":1}', encoding="utf-8")
    assert youzu_log.save_home_situation([], path) is None
    assert path.read_text(encoding="utf-8") == '{"schema":1}'


def test_home_situation_api_refresh_uses_private_state_and_burns_log(tmp_path):
    from panel import server
    raw = tmp_path / "pulled.log"
    raw.write_text(SAMPLE, encoding="utf-8")
    config = tmp_path / "touken.json"
    config.write_text('{"adb_path":"adb","adb_address":"127.0.0.1:16384"}',
                      encoding="utf-8")
    with patch.object(server, "STATUS_DIR", tmp_path / "state"), \
         patch.object(server, "DEBUG_DIR", tmp_path / "debug"), \
         patch.object(server, "_CONFIG_PATH", config), \
         patch.object(youzu_log, "pull_log", return_value=raw) as pull:
        client = TestClient(server.app)
        assert client.get("/api/honmaru-home/situation").json() == {"situation": None}
        response = client.post("/api/honmaru-home/situation/refresh")
        assert response.status_code == 200
        assert response.json()["situation"]["parties"][0]["members"][0]["name"]
        assert not raw.exists()
        assert pull.call_args.kwargs["dest_dir"] == tmp_path / "debug"
        assert client.get("/api/honmaru-home/situation").json() == response.json()
        saved = tmp_path / "state" / "youzu_home_situation.json"
        saved.write_text('{"schema":2}', encoding="utf-8")
        assert client.get("/api/honmaru-home/situation").status_code == 503
        assert saved.read_text(encoding="utf-8") == '{"schema":2}'


def test_format_summary_runs(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    snap = youzu_log.build_snapshot(youzu_log.parse_events(f))
    text = youzu_log.format_summary(snap)
    assert "测试婶" not in text
    assert "第1部队" in text
    assert "Lv.290" in text


LEDGER_SAMPLE = "\n".join([
    _s2c("2026-09-28 11:00:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
         {"resource": {"charcoal": 1000, "steel": 2000, "coolant": 3000,
                       "file": 4000, "bill": 10},
          "currency": {"money": "500", "point": "100", "point_free": "50"},
          "status": 0, "now_time": 1790545200}),
    # 远征完成：收入木炭
    _c2s("2026-09-28 11:05:00", "POST",
         "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1", "party_no=2"),
    _s2c("2026-09-28 11:05:01",
         "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1",
         {"resource": {"charcoal": 1250, "steel": 2000, "coolant": 3000,
                       "file": 4000, "bill": 10},
          "currency": {"money": "500"}, "status": 0,
          "now_time": 1790545501}),
    # 锻刀开炉：四项资源 + 委托符一起扣
    _c2s("2026-09-28 11:06:00", "POST",
         "https://s39-ios-djlw.youzu.com/forge/startmultiple?uid=1", "slot_no=1"),
    _s2c("2026-09-28 11:06:01",
         "https://s39-ios-djlw.youzu.com/forge/startmultiple?uid=1",
         {"resource": {"charcoal": 550, "steel": 1300, "coolant": 2300,
                       "file": 3300, "bill": 9},
          "currency": {"money": "500"}, "status": 0,
          "now_time": 1790545561}),
    # keepalive 不带资源块，不该产生读数
    _s2c("2026-09-28 11:06:30", "https://s39-ios-djlw.youzu.com/keepalive?uid=1",
         {"status": 0, "now_time": 1790545590}),
])


def test_build_ledger(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(LEDGER_SAMPLE, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))

    # 三次带资源的响应 → 三条读数（keepalive 不算）
    assert len(ledger["observations"]) == 3
    # 首条读数含甲州金合并（100+50）与小判
    first = ledger["observations"][0]["reading"]
    assert first["甲州金"] == 150
    assert first["小判"] == 500
    assert first["委托符"] == 10

    assert len(ledger["changes"]) == 2
    c1, c2 = ledger["changes"]
    assert c1["delta"] == {"木炭": 250}
    assert c1["via"] == ["远征完成"]
    assert c2["delta"] == {"木炭": -700, "玉钢": -700, "冷却材": -700,
                           "砥石": -700, "委托符": -1}
    assert c2["via"] == ["锻刀开炉"]
    # 时间戳用的是响应体里的服务器 now_time
    assert c1["ts"] == 1790545501


def test_ledger_attribution_prefers_labeled_endpoints(tmp_path):
    """轮询请求和动作请求夹在一起时，只归因给已知动作端点。"""
    sample = "\n".join([
        _s2c("2026-09-28 13:00:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
             {"resource": {"charcoal": 100, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "status": 0, "now_time": 1790542800}),
        _c2s("2026-09-28 13:01:00", "GET",
             "https://s39-ios-djlw.youzu.com/home/info?uid=1", ""),
        _c2s("2026-09-28 13:01:01", "POST",
             "https://s39-ios-djlw.youzu.com/mission/rewards?uid=1", "id=1"),
        _s2c("2026-09-28 13:01:02",
             "https://s39-ios-djlw.youzu.com/mission/rewards?uid=1",
             {"resource": {"charcoal": 500, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "status": 0, "now_time": 1790542862}),
    ])
    f = tmp_path / "log.txt"
    f.write_text(sample, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))
    assert ledger["changes"][0]["via"] == ["任务奖励"]
    # via_endpoints 保留全部原始请求留证
    assert ledger["changes"][0]["via_endpoints"] == ["/home/info",
                                                     "/mission/rewards"]


def test_format_ledger_runs(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(LEDGER_SAMPLE, encoding="utf-8")
    text = youzu_log.format_ledger(
        youzu_log.build_ledger(youzu_log.parse_events(f)))
    assert "远征完成" in text
    assert "木炭+250" in text
    assert "2 笔收支" in text


def test_conquest_complete_gets_detailed_label(tmp_path):
    """远征完成的响应自带 party_no/field_id，归因要细分到队和图。

    complete 响应顶层的 field_id 是连排口径（B1=5，2026-09-28 实测）。
    """
    sample = "\n".join([
        _s2c("2026-09-28 12:00:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
             {"resource": {"charcoal": 100, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "status": 0, "now_time": 1790546400}),
        _c2s("2026-09-28 12:37:47", "POST",
             "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1",
             "party_no=4"),
        _s2c("2026-09-28 12:37:48",
             "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1",
             {"success": 2, "field_id": "5", "party_no": "4",
              "conquest": {"field_id": "21"},
              "resource": {"charcoal": 235, "steel": 0, "coolant": 135,
                           "file": 135, "bill": 0},
              "status": 0, "now_time": 1790548668}),
    ])
    f = tmp_path / "log.txt"
    f.write_text(sample, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))
    label = ledger["changes"][0]["via"][0]
    assert label.startswith("远征完成·四队·B1"), label


def test_conquest_start_label_from_request(tmp_path):
    """start 的响应不带 party_no/field_id，细分标签要从请求原文拿。"""
    sample = "\n".join([
        _s2c("2026-09-28 12:00:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
             {"resource": {"charcoal": 100, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "status": 0, "now_time": 1790546400}),
        _c2s("2026-09-28 12:10:00", "POST",
             "https://s39-ios-djlw.youzu.com/conquest/start?uid=1",
             "consumable_id=0&field_id=1&party_no=1"),
        _s2c("2026-09-28 12:10:01",
             "https://s39-ios-djlw.youzu.com/conquest/start?uid=1",
             {"summary": {"1": {"party_no": "1", "field_id": "1"}},
              "resource": {"charcoal": 50, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "status": 0, "now_time": 1790547001}),
    ])
    f = tmp_path / "log.txt"
    f.write_text(sample, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))
    label = ledger["changes"][0]["via"][0]
    assert label.startswith("远征派遣·一队·A1"), label


def test_conquest_complete_koban_reward(tmp_path):
    """complete 的小判走 reward 数组（响应没有 currency 块）：按原文记
    一笔并推高水位线，后续轮询读到新余额时不许再报一次。"""
    sample = "\n".join([
        _s2c("2026-09-28 12:00:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
             {"resource": {"charcoal": 100, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "currency": {"money": "570"},
              "status": 0, "now_time": 1790546400}),
        _c2s("2026-09-28 12:37:47", "POST",
             "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1",
             "party_no=4"),
        _s2c("2026-09-28 12:37:48",
             "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1",
             {"success": 2, "field_id": "5", "party_no": "4",
              "resource": {"charcoal": 100, "steel": 0, "coolant": 135,
                           "file": 135, "bill": 0},
              "reward": [{"item_type": "4", "item_id": "0", "item_num": 200},
                         {"item_type": "5", "item_id": "4", "item_num": 135},
                         {"item_type": "5", "item_id": "5", "item_num": 135}],
              "status": 0, "now_time": 1790548668}),
        # 之后某个轮询端点带回新的小判余额 770：不许再报 +200
        _s2c("2026-09-28 12:38:10", "https://s39-ios-djlw.youzu.com/party/list?uid=1",
             {"resource": {"charcoal": 100, "steel": 0, "coolant": 135,
                           "file": 135, "bill": 0},
              "currency": {"money": "770"},
              "status": 0, "now_time": 1790548690}),
    ])
    f = tmp_path / "log.txt"
    f.write_text(sample, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))

    koban_changes = [c for c in ledger["changes"] if "小判" in c["delta"]]
    assert len(koban_changes) == 1
    ch = koban_changes[0]
    assert ch["delta"] == {"小判": 200}
    assert ch["before"] == {"小判": 570}
    assert ch["after"] == {"小判": 770}
    assert ch["via"][0].startswith("远征完成·四队·B1")
    # 资源差值照常走 resource 块，不受影响
    res = [c for c in ledger["changes"] if "冷却材" in c["delta"]]
    assert res and res[0]["delta"] == {"冷却材": 135, "砥石": 135}


def test_mission_rewards_koban_from_item_list(tmp_path):
    """mission/rewards 的小判在 item 数组里（item_type=4），响应没有
    currency 块——要按原文记账，不许拖到下一次轮询才爆出来。"""
    sample = "\n".join([
        _s2c("2026-09-28 13:00:00", "https://s39-ios-djlw.youzu.com/sign?uid=1",
             {"resource": {"charcoal": 0, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "currency": {"money": "1000"}, "status": 0,
              "now_time": 1790542800}),
        _c2s("2026-09-28 13:03:04", "POST",
             "https://s39-ios-djlw.youzu.com/mission/rewards?uid=1", "id=1"),
        _s2c("2026-09-28 13:03:06",
             "https://s39-ios-djlw.youzu.com/mission/rewards?uid=1",
             {"item": [{"item_type": 5, "item_id": 2, "item_num": 400},
                       {"item_type": 4, "item_id": 0, "item_num": 250}],
              "resource": {"charcoal": 400, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "status": 0, "now_time": 1790542986}),
        # 两个钟头后的轮询带回新余额：不许再报 +250
        _s2c("2026-09-28 15:00:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
             {"currency": {"money": "1250"}, "status": 0,
              "now_time": 1790550000}),
    ])
    f = tmp_path / "log.txt"
    f.write_text(sample, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))

    koban = [c for c in ledger["changes"] if "小判" in c["delta"]]
    assert len(koban) == 1
    assert koban[0]["delta"] == {"小判": 250}
    assert koban[0]["before"] == {"小判": 1000}
    assert koban[0]["after"] == {"小判": 1250}
    assert koban[0]["via"] == ["任务奖励"]
    # item 里的资源条目不重复计（resource 块差值已覆盖）
    res = [c for c in ledger["changes"] if "木炭" in c["delta"]]
    assert len(res) == 1 and res[0]["delta"] == {"木炭": 400}


def test_reading_event_points_and_consumables():
    """活动点数（point 块）和道具库存（item 为 dict）都进读数。"""
    reading = youzu_log._reading_from_payload({
        "resource": {"charcoal": 100},
        "point": {"10031": 20496},
        "item": {"1_0": {"consumable_id": "1", "num": "32"},
                 "8_0": {"consumable_id": "8", "num": "388"},
                 "6103_0": {"consumable_id": "6103", "num": "2"}},
    })
    assert reading["活动点数·10031"] == 20496
    # ITEM_NAMES 已校准的用真名（2026-09-28 CU 道具页逐页对上）
    assert reading["御守"] == 32
    assert reading["加速符·极"] == 388
    # 没校准的平局组保持「道具#N」，不硬猜
    assert reading["道具#6103"] == 2


def test_item_list_is_not_a_reading():
    """mission/rewards 的 item 是 list（奖励清单），不是库存读数。"""
    reading = youzu_log._reading_from_payload({
        "item": [{"item_type": 4, "item_id": 0, "item_num": 250}],
    })
    assert reading is None or not any(k.startswith("道具#") for k in reading)


def test_event_points_delta_attribution(tmp_path):
    """活动点数差值走同一条归因链：归给夹在中间的出阵请求。"""
    sample = "\n".join([
        _s2c("2026-09-28 20:00:00", "https://s39-ios-djlw.youzu.com/sally?uid=1",
             {"point": {"10031": 20000}, "status": 0,
              "now_time": 1790568000}),
        _c2s("2026-09-28 20:10:00", "POST",
             "https://s39-ios-djlw.youzu.com/sally/start?uid=1", "field_id=1"),
        _s2c("2026-09-28 20:10:30", "https://s39-ios-djlw.youzu.com/sally?uid=1",
             {"point": {"10031": 20496}, "status": 0,
              "now_time": 1790568630}),
    ])
    f = tmp_path / "log.txt"
    f.write_text(sample, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))
    ch = [c for c in ledger["changes"] if "活动点数·10031" in c["delta"]]
    assert len(ch) == 1
    assert ch[0]["delta"] == {"活动点数·10031": 496}
    assert ch[0]["via"] == ["sally/start"]  # 未收录端点，老实报原名


def test_conquest_complete_exp_ledger(tmp_path):
    """远征完成记两笔经验：审神者（before/after 可反推）+ 刀剑合计。"""
    sample = "\n".join([
        _s2c("2026-09-28 12:00:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
             {"resource": {"charcoal": 100, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "status": 0, "now_time": 1790546400}),
        _c2s("2026-09-28 12:37:47", "POST",
             "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1",
             "party_no=4"),
        _s2c("2026-09-28 12:37:48",
             "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1",
             {"success": 2, "field_id": "5", "party_no": "4",
              "result": {"user_exp": 110, "exp": 41589884, "level": 290},
              "sword": {"1": {"serial_id": "1", "get_exp": 285},
                        "2": {"serial_id": "2", "get_exp": 285}},
              "resource": {"charcoal": 100, "steel": 0, "coolant": 0,
                           "file": 0, "bill": 0},
              "status": 0, "now_time": 1790548668}),
    ])
    f = tmp_path / "log.txt"
    f.write_text(sample, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))
    user = [c for c in ledger["changes"] if "审神者经验" in c["delta"]]
    sword = [c for c in ledger["changes"] if "刀剑经验" in c["delta"]]
    assert len(user) == 1 and user[0]["delta"] == {"审神者经验": 110}
    assert user[0]["before"] == {"审神者经验": 41589774}
    assert user[0]["after"] == {"审神者经验": 41589884}
    assert user[0]["via"][0].startswith("远征完成·四队·B1")
    assert len(sword) == 1 and sword[0]["delta"] == {"刀剑经验": 570}


def test_snapshot_missions_kiwame_events(tmp_path):
    """快照带任务进度、修行归来倒计时、活动日历。"""
    sample = "\n".join([
        _s2c("2026-09-28 11:34:38", "https://s39-ios-djlw.youzu.com/login/start?uid=1",
             {"user_id": 1, "level": "290", "status": 0}),
        _s2c("2026-09-28 11:34:40", "https://s39-ios-djlw.youzu.com/party/list?uid=1",
             {"sword": {"111": {"serial_id": "111", "sword_id": "118",
                                "level": "99"}},
              "party": {}, "status": 0}),
        _s2c("2026-09-28 11:34:45", "https://s39-ios-djlw.youzu.com/home/leave?uid=1",
             {"evolution": {"back": {"0": {"serial_id": 111,
                                           "finished_at": "2026-10-02 11:34:55"}}},
              "status": 0}),
        _s2c("2026-09-28 11:34:46",
             "https://s39-ios-djlw.youzu.com/home/get_all_activity?uid=1",
             {"event": {"0": {"type": 4, "event_id": 14030,
                              "start_at": "2026-09-24 10:00:00",
                              "end_at": "2026-10-15 05:00:00"}},
              "status": 0}),
        _s2c("2026-09-28 13:03:04", "https://s39-ios-djlw.youzu.com/mission/index?uid=1",
             {"mission": {"1": {"mission_id": "1", "value": "2", "status": "3"},
                          "4375": {"mission_id": "4375", "value": "0",
                                   "status": "1"}},
              "status": 0}),
    ])
    f = tmp_path / "log.txt"
    f.write_text(sample, encoding="utf-8")
    snap = youzu_log.build_snapshot(youzu_log.parse_events(f))
    assert snap["missions"] == [
        {"mission_id": 1, "value": 2, "status": 3},
        {"mission_id": 4375, "value": 0, "status": 1}]
    assert snap["kiwame_return"] == [
        {"serial_id": 111, "name": "压切长谷部",
         "finished_at": "2026-10-02 11:34:55"}]
    assert snap["events_calendar"] == [
        {"event_id": 14030, "type": 4,
         "start_at": "2026-09-24 10:00:00", "end_at": "2026-10-15 05:00:00"}]
    # 展示层：修行倒计时和活动日历进文本摘要
    text = youzu_log.format_summary(snap)
    assert "修行中：压切长谷部" in text
    assert "活动 14030" in text


def test_expedition_map_label_fallback():
    # sequential 连排口径（真实报文唯一在用的）：1=A1、5=B1、20=E4
    assert youzu_log._expedition_map_label("1").startswith("A1")
    assert youzu_log._expedition_map_label("5").startswith("B1")
    assert youzu_log._expedition_map_label("20").startswith("E4")
    # 连排口径下 21 超出 E4=20，宁可显示原值也不硬猜
    assert youzu_log._expedition_map_label("21") == "field#21"
    # era_slot 口径仅用于解读那个恒为 21 的 conquest 粘性子对象
    assert youzu_log._expedition_map_label("21", scheme="era_slot") \
        .startswith("B1")
    # 妖魔鬼怪的 field_id 不硬猜，老实显示原值
    assert youzu_log._expedition_map_label("99") == "field#99"


def test_write_ledger_idempotent(tmp_path):
    from touken.telemetry import TelemetryStore
    f = tmp_path / "log.txt"
    f.write_text(LEDGER_SAMPLE, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))

    store = TelemetryStore(tmp_path / "telemetry.db")
    state = tmp_path / "state.json"
    r1 = youzu_log.write_ledger(store, ledger, state_path=state)
    assert r1["observations_written"] == 3
    # 远征 +1 资源、锻刀 -5 资源 → 6 条 resource.change
    assert r1["changes_written"] == 6

    # 同一份账本再写一遍：全部跳过
    r2 = youzu_log.write_ledger(store, ledger, state_path=state)
    assert r2["observations_written"] == 0
    assert r2["changes_written"] == 0

    # 账房聚合视角：归因都在，且是 confirmed
    agg = store.resource_ledger(0, 2_000_000_000)
    labels = [a["label"] for a in agg["attributions"]]
    assert any("远征完成" in x and "木炭" in x for x in labels)
    assert any("锻刀开炉" in x and "委托符" in x for x in labels)
    assert all(a["confidence"] == "confirmed" for a in agg["attributions"])
