"""收件箱刀剑：邮件编号定一笔领取，原始说明定来源，实例只按完整证据链接。"""
from datetime import datetime

from .youzu_log import _int, _sword_name


def sword_catalog(sid):
    from . import sword_db
    found = sword_db.find_game_sword(_int(sid))
    return found[0] if found else f"unknown:{sid}"


def observed_swords(events):
    swords = {}
    for event in events:
        p = event.get("payload")
        if (event.get("direction") == "S->C" and event.get("status") == 200
                and isinstance(p, dict) and str(p.get("status", 0)) == "0"
                and event.get("endpoint") in ("/party/list", "/receive/get")):
            for row in (p.get("sword") if isinstance(p.get("sword"), dict) else {}).values():
                if isinstance(row, dict) and _int(row.get("serial_id")) > 0:
                    swords[str(row["serial_id"])] = row
    return swords


def link_receipt_serials(receipts, swords):
    """战斗未给实例编号：只有刀种及完整获得秒数都唯一匹配时才补编号。"""
    for receipt in receipts:
        p = receipt["payload"]
        if receipt["event_type"] != "sword.obtained" or p.get("serial_id") or not p.get("acquired_at"):
            continue
        matches = [row for row in swords.values()
                   if sword_catalog(row.get("sword_id")) == sword_catalog(p.get("sword_id"))
                   and row.get("created_at") == p.get("acquired_at")]
        if len(matches) == 1:
            p["serial_id"] = _int(matches[0]["serial_id"])


def origin_label(message):
    text = str(message or "").strip()
    if text == "已收到时之政府发放的任务奖励。":
        return "任务奖励"
    if text == "【江户城潜入调查】宝箱报酬":
        return "江户城宝箱报酬"
    return text or "收件箱"


def build_inbox_receipts(events, swords=None):
    from . import sword_db
    swords = observed_swords(events) if swords is None else swords
    mails, claims = {}, {}
    for event in events:
        p = event.get("payload")
        if (event.get("direction") != "S->C" or event.get("status") != 200
                or not isinstance(p, dict) or str(p.get("status", 0)) != "0"):
            continue
        if event.get("endpoint") == "/receive/list":
            for section in ("receive", "history"):
                for row in (p.get(section) if isinstance(p.get(section), dict) else {}).values():
                    if isinstance(row, dict) and str(row.get("item_type")) == "2" and row.get("serial_id"):
                        key = str(row["serial_id"])
                        mails[key] = {**mails.get(key, {}), **row}
        if event.get("endpoint") == "/receive/get":
            # sword 是全所持名单，绝不能将其中每一振都算作这次新领取。
            for serial in p.get("serial_ids") or []:
                claims[str(serial)] = event.get("ts")
    receipts = []
    for mailbox_id, row in mails.items():
        received_at = row.get("received_at") or claims.get(mailbox_id)
        try:
            ts = datetime.strptime(received_at or "", "%Y-%m-%d %H:%M:%S").timestamp()
        except (ValueError, TypeError):
            continue  # 仍在收件箱的不记成已经领到。
        sid, count = _int(row.get("item_id")), _int(row.get("item_num"))
        if sid <= 0 or count <= 0:
            continue
        candidates = [s for s in swords.values()
                      if sword_catalog(s.get("sword_id")) == sword_catalog(sid)
                      and s.get("created_at") == received_at]
        serials = [_int(s["serial_id"]) for s in candidates] if len(candidates) == count else [None] * count
        name = _sword_name(sid, sword_db)
        if name.startswith("刀帐") and row.get("name"):
            name = row["name"]
        payload = {
            "source": "inbox.claim", "evidence_source": "youzu_log",
            "endpoint": "/receive/get", "receipt_key": f"inbox:{mailbox_id}",
            "mailbox_id": mailbox_id, "name": name, "sword_id": sid, "count": count,
            "origin_message": row.get("message") or "", "origin_reason": row.get("reason"),
            "origin_label": origin_label(row.get("message")),
            "inbox_at": row.get("created_at"), "received_at": received_at,
            "swords": [{"name": name, "sword_id": sid, "serial_id": serial} for serial in serials],
        }
        receipts.append({"ts": ts, "event_type": "sword.inbox_received", "payload": payload})
    return receipts
