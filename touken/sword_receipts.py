"""客户端确认的锻刀领取与合战场掉落；不依赖 OCR 刀帐。"""
from __future__ import annotations

import hashlib
import json

from .youzu_log import _event_epoch, _int, _sword_name


def _receipt_key(ts, endpoint, payload):
    swords = payload.get("swords")
    identity = ([(s["sword_id"], s["serial_id"]) for s in swords]
                if isinstance(swords, list) else payload.get("sword_id"))
    raw = json.dumps([ts, endpoint, identity], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def build_receipts(events):
    from . import sword_db
    pending = {}
    route = {}
    square = None
    receipts = []
    for event in events:
        endpoint = event.get("endpoint") or ""
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if event.get("direction") == "C->S":
            pending[endpoint] = payload
            # 新出阵开始就清空，失败的请求也不能沿用上一张地图。
            if endpoint.startswith("/sally/") and endpoint not in (
                    "/sally/forward", "/sally/sally"):
                route, square = {}, None
            if endpoint == "/sally/sally":
                route, square = {}, None
            continue
        if (event.get("direction") != "S->C"
                or event.get("status") != 200
                or str(payload.get("status", 0)) != "0"):
            continue
        request = pending.pop(endpoint, {})
        ts = _event_epoch(event)
        if not ts:
            continue
        if endpoint == "/sally/sally":
            route = {"chapter": _int(request.get("episode_id")),
                     "map_no": _int(request.get("field_id")),
                     "team_no": _int(request.get("party_no"))}
        if endpoint == "/sally/forward":
            square = payload.get("square_id")
        if endpoint in ("/forge/completemultiple", "/forge/complete"):
            swords = payload.get("sword")
            if isinstance(swords, dict):
                swords = [swords]
            if not isinstance(swords, list):
                continue
            swords = [{"name": _sword_name(row["sword_id"], sword_db),
                       "sword_id": _int(row["sword_id"]),
                       "serial_id": _int(row.get("serial_id")),
                       "is_first_get_sword": bool(row.get("is_first_get_sword"))}
                      for row in swords if isinstance(row, dict)
                      and _int(row.get("sword_id")) > 0]
            if not swords:
                continue
            detail = {"source": "forge", "slot": _int(request.get("slot_no")),
                      "count": len(swords), "swords": swords}
            kind = "forge.collected"
        elif endpoint in ("/battle/battle", "/battle/alloutbattle"):
            result = payload.get("result") or {}
            if not isinstance(result, dict):
                continue
            sid = _int(result.get("get_sword_id"))
            if sid <= 0:
                continue
            normal = endpoint == "/battle/battle"
            source = ("sortie.drop" if route.get("chapter") and route.get("map_no")
                      else "battle.drop") if normal else "raid.drop"
            detail = {"name": _sword_name(sid, sword_db), "sword_id": sid,
                      "acquired_at": payload.get("now") or event["ts"],
                      "source": source, **(route if normal else {}),
                      "square_id": square if normal else None,
                      "is_first_get_sword": bool(result.get("is_first_get_sword"))}
            kind = "sword.obtained"
        else:
            continue
        key = _receipt_key(ts, endpoint, detail)
        detail.update(evidence_source="youzu_log", endpoint=endpoint,
                      receipt_key=key)
        receipts.append({"ts": ts, "event_type": kind, "payload": detail})
    from .inbox_receipts import build_inbox_receipts, link_receipt_serials, observed_swords
    swords = observed_swords(events)
    link_receipt_serials(receipts, swords)
    from .expedition_receipts import build_expedition_receipts
    return receipts + build_inbox_receipts(events, swords) + build_expedition_receipts(events)


def write_receipts(store, receipts):
    """独立于资源余额水位去重；唯一对应时补全原 OCR 记录并保留证据。"""
    if not receipts:
        return {"written": 0, "reconciled": 0}
    conn = store._conn()
    written = reconciled = 0
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id, ts, run_id, script, event_type, payload FROM events "
            "WHERE ts BETWEEN ? AND ? AND event_type IN "
            "('forge.collected', 'sword.obtained', 'sword.drop_unrecognized', 'sword.inbox_received', 'expedition.settled')",
            (min(r["ts"] for r in receipts) - 90,
             max(r["ts"] for r in receipts) + 90)).fetchall()
        existing = [dict(zip(("id", "ts", "run_id", "script", "event_type", "payload"), row))
                    for row in rows]
        for row in existing:
            row["payload"] = json.loads(row["payload"])
        keys = {r["payload"].get("receipt_key") for r in existing}
        keys.update(_receipt_key(r["ts"], r["payload"].get("endpoint"), r["payload"])
                    for r in existing if r["payload"].get("receipt_key"))

        def matches(receipt, row):
            p, old = receipt["payload"], row["payload"]
            if (row["script"] in ("manual", "youzu_log") or old.get("receipt_key")
                    or abs(receipt["ts"] - row["ts"]) > 90):
                return False
            if receipt["event_type"] == "forge.collected":
                return (row["event_type"] == "forge.collected"
                        and p.get("slot") == old.get("slot")
                        and (not old.get("name") or old["name"] in
                             [s["name"] for s in p["swords"]]))
            if receipt["event_type"] == "expedition.settled":
                return (row['event_type'] == 'expedition.settled'
                        and p['team_no'] == old.get('team_no')
                        and p['era'] == old.get('era') and p['slot'] == old.get('slot'))
            return (receipt["event_type"] == "sword.obtained" and p.get("source") == "sortie.drop"
                    and row["event_type"] in ("sword.obtained", "sword.drop_unrecognized")
                    and old.get("source") == "sortie.drop"
                    and (not old.get("name") or old["name"] == p["name"])
                    and all(not old.get(k) or str(old[k]) == str(p.get(k))
                            for k in ("chapter", "map_no")))

        for receipt in receipts:
            p = dict(receipt["payload"])
            if p["receipt_key"] in keys:
                continue
            candidates = [row for row in existing if matches(receipt, row)]
            if (len(candidates) == 1 and sum(matches(other, candidates[0])
                    for other in receipts) == 1):
                row = candidates[0]
                p.update(ocr_evidence=row["payload"], execution_script=row["script"])
                conn.execute("UPDATE events SET ts=?, script=?, event_type=?, payload=? WHERE id=?",
                             (receipt["ts"], "youzu_log", receipt["event_type"],
                              json.dumps(p, ensure_ascii=False), row["id"]))
                row["payload"] = p
                reconciled += 1
            else:
                conn.execute("INSERT INTO events(ts, run_id, script, event_type, payload) "
                             "VALUES (?, NULL, 'youzu_log', ?, ?)",
                             (receipt["ts"], receipt["event_type"],
                              json.dumps(p, ensure_ascii=False)))
                written += 1
            keys.add(p["receipt_key"])
    return {"written": written, "reconciled": reconciled}


def sync_receipts(events, store=None):
    if store is None:
        from .telemetry import TelemetryStore
        store = TelemetryStore()
    receipts = build_receipts(events)
    result = write_receipts(store, receipts)
    from .game_sword_archive import sync_archive
    sync_archive(events, store, receipts=receipts)
    return result
