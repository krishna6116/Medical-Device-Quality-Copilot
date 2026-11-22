"""Phase 5 memory tests on a real PostgreSQL (skipped without one). They use their own schemas
(pytest_memory, pytest_core5) so they never touch real investigations or the loaded data."""

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from mdqc import memory as mem

ROOT = Path(__file__).resolve().parents[1]
S = "pytest_memory"


def _url():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=3) as c:
            return url if c.execute("SELECT to_regclass('core.fact_report')").fetchone()[0] else None
    except Exception:
        return None


URL = _url()
pytestmark = pytest.mark.skipif(URL is None, reason="needs PostgreSQL with core.fact_report loaded")


@pytest.fixture()
def con():
    import psycopg
    c = psycopg.connect(URL)
    c.execute(f"DROP SCHEMA IF EXISTS {S} CASCADE")
    mem.ensure_schema(c, S)
    yield c
    c.rollback()
    c.execute(f"DROP SCHEMA IF EXISTS {S} CASCADE")
    c.commit()
    c.close()


def a_report(con):
    return con.execute("SELECT mdr_report_key FROM core.fact_report ORDER BY 1 LIMIT 1").fetchone()[0]


def test_round_trip_create_read_edit_delete_export(con):
    inv = mem.create_investigation(con, "Test investigation", "LZG", "INSULET", schema=S)
    key = a_report(con)
    saved = mem.add_item(con, inv, "ruled_out", "  Adhesive   failure ruled out. ", [f"MDR {key}"], schema=S)
    assert saved["text"] == "Adhesive failure ruled out." and saved["evidence"] == [{"type": "report", "id": key}]
    assert "Saved to investigation" in saved["confirmation"]
    h = mem.add_item(con, inv, "hypothesis", "Wear time may matter.", schema=S)
    mem.edit_item(con, h["item_id"], status="rejected", schema=S)
    items = mem.get_items(con, inv, S)
    assert [(i["kind"], i["status"]) for i in items] == [("ruled_out", "open"), ("hypothesis", "rejected")]
    block = mem.memory_block(con, inv, S)
    assert "Ruled out:" in block and f"(evidence: MDR {key})" in block and "[item %d, rejected]" % h["item_id"] in block
    mem.delete_item(con, h["item_id"], schema=S)
    assert "Wear time" not in mem.memory_block(con, inv, S)
    exp = mem.export_json(con, inv, S)
    assert [i["item_id"] for i in exp["items"]] == [saved["item_id"]]
    assert all("text" not in e for e in exp["audit_trail"]) and {e["action"] for e in exp["audit_trail"]} >= {"item_created", "item_deleted"}
    assert "Adhesive failure ruled out." in mem.export_markdown(con, inv, S)


def test_constraints_and_guardrails(con):
    inv = mem.create_investigation(con, "Guardrails", "LWP", schema=S)
    for kind, text, ev in [("rumour", "valid text", []), ("note", "abc", []), ("note", "x" * 501, []),
                           ("note", "mail me at a.b@example.com", []), ("note", "phone +1 617-555-0100 now", []),
                           ("note", "valid text", ["MDR 99999999"]), ("note", "valid text", ["Z-0000-0000"]), ("note", "valid text", ["the report"])]:
        with pytest.raises(mem.MemoryRefused):
            mem.add_item(con, inv, kind, text, ev, schema=S)
        con.rollback()
    with pytest.raises(mem.MemoryRefused):
        mem.create_investigation(con, "Bad code", "FRN", schema=S)
    mem.close_investigation(con, inv, schema=S)
    with pytest.raises(mem.MemoryRefused):
        mem.add_item(con, inv, "note", "after closing", schema=S)
    con.rollback()
    assert con.execute(f"SELECT count(*) FROM {S}.memory_item").fetchone()[0] == 0


def test_investigations_stay_apart_and_delete_cascades(con):
    from mdqc.tools import make_runner
    a = mem.create_investigation(con, "Investigation A", "LWP", schema=S)
    b = mem.create_investigation(con, "Investigation B", "LWP", schema=S)
    item_a = mem.add_item(con, a, "note", "belongs to A only", schema=S)["item_id"]
    sid = mem.start_session(con, b, schema=S)
    run_b = make_runner(con, b, sid, S)
    out, err = run_b("forget", {"item_id": item_a})
    assert err and "not part of this investigation" in out
    out, err = run_b("recall", {})
    assert not err and "belongs to A only" not in out
    mem.delete_investigation(con, a, schema=S)
    refs = sum(con.execute(f"SELECT count(*) FROM {S}.{t} WHERE investigation_id = %s", (a,)).fetchone()[0]
               for t in ("investigation", "session", "memory_item", "memory_event"))
    assert refs == 0 and con.execute(f"SELECT count(*) FROM {S}.memory_item").fetchone()[0] == 0


def test_memory_tools_validate_and_confirm(con):
    from mdqc.tools import make_runner
    inv = mem.create_investigation(con, "Tools", "LZG", schema=S)
    run = make_runner(con, inv, mem.start_session(con, inv, schema=S), S)
    out, err = run("remember", {"kind": "decision", "text": "Review lot ranges first.", "evidence": [a_report(con)]})
    assert not err and json.loads(out)["confirmation"].startswith("Saved")
    out, err = run("remember", {"kind": "note", "text": "ok text", "bogus": 1})
    assert err and "unknown argument" in out
    out, err = make_runner(con)("recall", {})
    assert err and "no investigation is open" in out


def test_memory_survives_a_data_reload(con):
    """The data loader drops and rebuilds only its own schema; memory lives elsewhere."""
    from mdqc import load as loader
    inv = mem.create_investigation(con, "Survives reload", "LZG", schema=S)
    mem.add_item(con, inv, "note", "must survive the reload", schema=S)
    loader.load(ROOT / "tests" / "fixtures" / "phase1" / "raw", "pytest_core5", URL, write_summary=False)
    assert "must survive the reload" in mem.memory_block(con, inv, S)
    con.execute("DROP SCHEMA pytest_core5 CASCADE")
    con.commit()
