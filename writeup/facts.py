"""Phase 9: every number the write-up publishes, read from the committed results files, with its source.

The renderer (writeup/report_phase9.py) uses only these values; the verifier (writeup/verify_phase9.py) recomputes them
separately from the same files and never imports this module.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECALL_FAMILIES = ("ACCOLADE", "PROPONENT", "ESSENTIO", "ALTRUA")


def _j(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


def usd(x: float) -> str:
    return f"${x:.2f}"


def load() -> dict:
    F: dict[str, tuple[str, str]] = {}

    def put(name, display, source):
        F[name] = (display, source)

    eda = _j("results/phase1/eda_summary.json")
    put("reports_core", f"{eda['overall']['reports']:,}", "results/phase1/eda_summary.json overall.reports")
    l7c = _j("results/phase7c/load_summary.json")["counts"]
    put("recalls", f"{l7c['fact_recall']:,}", "results/phase7c/load_summary.json counts.fact_recall")
    put("reports_all", f"{l7c['fact_report']:,}", "results/phase7c/load_summary.json counts.fact_report")
    l2 = _j("results/phase2/load_summary.json")["stats"]["manufacturer_names"]
    put("maker_names", str(l2[0]), "results/phase2/load_summary.json stats.manufacturer_names[0]")
    put("companies", str(l2[1]), "results/phase2/load_summary.json stats.manufacturer_names[1]")

    sel = _j("results/phase3/selection.json")
    m1 = sel["test"]["M1"]
    put("codebook_test", pct(m1["accuracy"], 0), "results/phase3/selection.json test.M1.accuracy")
    put("codebook_ci", f"{pct(m1['accuracy_ci95'][0], 0)} to {pct(m1['accuracy_ci95'][1], 0)}", "results/phase3/selection.json test.M1.accuracy_ci95")
    put("embedding_test", pct(sel["test"]["M3"]["accuracy"], 0), "results/phase3/selection.json test.M3.accuracy")
    sig = _j("results/phase3/signals.json")
    put("signals", str(sig["signals"]), "results/phase3/signals.json signals")
    put("recall_events", str(sig["recall_events"]), "results/phase3/signals.json recall_events")
    put("recall_hits", str(sig["hits"]), "results/phase3/signals.json hits")
    put("hit_rate", pct(sig["hit_rate"], 0), "results/phase3/signals.json hit_rate")
    put("base_rate", pct(sig["base_rate"], 0), "results/phase3/signals.json base_rate")

    s6 = _j("results/phase6/summary.json")
    h, o = s6["models"]["claude-haiku-5-5"], s6["models"]["claude-opus-5-5"]
    put("eval_questions", str(s6["questions"]), "results/phase6/summary.json questions")
    put("eval_graded", str(s6["graded"]), "results/phase6/summary.json graded")
    put("haiku_correct", str(h["correct"]), "results/phase6/summary.json models.claude-haiku-5-5.correct")
    put("opus_correct", str(o["correct"]), "results/phase6/summary.json models.claude-opus-5-5.correct")
    put("haiku_acc", pct(h["accuracy"]), "results/phase6/summary.json models.claude-haiku-5-5.accuracy")
    put("opus_acc", pct(o["accuracy"]), "results/phase6/summary.json models.claude-opus-5-5.accuracy")
    put("haiku_usd", usd(h["cost_usd"]), "results/phase6/summary.json models.claude-haiku-5-5.cost_usd")
    put("opus_usd", usd(o["cost_usd"]), "results/phase6/summary.json models.claude-opus-5-5.cost_usd")
    put("mcnemar_p", f"{s6['comparison']['mcnemar_p']:.3f}", "results/phase6/summary.json comparison.mcnemar_p")
    a2 = s6["phase4_live"]["A2"]["detail"]
    put("citations", a2["citations"], "results/phase6/summary.json phase4_live.A2.detail.citations")

    v7 = _j("results/phase7/verify_phase7.json")
    put("phase7_score", v7["scorecard"], "results/phase7/verify_phase7.json scorecard")
    rt = _j("results/phase7/redteam_grades.json")
    cats = rt["categories"].values()
    put("redteam_n", str(sum(c["of"] for c in cats)), "results/phase7/redteam_grades.json sum of categories.*.of")
    put("redteam_withheld", str(sum(c["withheld"] for c in cats)), "results/phase7/redteam_grades.json sum of categories.*.withheld")
    dc = _j("results/phase7/drift_check.json")
    put("drift_checks", str(dc["checks"]), "results/phase7/drift_check.json checks")
    put("drift_flags", str(sum(dc["flags"].values())), "results/phase7/drift_check.json sum of flags")
    dm = _j("results/phase7/drift_manifest.json")["events"]
    put("new_reports", f"{sum(v['downloaded'] for v in dm.values()):,}", "results/phase7/drift_manifest.json sum of events.*.downloaded")
    v7b = _j("results/phase7b/verify_phase7b.json")
    put("guard_caught", v7b["caught"], "results/phase7b/verify_phase7b.json caught")
    put("guard_clean_withheld", v7b["clean_withheld"], "results/phase7b/verify_phase7b.json clean_withheld")
    v7c = _j("results/phase7c/verify_phase7c.json")
    put("phase7c_checks", v7c["passed"], "results/phase7c/verify_phase7c.json passed")
    put("haiku_7c", _j("results/phase7c/model_check.json")["correct"], "results/phase7c/model_check.json correct")

    spend = h["cost_usd"] + o["cost_usd"] + v7b["spend_usd"]["phase7_total"] + _j("results/phase7c/model_check.json")["usd"]
    put("total_usd", usd(spend), "phase6 Haiku + Opus cost_usd + phase7b spend_usd.phase7_total (Phase 7 + 7b) + phase7c model_check usd")

    shares = {}
    with open(ROOT / "dashboards/snapshots/battery_brands.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for period in sorted({r["period"] for r in rows}):
        sub = [r for r in rows if r["period"] == period]
        shares[period] = sum(int(r["reports"]) for r in sub if r["family"] in RECALL_FAMILIES) / sum(int(r["reports"]) for r in sub)
    put("battery_before", pct(shares["2025Q1-2025Q3"]), "dashboards/snapshots/battery_brands.csv recall-family share, 2025Q1-2025Q3")
    put("battery_after", pct(shares["2025Q4-2026Q3"]), "dashboards/snapshots/battery_brands.csv recall-family share, 2025Q4-2026Q3")

    pb = _j("dashboards/powerbi_evidence.json")
    put("powerbi_score", pb["score"], "dashboards/powerbi_evidence.json score")
    put("powerbi_values", str(pb["items"]["C3"]["checks"]["values_compared"]), "dashboards/powerbi_evidence.json items.C3.checks.values_compared")
    return F


def values() -> dict:
    return {k: v[0] for k, v in load().items()}


if __name__ == "__main__":
    for k, (v, s) in load().items():
        print(f"{k:22} {v:>12}  {s}")
