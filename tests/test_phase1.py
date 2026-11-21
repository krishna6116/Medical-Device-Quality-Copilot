"""Phase 1 tests: deterministic raw files, verifier helpers, and EDA vs verifier on the committed fixture."""

import gzip
import json
from pathlib import Path

import pytest

from mdqc import eda, verify_phase1
from mdqc.download import sha256, write_jsonl_gz

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "phase1" / "raw"


def test_jsonl_gz_is_deterministic(tmp_path):
    recs = [{"b": 2, "a": 1}, {"a": "é"}]
    p1, p2 = tmp_path / "x.jsonl.gz", tmp_path / "y.jsonl.gz"
    write_jsonl_gz(p1, iter(recs))
    write_jsonl_gz(p2, iter(recs))
    assert sha256(p1) == sha256(p2)  # mtime=0 + sorted keys -> same bytes
    with gzip.open(p1, "rt", encoding="utf-8") as fh:
        assert [json.loads(x) for x in fh] == recs


def test_percentile_matches_numpy():
    import numpy as np
    vals = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]
    for q in (50, 90, 10):
        assert verify_phase1.interp_percentile(vals, q) == round(float(np.percentile(vals, q)), 1)
    assert verify_phase1.interp_percentile([], 50) is None


def test_dates():
    assert verify_phase1.ymd("20240229").isoformat() == "2024-02-29"
    assert verify_phase1.ymd("20230229") is None and verify_phase1.ymd("") is None
    assert eda.parse_date("2024-01-01") is None


def test_report_row_definitions():
    rec = {"mdr_report_key": "1", "date_received": "20230105", "date_of_event": "20221231",
           "event_type": " Injury ", "product_problems": ["Loosening"],
           "device": [{"device_report_product_code": "XXX", "manufacturer_d_name": "other"},
                      {"device_report_product_code": "LPH", "manufacturer_d_name": " acme corp "}],
           "mdr_text": [{"text": "abc"}, {"text": "de"}], "manufacturer_contact_l_name": "Doe"}
    r = eda.report_row(rec, "LPH")
    assert r["manufacturer"] == "ACME CORP" and r["event_type"] == "Injury"
    assert r["narrative_len"] == len("abc de") and r["lag_days"] == 5
    assert r["n_devices"] == 2 and r["has_contact"] and r["month"] == "2023-01"


def test_compare_finds_mismatch():
    assert verify_phase1.compare({"a": 1, "b": {"c": 0.5}}, {"b": {"c": 0.5}, "a": 1}) == []
    assert verify_phase1.compare({"a": 1}, {"a": 2})


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture not built yet")
def test_eda_and_verifier_agree_on_fixture(tmp_path):
    s = eda.main(raw=FIXTURE, out=tmp_path, make_figures=False)
    mine = verify_phase1.recompute(FIXTURE)
    assert verify_phase1.compare(mine["per_code"], s["per_code"]) == []
    assert verify_phase1.compare(mine["overall"], s["overall"]) == []
    assert s["overall"]["reports_with_contact_fields"] == 0  # fixture blanks contact fields


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture not built yet")
def test_verifier_catches_a_planted_error(tmp_path):
    s = eda.main(raw=FIXTURE, out=tmp_path, make_figures=False)
    code = s["codes"][0]
    s["per_code"][code]["reports"] += 1  # plant a wrong number
    mine = verify_phase1.recompute(FIXTURE)
    assert verify_phase1.compare(mine["per_code"], s["per_code"])


RESULTS = ROOT / "results" / "phase1"


@pytest.mark.skipif(not (RESULTS / "verify_phase1.json").exists(), reason="no committed evidence yet")
def test_committed_evidence_is_consistent():
    ev = json.loads((RESULTS / "verify_phase1.json").read_text(encoding="utf-8"))
    assert ev["all_pass"] and {c["id"] for c in ev["checks"]} >= {"C1", "C2", "C3", "C4", "C5", "C6", "C7"}
    s = json.loads((RESULTS / "eda_summary.json").read_text(encoding="utf-8"))
    m = json.loads((RESULTS / "download_manifest.json").read_text(encoding="utf-8"))
    for code, e in m["events"].items():
        assert e["server_total_before"] == e["downloaded"] == s["per_code"][code]["reports"]
    scope = json.loads((ROOT / "config" / "scope.json").read_text(encoding="utf-8"))
    assert list(s["per_code"]) == list(scope["product_codes"])  # analysis used exactly the registered scope
