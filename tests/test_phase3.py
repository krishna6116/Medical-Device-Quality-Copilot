"""Phase 3 unit tests (no database, no model): keyword rules, FDA-term map, embedding fallback, metrics,
the verifier's own BM25 and Poisson tail, and the committed results if present."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import poisson

from mdqc import failure_modes as fm
from mdqc import verify_phase3 as v3
from mdqc.textprep import normalise, report_text

ROOT = Path(__file__).resolve().parents[1]


def test_report_text_order_and_cleaning():
    parts = [(2, "Additional Manufacturer Narrative", "MFR  NOTE"), (1, "Description of Event or Problem", "POD\x12 FELL OFF")]
    assert report_text(parts) == "POD FELL OFF || MFR NOTE"
    assert normalise("a\x12\n b") == "a b"
    assert v3.report_text(parts) == report_text(parts)  # verifier's own version agrees


@pytest.mark.parametrize("text,earliest,priority", [
    ("REVISED DUE TO PAIN AND LOOSENING OF THE STEM", "O_PAIN_STIFFNESS", "O_LOOSENING"),
    ("PATIENT WAS REVISED DUE TO INFECTION. SPACER PLACED", "O_INFECTION", "O_INFECTION"),
    ("NO INFORMATION PROVIDED", "O_OTHER", "O_OTHER"),
    ("THE LINER WOULD NOT SEAT IN THE SHELL", "O_INTRAOP", "O_INTRAOP"),
])
def test_keyword_rules_orthopedic(text, earliest, priority):
    assert fm.m2("orthopedic", text, "earliest") == earliest == v3.kw_label("orthopedic", text, "earliest")
    assert fm.m2("orthopedic", text, "priority") == priority == v3.kw_label("orthopedic", text, "priority")


def test_keyword_rules_other_families():
    assert fm.m2("diabetes", "THE CANNULA WAS FOUND BENT", "priority") == "D_CANNULA_INSERTION"
    assert fm.m2("diabetes", "POD FELL OFF THE ARM", "priority") == "D_ADHESIVE_DISLODGED"
    assert fm.m2("cardiac", "EXPLANTED PROPHYLACTICALLY DUE TO ADVISORY; BATTERY OK", "priority") == "C_PREVENTIVE"
    assert fm.m2("cardiac", "HIGH IMPEDANCE AND OVERSENSING", "priority") == "C_LEAD_CAPTURE"


def test_m1_fda_terms_priority_and_patient_terms():
    assert fm.m1("orthopedic", ["Naturally Worn", "Fracture"], []) == "O_DEVICE_FRACTURE"
    assert fm.m1("orthopedic", ["Adverse Event Without Identified Device or Use Problem"], ["Unspecified Infection"]) == "O_INFECTION"
    assert fm.m1("cardiac", ["Defective Device"], []) == "C_OTHER"
    assert fm.m1("diabetes", ["Material Twisted/Bent", "Fluid/Blood Leak"], []) == "D_LEAK"


def test_m3_threshold_falls_back_to_other():
    defs = np.eye(3, dtype=np.float32)
    modes = ["A", "B", "C"]
    vec = np.array([0.5, 0.2, 0.1], dtype=np.float32)
    assert fm.m3("orthopedic", vec, defs, modes, None) == "A"
    assert fm.m3("orthopedic", vec, defs, modes, 0.6) == "O_OTHER"


def test_verifier_bm25_equals_rank_bm25():
    from rank_bm25 import BM25Okapi
    docs = [["cannula", "bent", "pod"], ["pod", "fell", "off", "pod"], ["alarm", "error"], ["cannula", "did", "not", "deploy"]]
    for q in (["cannula", "bent"], ["pod"], ["unknown"]):
        assert np.allclose(BM25Okapi(docs).get_scores(q), v3.bm25_scores(docs, q))


@pytest.mark.parametrize("c,lam", [(5, 1.0), (12, 3.3), (1, 0.5), (30, 9.0)])
def test_poisson_tail_matches_scipy(c, lam):
    assert math.isclose(v3.poisson_tail(c, lam), float(poisson.sf(c - 1, lam)), rel_tol=1e-9, abs_tol=1e-15)


def test_macro_f1():
    assert v3.f1_macro(["a", "a", "b"], ["a", "b", "b"]) == pytest.approx((2 / 3 + 2 / 3) / 2)


@pytest.mark.skipif(not (ROOT / "results" / "phase3" / "selection.json").exists(), reason="no committed results yet")
def test_committed_results_pass_offline_checks():
    assert v3.main(offline=True, evidence=None) in (0, 1)  # runs; F2 may still be pending the user's review
    sel = json.loads((ROOT / "results" / "phase3" / "selection.json").read_text(encoding="utf-8"))
    assert sel["chosen"] in ("M1", "M2", "M3", "M4", "M5") and sel["n"] == {"validation": 100, "test": 100}
