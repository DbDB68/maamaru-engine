"""Game-log evidence for hiding settled departures; never edits dispatch records."""

import json
import math
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from touken import youzu_log
from touken.runtime_paths import STATUS_DIR

FILENAME = "youzu_expedition_observations.json"
SHANGHAI = timezone(timedelta(hours=8))
_PARTY_ENDPOINTS = {"/login/start", "/sally", "/party/list",
                    "/home/situation", "/conquest/complete"}
_WRITE_LOCK = threading.Lock()


def load_observations(path=None):
    try:
        data = json.loads(Path(path or STATUS_DIR / FILENAME).read_text(encoding="utf-8"))
        if data.get("schema") != 1 or not isinstance(data.get("teams"), dict):
            return {}
        return {team: proof for team, proof in data["teams"].items()
                if isinstance(proof, dict) and proof.get("kind") in {"standby", "collected"}
                and isinstance(proof.get("observed_at"), (int, float))
                and math.isfinite(proof["observed_at"])}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def save_observations(events, path=None):
    with _WRITE_LOCK:
        return _save_observations(events, path)


def _save_observations(events, path=None):
    path = Path(path or STATUS_DIR / FILENAME)
    teams = load_observations(path)
    changed = False

    def remember(team, at, kind, map_code=None):
        nonlocal changed
        if team not in range(1, 6):
            return
        key = str(team)
        previous = teams.get(key)
        if isinstance(previous, dict) and previous.get("observed_at", 0) >= at:
            return
        teams[key] = {"observed_at": at, "kind": kind, "map_code": map_code}
        changed = True

    for event in events:
        body = event.get("payload")
        if (event.get("direction") != "S->C" or event.get("status") != 200
                or not isinstance(body, dict) or str(body.get("status")) != "0"):
            continue
        at = youzu_log._event_epoch(event)
        if at is None:
            continue
        endpoint = event.get("endpoint")
        if endpoint == "/conquest/complete":
            team = youzu_log._int(body.get("party_no"))
            field = youzu_log._int(body.get("field_id"))
            if 1 <= field <= 20:
                code = f"{'ABCDE'[(field - 1) // 4]}{(field - 1) % 4 + 1}"
                remember(team, at, "collected", code)
        if endpoint in _PARTY_ENDPOINTS and isinstance(body.get("party"), dict):
            for team, party in body["party"].items():
                # 国服实测：领取后 status=1 且 finished_at=null。缺字段不算待命。
                if (isinstance(party, dict) and str(party.get("status")) == "1"
                        and "finished_at" in party and party["finished_at"] is None):
                    remember(youzu_log._int(team), at, "standby")
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"schema": 1, "teams": teams}), encoding="utf-8")
        temporary.replace(path)
    return teams


def visible_records(records, observations):
    result = dict(records)
    for team, record in records.items():
        proof = observations.get(team)
        if not isinstance(record, dict) or not isinstance(proof, dict):
            continue
        try:
            started = datetime.strptime(record["dispatched_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI).timestamp()
            observed = float(proof["observed_at"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        # 同秒也保留，旧领取记录绝不能覆盖重新派出的班次。
        if observed <= started:
            continue
        if proof.get("kind") == "standby" or (
                proof.get("kind") == "collected" and proof.get("map_code")
                and proof["map_code"] == record.get("map_code")):
            result.pop(team, None)
    return result
