import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from panel import expedition_observation as obs


def event(endpoint="/conquest/complete", at="2026-09-30 17:18:05", **body):
    return {"direction": "S->C", "status": 200, "endpoint": endpoint,
            "ts": at, "payload": {"status": 0, **body}}


def record(at="2026-09-30 07:44:00", code="B1"):
    return {"dispatched_at": at, "map_code": code, "duration_min": 90}


def test_collected_hides_only_matching_old_departure(tmp_path):
    path = tmp_path / obs.FILENAME
    proofs = obs.save_observations([event(party_no="4", field_id="5")], path)
    records = {"4": record(), "5": record(code="B2")}
    assert obs.visible_records(records, proofs) == {"5": records["5"]}
    assert "4" in records  # dispatch source stays recoverable
    for at in ("2026-09-30 17:18:05", "2026-09-30 17:19:00"):
        newer = {"4": record(at)}
        assert obs.visible_records(newer, proofs) == newer
    mismatch = {"4": record(code="B2")}
    assert obs.visible_records(mismatch, proofs) == mismatch
    assert obs.load_observations(path) == proofs


def test_standby_hides_unknown_map_but_missing_or_busy_keeps_record(tmp_path):
    path = tmp_path / obs.FILENAME
    proofs = obs.save_observations([event("/login/start", party={
        "2": {"status": "1", "finished_at": None},
        "3": {"status": "1"},
        "4": {"status": "2", "finished_at": "2026-09-30 18:00:00"},
        "5": {"status": "1", "finished_at": "2026-09-30 10:00:00"},
    })], path)
    records = {str(team): record(code=None) for team in range(2, 6)}
    assert set(obs.visible_records(records, proofs)) == {"3", "4", "5"}


def test_failed_incomplete_and_unrelated_responses_are_not_evidence(tmp_path):
    path = tmp_path / obs.FILENAME
    assert obs.save_observations([
        event(party_no="4", field_id="5", status=1),
        event(party_no="4", field_id="99"),
        event(party_no="4"),
        event("/keepalive", party={"4": {"status": 1, "finished_at": None}}),
        {**event(party_no="4", field_id="5"), "status": 500},
    ], path) == {}
    assert not path.exists()


def test_replaying_older_logs_preserves_newer_proof(tmp_path):
    path = tmp_path / obs.FILENAME
    newer = obs.save_observations([event(party_no="4", field_id="5")], path)
    assert obs.save_observations([event(at="2026-09-29 10:00:00",
                                      party_no="4", field_id="6")], path) == newer
    assert obs.save_observations([], path) == newer
    # No credentials or raw game payload in the persisted evidence.
    assert set(json.loads(path.read_text())['teams']['4']) == {"observed_at", "kind", "map_code"}


def test_missing_corrupt_and_future_schema_leave_dispatches_visible(tmp_path):
    path = tmp_path / obs.FILENAME
    for content in (None, "broken", "[]", '{"schema":2,"teams":{}}'):
        if content is not None:
            path.write_text(content)
        records = {"4": record()}
        assert obs.visible_records(records, obs.load_observations(path)) == records
    assert obs.visible_records({"4": {"dispatched_at": "bad"}},
                               {"4": {"kind": "standby", "observed_at": 1}})


def test_timeline_uses_evidence_for_default_records(tmp_path):
    from panel import day_timeline as dtl
    path = tmp_path / obs.FILENAME
    obs.save_observations([event(party_no="4", field_id="5")], path)
    now = datetime(2026, 9, 30, 18, tzinfo=obs.SHANGHAI).timestamp()
    with patch.object(dtl.scheduler, "expedition_records", return_value={"4": record()}), \
         patch.object(obs, "STATUS_DIR", tmp_path):
        timeline = dtl.build_day_timeline(now=now, cfg={"automation": {}},
            store=SimpleNamespace(runs_between=lambda *args: []),
            expedition_choices={}, expedition_forced={},
            expedition_help={"rounds_per_team": 0}, planning={})
    assert timeline["expeditions"] == []


def test_idle_refresh_throttles_and_disposes_raw_log(tmp_path):
    from panel import server
    from touken import youzu_log
    config = tmp_path / "config.json"
    config.write_text('{}')
    raw = tmp_path / "raw.log"
    raw.write_text('not logged')
    with patch.object(server, "STATUS_DIR", tmp_path), \
         patch.object(server, "DEBUG_DIR", tmp_path / "debug"), \
         patch.object(server, "_CONFIG_PATH", config), \
         patch.object(server, "_expedition_observation_next", 0), \
         patch.object(server, "_read_expedition_records", return_value={"4": record()}), \
         patch.object(server, "_expedition_remaining", return_value=0), \
         patch.object(server, "get_runner", return_value=SimpleNamespace(is_running=False)) as runner, \
         patch.object(youzu_log, "pull_log", return_value=raw) as pull, \
         patch.object(youzu_log, "parse_events", return_value=[event(party_no="4", field_id="5")]):
        server._refresh_expedition_observations()
        server._refresh_expedition_observations()
        assert pull.call_count == 1
        assert not raw.exists()
        assert "4" in obs.load_observations(tmp_path / obs.FILENAME)
        runner.return_value.is_running = True
        server._expedition_observation_next = 0
        server._refresh_expedition_observations()
        assert pull.call_count == 1
