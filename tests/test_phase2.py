"""Phase 2 tests: cleaning rules (loader and verifier must agree) and, when a database is reachable,
a real load of the fixture plus proof that the verifier notices a tampered cell."""

import os
from datetime import date
from pathlib import Path

import pytest
from dotenv import load_dotenv

from mdqc import load as loader
from mdqc import verify_phase2 as ver

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "phase1" / "raw"

NAMES = ["DEPUY IRELAND - 9616671", "ST. JUDE MEDICAL, INC.(CRM-SYLMAR)", "ENCORE MEDICAL L.P", "ENCORE MEDICAL, LP",
         "Howmedica Osteonics Corp.", "Guidant Corporation", "MEDTRONIC PUERTO RICO OPERATIONS CO.",
         "MANNKIND CORPORATION  - V-GO", "Smith & Nephew, Inc.", "SMITHS MEDICAL ASD, INC.", "Zimmer Biomet, Inc.",
         "Disetronic Medical Systems, Inc.", "", "  ", "MPRI", "WALDEMAR LINK GMBH & CO KG", "Boston Scientific CRM Corp"]


@pytest.mark.parametrize("name", NAMES)
def test_loader_and_verifier_clean_names_identically(name):
    assert loader.clean_name(name) == ver.clean(name)
    assert loader.parent_company(loader.clean_name(name)) == ver.parent(ver.clean(name))


def test_parent_examples():
    p = lambda n: loader.parent_company(loader.clean_name(n))  # noqa: E731
    assert p("ST. JUDE MEDICAL, INC.(CRM-SYLMAR)") == "ABBOTT"
    assert p("Howmedica Osteonics Corp.") == "STRYKER"
    assert p("SMITHS MEDICAL ASD, INC.") != "SMITH & NEPHEW"  # 'Smiths Medical' is a different company
    assert p("ENCORE MEDICAL L.P") == p("ENCORE MEDICAL, LP") == "ENCORE MEDICAL"
    assert p("") == "(BLANK)"


def test_recall_date_repair():
    assert loader.repair_initiated("0013-11-26", "2013-12-13") == (date(2013, 11, 26), True)
    assert loader.repair_initiated("0013-12-26", "2013-12-13") == (date(2012, 12, 26), True)  # never after posting
    assert loader.repair_initiated("2020-05-01", "2020-06-01") == (date(2020, 5, 1), False)
    assert loader.repair_initiated("garbage", "") == (None, False)


def test_strip_personal_removes_contacts_and_demographics():
    rec = {"manufacturer_contact_l_name": "Doe", "manufacturer_contact_phone_number": "555",
           "patient": [{"patient_age": "60", "patient_sex": "F", "patient_problems": ["Pain"]}], "event_type": "Injury"}
    out = loader.strip_personal(rec)
    assert "manufacturer_contact_l_name" not in out and out["patient"] == [{"patient_problems": ["Pain"]}]
    assert out["event_type"] == "Injury" and rec["patient"][0]["patient_age"] == "60"  # input untouched


def _db_url():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=3):
            return url
    except Exception:
        return None


DB = _db_url()


@pytest.mark.skipif(DB is None, reason="no PostgreSQL reachable")
def test_fixture_load_matches_and_tampering_is_detected():
    import psycopg
    schema = "pytest_phase2"
    loader.load(FIXTURE, schema, DB, write_summary=False)
    exp = ver.expected(FIXTURE)
    with psycopg.connect(DB) as con:
        diffs, sizes = ver.table_diffs(con, schema, exp)
        assert diffs == {} and sizes["fact_report"] == 200
        con.execute(f"UPDATE {schema}.fact_report SET lot_number = 'TAMPERED' "
                    f"WHERE mdr_report_key = (SELECT min(mdr_report_key) FROM {schema}.fact_report)")
        diffs, _ = ver.table_diffs(con, schema, exp)
        assert list(diffs) == ["fact_report"] and diffs["fact_report"]["n_only_db"] == 1
        con.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.mark.skipif(DB is None, reason="no PostgreSQL reachable")
def test_link_rules_at_the_window_edges(tmp_path):
    """Synthetic data: one recall started 2023-06-01 by 'Zimmer Inc.'; reports from 'ZIMMER BIOMET, INC.' at
    -181, -180, +365 and +366 days, one with a matching 510(k), one from another company."""
    from datetime import timedelta

    import psycopg
    from mdqc.download import write_jsonl_gz

    start = date(2023, 6, 1)

    def rep(key, days, maker="ZIMMER BIOMET, INC.", k=None):
        d = (start + timedelta(days=days)).strftime("%Y%m%d")
        return {"mdr_report_key": key, "date_received": d, "event_type": "Injury", "pma_pmn_number": k,
                "device": [{"device_report_product_code": "JWH", "manufacturer_d_name": maker}],
                "mdr_text": [{"text": "x", "text_type_code": "Description of Event or Problem"}]}

    reports = [rep("a", -181), rep("b", -180), rep("c", 365), rep("d", 366), rep("e", 10, k="K123456"),
               rep("f", 10, maker="EXACTECH, INC.")]
    recall = {"product_res_number": "Z-1-2023", "event_date_initiated": "2023-06-01", "event_date_posted": "2023-07-01",
              "recalling_firm": "Zimmer Inc.", "k_numbers": ["K123456"]}
    for code in loader.CODES:
        write_jsonl_gz(tmp_path / f"events_{code}.jsonl.gz", iter(reports if code == "JWH" else []))
        write_jsonl_gz(tmp_path / f"recalls_{code}.jsonl.gz", iter([recall] if code == "JWH" else []))
    loader.load(tmp_path, "pytest_links", DB, write_summary=False)
    want = {("b", "Z-1-2023", "firm_window", -180), ("c", "Z-1-2023", "firm_window", 365),
            ("e", "Z-1-2023", "firm_window", 10), ("e", "Z-1-2023", "510k", 10)}
    assert ver.expected(tmp_path)["report_recall_link"] == want
    with psycopg.connect(DB) as con:
        got = set(con.execute("SELECT mdr_report_key, product_res_number, link_type, days_from_initiation "
                              "FROM pytest_links.report_recall_link").fetchall())
        con.execute("DROP SCHEMA pytest_links CASCADE")
    assert got == want
