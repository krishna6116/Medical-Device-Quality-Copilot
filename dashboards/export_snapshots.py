"""Phase 8: export the small, deterministic files the Streamlit app reads (dashboards/snapshots/). Needs the local database.

Run:  python -m dashboards.export_snapshots

The app never touches the database or the API: everything it shows comes from these files, and the manifest records each
file's rows and sha256 plus the sha256 of every results file they were built from.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "dashboards" / "snapshots"
PRODUCTS = {"LPH": "Hip implant, uncemented", "JWH": "Knee implant, cemented", "MBH": "Knee implant, uncemented", "LWP": "Pacemaker", "LZG": "Insulin pump"}
LAST_COMPLETE = "2026Q3"  # reports after this quarter are still arriving
SOURCES = ["results/phase6/summary.json", "results/phase7/redteam_grades.json", "results/phase7/drift_check.json", "results/phase7/verify_phase7.json",
           "results/phase7b/test_grades.json", "results/phase7c/model_check.json", "results/phase7c/verify_phase7c.json", "config/phase6_eval_set.json",
           "config/phase7c_questions.json", "config/failure_modes.json"]


def write_csv(name: str, header: list[str], rows: list) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    (SNAP / name).write_text(buf.getvalue(), encoding="utf-8", newline="")


def write_json(name: str, obj) -> None:
    (SNAP / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="")


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def answers() -> list[dict]:
    """Recorded assistant answers the app replays: Phase 6 (Haiku, 2022-2024) and Phase 7c (Haiku, 2022-2026)."""
    out = []
    g6 = load("results/phase6/grades.json")["claude-haiku-5-5"]
    for q in load("config/phase6_eval_set.json")["questions"]:
        r = load(f"results/phase6/claude-haiku-5-5/{q['id']}.json")
        g = g6[q["id"]]
        out.append({"id": f"P6-{q['id']}", "set": "Phase 6 evaluation (2022-2024)", "category": q["category"], "question": q["text"], "answer": r["answer"],
                    "tools": [t["name"] for t in r["tool_calls"]], "model": r["model"], "cost_usd": r["cost_usd"], "steps": r["steps"],
                    "recorded_utc": r["recorded_utc"], "graded": g["graded"], "correct": g["correct"] if g["graded"] else None})
    m = {x["id"]: x for x in load("results/phase7c/model_check.json")["rows"]}
    for q in load("config/phase7c_questions.json")["questions"]:
        r = load(f"results/phase7c/answers/{q['id']}.json")
        out.append({"id": f"P7c-{q['id']}", "set": "Phase 7c check (2022-2026)", "category": q["category"], "question": q["text"], "answer": r["answer"],
                    "tools": [t["name"] for t in r["tool_calls"]], "model": r["model"], "cost_usd": r["cost_usd"], "steps": r["steps"],
                    "recorded_utc": None, "graded": True, "correct": m[q["id"]]["correct"]})
    return out


def results() -> dict:
    s6, r7, v7 = load("results/phase6/summary.json"), load("results/phase7/redteam_grades.json"), load("results/phase7/verify_phase7.json")
    b, m7c, v7c = load("results/phase7b/test_grades.json"), load("results/phase7c/model_check.json"), load("results/phase7c/verify_phase7c.json")
    h, o = s6["models"]["claude-haiku-5-5"], s6["models"]["claude-opus-5-5"]
    return {
        "phase6": {"haiku_correct": h["correct"], "haiku_of": h["of"], "haiku_cost_usd": h["cost_usd"], "opus_correct": o["correct"], "opus_of": o["of"],
                   "opus_cost_usd": o["cost_usd"], "difference": s6["comparison"]["difference"], "ci95": s6["comparison"]["ci95"], "decision": s6["comparison"]["decision"]},
        "phase7": {"scorecard": v7["scorecard"], "categories": r7["categories"], "g2_met": r7["G2_met"], "withheld": sum(bool(x["withheld_for"]) for x in r7["rows"]),
                   "cases": len(r7["rows"]), "spend_usd": r7["phase7_spend_usd"]},
        "phase7b": {"caught": b["caught"], "clean_withheld": len(b["clean_withheld"]), "plants_labelled_unsafe": b["plants_labelled_unsafe"], "passes": b["passes"],
                    "labels_by": "Claude Opus 5.5 (AI, no human check)"},
        "phase7c": {"checks": v7c["passed"], "correct": m7c["correct"], "cost_usd": m7c["usd"]},
    }


def main() -> None:
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    SNAP.mkdir(parents=True, exist_ok=True)
    con = psycopg.connect(os.environ["DATABASE_URL"])
    q = lambda s: con.execute(s).fetchall()  # noqa: E731
    R = "core_all.fact_report r"
    write_csv("quarterly.csv", ["product", "quarter", "event_type", "reports"],
              q(f"SELECT product_code, to_char(date_received, 'YYYY\"Q\"Q'), event_type, count(*) FROM {R} GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"))
    write_csv("quarterly_modes.csv", ["product", "quarter", "mode", "reports"],
              q(f"SELECT r.product_code, to_char(date_received, 'YYYY\"Q\"Q'), f.mode, count(*) FROM {R} JOIN analytics_all.report_failure_mode f USING (mdr_report_key) GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"))
    write_csv("makers.csv", ["product", "year", "company", "reports"],
              q(f"SELECT r.product_code, extract(year FROM date_received)::int, m.parent_company, count(*) FROM {R} JOIN core_all.dim_manufacturer m USING (manufacturer_id) GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"))
    write_csv("signals.csv", ["product", "company", "mode", "month", "reports", "expected"],
              q("SELECT product_code, parent_company, mode, month, count, round(expected::numeric, 1) FROM analytics_all.signal_month ORDER BY 1, 2, 3, 4"))
    write_csv("recalls.csv", ["recall_number", "recall_event", "product", "company", "started", "status", "root_cause", "reason"],
              q(r"SELECT product_res_number, res_event_number, product_code, m.parent_company, event_date_initiated::text, recall_status, regexp_replace(root_cause, '\s+', ' ', 'g'), left(regexp_replace(reason_for_recall, '\s+', ' ', 'g'), 300) "
                "FROM core_all.fact_recall JOIN core_all.dim_manufacturer m USING (manufacturer_id) ORDER BY 1"))
    con.close()
    d = load("results/phase7/drift_check.json")
    write_csv("drift.csv", ["product", "quarter", "reports", "volume_change", "mode_mix", "vocabulary", "flags", "largest_mode_move"],
              [[r["code"], r["quarter"], r["reports"], round(r["volume_change"], 4), round(r["mode_mix"], 4), round(r["vocabulary"], 4), ";".join(r["flags"]),
                f"{r['largest_mode_moves'][0][0]} {r['largest_mode_moves'][0][1]:+.4f}"] for r in d["rows"]])
    book = load("config/failure_modes.json")
    write_json("reference.json", {"products": PRODUCTS, "last_complete_quarter": LAST_COMPLETE, "drift_thresholds": {k: round(v, 4) for k, v in d["thresholds"].items()},
                                  "modes": {m: x["definition"] for f in book["families"].values() for m, x in f["modes"].items()}})
    write_json("answers.json", answers())
    write_json("results.json", results())
    files = sorted(p for p in SNAP.iterdir() if p.name != "manifest.json")
    man = {"files": {p.name: {"sha256": sha(p), "rows": (sum(1 for _ in csv.reader(p.open(encoding="utf-8", newline=""))) - 1) if p.suffix == ".csv" else len(json.loads(p.read_text(encoding="utf-8")))} for p in files},
           "sources": {s: sha(ROOT / s) for s in SOURCES}}
    man["data_checksum"] = hashlib.sha256("".join(v["sha256"] for v in man["files"].values()).encode()).hexdigest()
    write_json("manifest.json", man)
    print(len(files), "files;", "data checksum", man["data_checksum"][:12], {k: v["rows"] for k, v in man["files"].items()})


if __name__ == "__main__":
    main()
