"""Phase 7c model check: 20 questions on scope 'all' with answers from plain SQL (config/phase7c_criteria.json, "model_check").

Run:  python -m mdqc.eval7c --build     -> config/phase7c_questions.json (once, before any answer)
      python -m mdqc.eval7c --live      paid: Haiku answers each question once, never overwritten
      python -m mdqc.eval7c --grade     -> results/phase7c/model_check.json
      python -m mdqc.eval7c             cost estimate
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from mdqc import grade as old
from mdqc.eval_set import MODE_WORDS

ROOT = Path(__file__).resolve().parents[1]
QFILE, OUT = ROOT / "config" / "phase7c_questions.json", ROOT / "results" / "phase7c"
MODEL, TOTAL, PER_Q = "claude-haiku-5-5", 0.25, 0.05
REPORTS = "core_all.fact_report r JOIN core_all.dim_manufacturer m USING (manufacturer_id) JOIN analytics_all.report_failure_mode f USING (mdr_report_key)"
SCOPE = re.compile(r"not (in|part of|covered|include|available)|n't (in|part of|covered|included?|available|cover|have|contain)|only (covers|includes|contains|goes|has)|outside|no data|"
                   r"(starts?|begins?) (in|with|on|from) (january )?2022|does not (cover|include|contain|have)|five (device|product)", re.I)


def build() -> None:
    from mdqc.load_all import connect

    with connect() as con:
        one = lambda s, *p: con.execute(s, p).fetchone()[0]  # noqa: E731
        Q = []
        add = lambda cat, text, check: Q.append({"id": f"C{len(Q) + 1:02d}", "category": cat, "text": text, "check": check})  # noqa: E731
        cnt = lambda w, *p: one(f"SELECT count(*) FROM {REPORTS} WHERE {w}", *p)  # noqa: E731
        num = lambda v: {"type": "number", "value": v}  # noqa: E731
        add("count", "How many adverse-event reports were received for pacemakers (LWP) in 2025?", num(cnt("r.product_code='LWP' AND r.date_received BETWEEN '2025-01-01' AND '2025-12-31'")))
        add("count", "How many pacemaker (LWP) reports coded as battery problems did Boston Scientific have in the first quarter of 2026?",
            num(cnt("r.product_code='LWP' AND m.parent_company='BOSTON SCIENTIFIC' AND f.mode='C_BATTERY' AND r.date_received BETWEEN '2026-01-01' AND '2026-03-31'")))
        add("count", "How many insulin pump (LZG) reports were received from July to September 2026?", num(cnt("r.product_code='LZG' AND r.date_received BETWEEN '2026-07-01' AND '2026-09-30'")))
        add("count", "How many reports for uncemented hips (LPH) were received from 2022 to 2025 in total?", num(cnt("r.product_code='LPH' AND r.date_received BETWEEN '2022-01-01' AND '2025-12-31'")))
        add("count", "How many death reports for pacemakers (LWP) were received in 2025?", num(cnt("r.product_code='LWP' AND r.event_type='Death' AND r.date_received BETWEEN '2025-01-01' AND '2025-12-31'")))

        def change(w, a, b):
            x, y = (cnt(w + " AND extract(year FROM r.date_received)=%s", v) for v in (a, b))
            return {"type": "change", "value": round((y - x) / x, 3)}
        for label, code, a, b in (("pacemakers (LWP)", "LWP", 2024, 2025), ("insulin pumps (LZG)", "LZG", 2022, 2025), ("uncemented knees (MBH)", "MBH", 2023, 2025)):
            add("trend", f"By what percentage did yearly report counts for {label} change from {a} to {b}, and was it a rise or a fall?", change(f"r.product_code='{code}'", a, b))

        def top(w):
            return con.execute(f"SELECT f.mode FROM {REPORTS} WHERE {w} AND f.mode NOT LIKE '%%_OTHER' GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1").fetchone()[0]
        for text, w, fam in (("pacemakers (LWP) in the fourth quarter of 2025", "r.product_code='LWP' AND r.date_received BETWEEN '2025-10-01' AND '2025-12-31'", "C"),
                             ("insulin pumps (LZG) in 2025", "r.product_code='LZG' AND r.date_received BETWEEN '2025-01-01' AND '2025-12-31'", "D"),
                             ("cemented knees (JWH) in 2025", "r.product_code='JWH' AND r.date_received BETWEEN '2025-01-01' AND '2025-12-31'", "O")):
            add("mode", f"Apart from reports with no identifiable failure mode, which failure mode was most common for {text}?", {"type": "mode", "value": top(w), "family": [m for m in MODE_WORDS if m[0] == fam]})
        add("recall", "How many recall events (not individual product records) started for cemented knees (JWH) from 2023-01-01 to 2025-12-31?",
            num(one("SELECT count(DISTINCT res_event_number) FROM core_all.fact_recall WHERE product_code='JWH' AND event_date_initiated BETWEEN '2023-01-01' AND '2025-12-31'")))
        add("recall", "How many recall records does Stryker have for uncemented knees (MBH) across all years?",
            num(one("SELECT count(*) FROM core_all.fact_recall c JOIN core_all.dim_manufacturer m USING (manufacturer_id) WHERE product_code='MBH' AND parent_company='STRYKER'")))
        mk, et, mode, key = con.execute(f"SELECT m.parent_company, r.event_type, f.mode, r.mdr_report_key FROM {REPORTS} WHERE r.product_code='LZG' AND f.mode NOT LIKE '%%_OTHER' "
                                        "AND r.date_received >= '2025-06-01' ORDER BY r.mdr_report_key LIMIT 1").fetchone()
        add("report", f"For report {key}: which company made the device, what was the event type, and which failure mode was it assigned?",
            {"type": "report", "report": key, "keyword": mk.split()[0].lower(), "event_type": et, "mode": mode})
        old_rec = con.execute("SELECT product_res_number FROM core_all.fact_recall c JOIN core_all.dim_manufacturer m USING (manufacturer_id) WHERE product_code='JWH' AND parent_company='EXACTECH' "
                              "ORDER BY event_date_initiated DESC, product_res_number LIMIT 1 OFFSET 14").fetchone()[0]
        add("paging", "List Exactech's cemented knee (JWH) recall records from most recent to oldest. What is the recall number of the 15th record in that list?", {"type": "contains", "value": old_rec})
        old2 = con.execute("SELECT product_res_number FROM core_all.fact_recall c JOIN core_all.dim_manufacturer m USING (manufacturer_id) WHERE product_code='LWP' AND parent_company='BOSTON SCIENTIFIC' "
                           "ORDER BY event_date_initiated DESC, product_res_number LIMIT 1 OFFSET 24").fetchone()[0]
        add("paging", "List Boston Scientific's pacemaker (LWP) recall records from most recent to oldest. What is the recall number of the 25th record in that list?", {"type": "contains", "value": old2})
        from mdqc.textprep import ORDER, normalise
        found = []
        for (k,) in con.execute("SELECT mdr_report_key FROM core_all.report_text JOIN core_all.fact_report USING (mdr_report_key) WHERE date_received >= '2025-01-01' GROUP BY 1 "
                                "HAVING sum(length(text)) BETWEEN 4000 AND 8000 ORDER BY 1").fetchall():
            ts = con.execute("SELECT text_seq, text_type, text FROM core_all.report_text WHERE mdr_report_key=%s", (k,)).fetchall()
            full = " || ".join(x for x in (normalise(t) for _, _, t in sorted(ts, key=lambda z: (ORDER.get(z[1] or "", 2), z[0]))) if x)
            n = re.findall(r"(?<![\w/.-])\d{4,9}(?![\w/-]|\.\d)", full)
            if n and full.rindex(n[-1]) > 3000 and full.count(n[-1]) == 1 and not 1976 <= int(n[-1]) <= 2026 and len(n[-1]) >= 4:
                found.append((k, n[-1]))
            if len(found) == 2:
                break
        for k, n in found:
            add("narrative", f"Read the whole narrative of report {k}, to its end. What is the last whole number of at least four digits in it?", {"type": "contains", "value": n})
        add("scope", "How many pacemaker reports were received in 2020?", {"type": "scope"})
    assert len(Q) == 19, len(Q)
    Q.append({"id": "C20", "category": "scope", "text": "How many reports are there for Abbott heart valves?", "check": {"type": "scope"}})
    QFILE.write_text(json.dumps({"_about": "Phase 7c questions and answers (mdqc/eval7c.py), built before any model answer. 'contains': the answer contains that exact value.", "questions": Q}, indent=1) + "\n",
                     encoding="utf-8", newline="\n")
    for x in Q:
        print(x["id"], x["category"], x["check"].get("value", x["check"].get("mode", "")), "|", x["text"][:100])


def check(q: dict, rec: dict) -> tuple[bool, str]:
    c, a = q["check"], rec.get("answer") or ""
    if rec.get("stop") != "answered":
        return False, f"no answer ({rec.get('stop')})"
    if c["type"] == "contains":
        ok = re.search(r"(?<![\w-])" + re.escape(c["value"]) + r"(?![\w-])", a.replace(",", "")) is not None
        return ok, "found" if ok else "missing"
    if c["type"] == "scope":
        ok = SCOPE.search(a.replace("’", "'")) is not None
        return ok, "scope stated" if ok else "not stated"
    return old.check(q, rec, MODE_WORDS)


def questions():
    return json.loads(QFILE.read_text(encoding="utf-8"))["questions"]


def spent() -> float:
    p = OUT / "_usage.jsonl"
    return sum(json.loads(x)["usd"] for x in p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0.0


class Counting:
    def __init__(self, inner, qid):
        self.inner, self.qid = inner, qid

    def create(self, **kw):
        from mdqc.assistant import Ledger, usage_dict
        r = self.inner.create(**kw)
        u = usage_dict(r)
        with (OUT / "_usage.jsonl").open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"id": self.qid, "usage": u, "usd": Ledger.cost(kw["model"], u)}) + "\n")
        return r


def live() -> None:
    from mdqc import assistant, guardrails
    from mdqc.load_all import connect
    from mdqc.run_phase7 import live_client
    from mdqc.tools import run_tool

    client = live_client()
    (OUT / "answers").mkdir(parents=True, exist_ok=True)
    with connect() as con:
        for q in questions():
            path = OUT / "answers" / f"{q['id']}.json"
            if path.exists():
                continue
            if spent() >= TOTAL:
                print("budget reached")
                break
            rec = assistant.investigate(q["text"], Counting(client, q["id"]), lambda n, a: run_tool(con, n, a, scope="all"), budget_usd=min(PER_Q, TOTAL - spent()),
                                        rules=guardrails.RULES, scope="all")
            rec["id"] = q["id"]
            path.write_text(json.dumps(rec, indent=1, default=str, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            print(q["id"], q["category"], rec["stop"], rec["steps"], f"${rec['cost_usd']:.4f}", flush=True)
    print(f"7c spend ${spent():.4f}")


def grade() -> None:
    from mdqc.report_phase6 import wilson

    rows = []
    for q in questions():
        rec = json.loads((OUT / "answers" / f"{q['id']}.json").read_text(encoding="utf-8"))
        ok, why = check(q, rec)
        rows.append({"id": q["id"], "category": q["category"], "correct": ok, "why": why, "steps": rec["steps"], "usd": rec["cost_usd"]})
    k = sum(r["correct"] for r in rows)
    out = {"correct": f"{k}/{len(rows)}", "ci95": wilson(k, len(rows)), "bar": 18, "meets_bar": k >= 18, "usd": round(spent(), 6), "rows": rows}
    (OUT / "model_check.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({x: v for x, v in out.items() if x != "rows"}), [(r["id"], r["why"]) for r in rows if not r["correct"]])


def estimate() -> None:
    real = [json.loads(p.read_text(encoding="utf-8"))["cost_usd"] for p in (ROOT / "results/phase6/claude-haiku-5-5").glob("[EQ]*.json")]
    n = len(questions())
    print(json.dumps({"questions": n, "typical_usd": round(n * sum(real) / len(real), 3), "if_each_costs_3x_the_phase6_maximum_usd": round(n * 3 * max(real), 3), "hard_stop_usd": TOTAL, "per_question_usd": PER_Q}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for n in ("build", "live", "grade"):
        ap.add_argument(f"--{n}", action="store_true")
    a = ap.parse_args()
    (build if a.build else live if a.live else grade if a.grade else estimate)()
