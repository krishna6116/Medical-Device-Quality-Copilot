"""Phase 3 independent verification (criteria F1-F8 in config/phase3_criteria.json).

Run:  python -m mdqc.verify_phase3              full check (needs the database and data/processed/)
      python -m mdqc.verify_phase3 --offline    only what the committed files allow (CI): F1, F2, F3, F4

Independence: never imports mdqc.run_phase3 or mdqc.failure_modes. It re-implements the keyword rules,
the FDA-term map, the embedding argmax, BM25 (Okapi, the formula rank-bm25 uses), reciprocal-rank fusion,
the Poisson tail (summing probabilities by hand) and every metric, then compares with results/phase3/.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "phase3"
CB = json.loads((ROOT / "config" / "failure_modes.json").read_text(encoding="utf-8"))
FAM = {c: f for f, v in CB["families"].items() for c in v["codes"]}
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def first_commit(path):
    out = git("log", "--diff-filter=A", "--format=%H", "--", path).splitlines()
    return out[-1] if out else None


def is_ancestor(a, b):
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=ROOT).returncode == 0


def read_csv(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def acc(rows, col):
    return sum(r[col] == r["label"] for r in rows) / len(rows)


def boot(values, n=2000, seed=0):
    v = np.asarray(values, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(v), size=(n, len(v)))
    m = np.sort(v[idx].mean(axis=1))
    def q(p):  # linear interpolation, written out
        pos = (len(m) - 1) * p
        lo, hi = math.floor(pos), math.ceil(pos)
        return m[lo] + (m[hi] - m[lo]) * (pos - lo)
    return [round(float(q(0.025)), 4), round(float(q(0.975)), 4)]


def f1_macro(gold, pred):
    out = []
    for m in sorted(set(gold) | set(pred)):
        tp = sum(g == m and p == m for g, p in zip(gold, pred))
        fp = sum(g != m and p == m for g, p in zip(gold, pred))
        fn = sum(g == m and p != m for g, p in zip(gold, pred))
        out.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return sum(out) / len(out)


def poisson_tail(c, lam):
    """P(X >= c) = 1 - sum_{i<c} e^-lam lam^i / i!, summed directly."""
    s, term = 0.0, math.exp(-lam)
    for i in range(c):
        s += term
        term *= lam / (i + 1)
    return max(0.0, 1.0 - s)


# ---- independent text + methods ----------------------------------------------------------------------
def report_text(parts):
    rank = {"Description of Event or Problem": 0, "Additional Manufacturer Narrative": 1}
    parts = sorted(parts, key=lambda p: (rank.get(p[1] or "", 2), p[0]))
    cleaned = [" ".join(CONTROL.sub(" ", p[2] or "").split()) for p in parts]
    return " || ".join(c for c in cleaned if c)[:2000]


def kw_label(fam, text, setting):
    pri = CB["families"][fam]["priority"]
    other = [m for m in CB["families"][fam]["modes"] if m.endswith("_OTHER")][0]
    first = {}
    for mode, d in CB["families"][fam]["modes"].items():
        if "keywords" in d:
            m = re.compile(d["keywords"], re.I).search(text)
            if m:
                first[mode] = m.start()
    if not first:
        return other
    if setting == "priority":
        return [m for m in pri if m in first][0]
    return sorted(first, key=lambda m: (first[m], pri.index(m)))[0]


def term_label(fam, device_terms, patient_terms):
    """M1 re-implemented: FDA terms -> modes via the codebook map; family priority; else *_OTHER."""
    tmap = CB["fda_term_map"][fam]
    hit = set()
    for t in device_terms:
        if t in tmap:
            hit.add(tmap[t])
    for t in patient_terms:
        if ("patient:" + t) in tmap:
            hit.add(tmap["patient:" + t])
    for mode in CB["families"][fam]["priority"]:
        if mode in hit:
            return mode
    return [m for m in CB["families"][fam]["modes"] if m.endswith("_OTHER")][0]


def bm25_scores(docs, query, k1=1.5, b=0.75, eps=0.25):
    """Okapi BM25 as in rank-bm25 0.2.2 (negative idf floored at eps * average idf)."""
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / n
    df = Counter(t for d in docs for t in set(d))
    idf = {t: math.log(n - f + 0.5) - math.log(f + 0.5) for t, f in df.items()}
    avg_idf = sum(idf.values()) / len(idf)
    idf = {t: (v if v >= 0 else eps * avg_idf) for t, v in idf.items()}
    out = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in query:
            f = tf.get(t, 0)
            s += idf.get(t, 0.0) * (f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avgdl)))
        out.append(s)
    return out


def main(offline: bool, evidence: Path | None) -> int:
    checks = []

    def check(cid, name, ok, detail):
        checks.append({"id": cid, "check": name, "pass": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {cid} {name}: {json.dumps(detail, default=str)[:230]}")

    sel = json.loads((RES / "selection.json").read_text(encoding="utf-8"))
    pred = read_csv(RES / "predictions_sample.csv")

    # F1 order in git
    c_crit, c_lab = first_commit("config/phase3_criteria.json"), first_commit("config/phase3_labels.csv")
    c_res = first_commit("results/phase3/selection.json")
    labels_unchanged = git("diff", "--stat", c_lab or "HEAD", "--", "config/phase3_labels.csv") == "" if c_lab else False
    order_ok = bool(c_crit and c_lab and is_ancestor(c_crit, c_lab) and c_crit != c_lab
                    and (c_res is None or (is_ancestor(c_lab, c_res) and c_lab != c_res)))
    no_results_in_label_commit = not any(p.startswith("results/phase3/") for p in
                                         git("show", "--name-only", "--format=", c_lab).splitlines()) if c_lab else False
    check("F1", "criteria -> labels -> results committed in that order; labels unchanged since",
          order_ok and labels_unchanged and no_results_in_label_commit,
          {"criteria": (c_crit or "")[:7], "labels": (c_lab or "")[:7], "results": (c_res or "not committed yet")[:7],
           "labels_unchanged": labels_unchanged})

    # F2 spot check
    spot = read_csv(ROOT / "config" / "phase3_spot_check.csv")
    verdicts = [r["user_verdict"].strip().lower() for r in spot]
    agree = sum(v == "agree" for v in verdicts)
    filled = all(v in ("agree", "disagree") for v in verdicts)
    reviewers = sorted({r.get("reviewer", "user") for r in spot})
    check("F2", "spot-check of 20 labels: >= 16 agree (reviewer recorded; delegated to Claude = post hoc)",
          filled and agree >= 16,
          {"reviewed": sum(v in ("agree", "disagree") for v in verdicts), "agree": agree, "of": len(spot),
           "reviewer": reviewers})

    # F3 selection on validation
    val = [r for r in pred if r["split"] == "validation"]
    settings = [c for c in pred[0] if c[:2] in ("M1", "M2", "M3", "M4", "M5")]
    vacc = {c: round(acc(val, c), 4) for c in settings}
    m2 = max(["M2:earliest", "M2:priority"], key=lambda c: (vacc[c], -["M2:earliest", "M2:priority"].index(c)))
    th = ["M3:None", "M3:0.55", "M3:0.6", "M3:0.65"]
    m3 = max(th, key=lambda c: (vacc[c], -th.index(c)))
    m4 = [c for c in settings if c.startswith("M4:")][0]
    chosen_cols = {"M1": "M1", "M2": m2, "M3": m3, "M4": m4, "M5": "M5"}
    order = ["M1", "M2", "M3", "M4", "M5"]
    chosen = max(order, key=lambda m: (vacc[chosen_cols[m]], -order.index(m)))
    m4_ok = m4 == f"M4:{m2.split(':')[1]}+{m3.split(':')[1]}"
    check("F3", "chosen method and settings follow from validation accuracy only",
          chosen == sel["chosen"] and chosen_cols == sel["chosen_settings"] and m4_ok
          and all(abs(vacc[chosen_cols[m]] - sel["validation_accuracy"][m]) < 1e-9 for m in order),
          {"validation": {m: vacc[chosen_cols[m]] for m in order}, "chosen": chosen})

    # F4 test metrics recomputed
    test = sorted([r for r in pred if r["split"] == "test"], key=lambda r: r["mdr_report_key"])
    bad = []
    corr = {}
    for m in order:
        col = chosen_cols[m]
        corr[m] = [int(r[col] == r["label"]) for r in test]
        a = round(sum(corr[m]) / len(test), 4)
        f = round(f1_macro([r["label"] for r in test], [r[col] for r in test]), 4)
        if a != sel["test"][m]["accuracy"] or f != sel["test"][m]["macro_f1"] or boot(corr[m]) != sel["test"][m]["accuracy_ci95"]:
            bad.append(m)
    d = [a - b for a, b in zip(corr[chosen], corr["M1"])]
    cmp_ok = boot(d) == sel["chosen_vs_m1_test"]["difference_ci95"] and \
        round(sum(d) / len(d), 4) == sel["chosen_vs_m1_test"]["difference"]
    check("F4", "test accuracy, macro-F1, intervals and chosen-vs-M1 recomputed", not bad and cmp_ok,
          {"mismatch": bad, "test_accuracy": {m: sel["test"][m]["accuracy"] for m in order},
           "chosen_minus_M1": sel["chosen_vs_m1_test"]})

    if not offline:
        import psycopg
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        con = psycopg.connect(os.environ["DATABASE_URL"])
        parts = defaultdict(list)
        for k, seq, tt, tx in con.execute("SELECT mdr_report_key, text_seq, text_type, text FROM core.report_text").fetchall():
            parts[k].append((seq, tt, tx))
        texts = {k: report_text(v) for k, v in parts.items()}
        info = {k: (c, p, d) for k, c, p, d in con.execute(
            "SELECT r.mdr_report_key, r.product_code, m.parent_company, r.date_received FROM core.fact_report r "
            "JOIN core.dim_manufacturer m USING (manufacturer_id)").fetchall()}
        keys = (ROOT / "data" / "processed" / "embeddings_bge_small_keys.txt").read_text(encoding="utf-8").split()
        emb = np.load(ROOT / "data" / "processed" / "embeddings_bge_small.npy").astype(np.float32)
        row = {k: i for i, k in enumerate(keys)}
        dv = np.load(RES / "mode_definition_vectors.npz")

        def emb_label(k, thr):
            fam = FAM[info[k][0]]
            names = [n for n in dv.files if n.startswith(fam + "__")]
            sims = [float(dv[n] @ emb[row[k]]) for n in names]
            i = int(np.argmax(sims))
            if thr is not None and sims[i] < thr:
                return [m for m in CB["families"][fam]["modes"] if m.endswith("_OTHER")][0]
            return names[i].split("__", 1)[1]

        dterms, pterms = defaultdict(list), defaultdict(list)
        for k, t in con.execute("SELECT mdr_report_key, term FROM core.report_problem").fetchall():
            dterms[k].append(t)
        for k, t in con.execute("SELECT mdr_report_key, term FROM core.report_patient_problem").fetchall():
            pterms[k].append(t)

        # sample predictions for M1, the keyword and the embedding methods recomputed from scratch
        mism = []
        for r in pred:
            k, fam = r["mdr_report_key"], FAM[r["product_code"]]
            if term_label(fam, dterms[k], pterms[k]) != r["M1"]:
                mism.append((k, "M1"))
            for s in ("earliest", "priority"):
                if kw_label(fam, texts[k], s) != r[f"M2:{s}"]:
                    mism.append((k, f"M2:{s}"))
            for c in th:
                t = None if c == "M3:None" else float(c.split(":")[1])
                if emb_label(k, t) != r[c]:
                    mism.append((k, c))

        # F7 database + full corpus
        db_modes = dict(con.execute("SELECT mdr_report_key, mode FROM analytics.report_failure_mode").fetchall())
        full = {r["mdr_report_key"]: r["mode"] for r in read_csv(ROOT / "data" / "processed" / "full_modes.csv")}
        counts = json.loads((RES / "mode_counts.json").read_text(encoding="utf-8"))
        recount = defaultdict(Counter)
        for k, m in db_modes.items():
            recount[info[k][0]][m] += 1
        col = sel["chosen_settings"][sel["chosen"]]
        recomputed = 0
        if col == "M1":
            for k in info:
                if term_label(FAM[info[k][0]], dterms[k], pterms[k]) != db_modes.get(k):
                    mism.append((k, "full-corpus"))
                recomputed += 1
        elif col.startswith(("M2:", "M3:", "M4:")):
            s2 = col.split(":")[1].split("+")[0]
            for k in info:
                fam = FAM[info[k][0]]
                if col.startswith("M2:"):
                    mine = kw_label(fam, texts[k], s2)
                elif col.startswith("M3:"):
                    t = None if col == "M3:None" else float(col.split(":")[1])
                    mine = emb_label(k, t)
                else:
                    t3 = col.split("+")[1]
                    has_kw = kw_label(fam, texts[k], "priority") != [m for m in CB["families"][fam]["modes"] if m.endswith("_OTHER")][0]
                    mine = kw_label(fam, texts[k], s2) if has_kw else emb_label(k, None if t3 == "None" else float(t3))
                if mine != db_modes.get(k):
                    mism.append((k, "full-corpus"))
                recomputed += 1
        check("F7", "every report has one mode; DB = saved predictions = counts; chosen method recomputed independently",
              set(db_modes) == set(info) and db_modes == full and {c: dict(v) for c, v in recount.items()} ==
              {c: v for c, v in counts.items()} and not mism,
              {"reports": len(info), "db_rows": len(db_modes), "recomputed_full_corpus": recomputed,
               "mismatches": mism[:10], "n_mismatches": len(mism)})

        # F5 retrieval recomputed (own BM25, own cosine, own RRF)
        lab = {r["mdr_report_key"]: r for r in pred}
        rr = json.loads((RES / "retrieval_rankings.json").read_text(encoding="utf-8"))
        tok = lambda t: re.findall(r"[a-z0-9]+", t.lower())  # noqa: E731
        diffs = 0
        for q in rr:
            if "skipped" in q:
                continue
            cands = sorted(k for k, r in lab.items() if r["product_code"] == q["code"] and r["split"] == q["split"] and k != q["query"])
            bm = bm25_scores([tok(texts[k]) for k in cands], tok(texts[q["query"]]))
            em = [float(emb[row[q["query"]]] @ emb[row[k]]) for k in cands]
            rk = {}
            for name, sc in (("R1_bm25", bm), ("R2_embedding", em)):
                ordd = sorted(range(len(cands)), key=lambda i: (-sc[i], cands[i]))
                rk[name] = {cands[i]: n for n, i in enumerate(ordd, 1)}
            fused = {k: 1 / (60 + rk["R1_bm25"][k]) + 1 / (60 + rk["R2_embedding"][k]) for k in cands}
            rk["R3_hybrid"] = {k: n for n, k in enumerate(sorted(cands, key=lambda k: (-fused[k], k)), 1)}
            gold = lab[q["query"]]["label"]
            for name in rk:
                ranked = sorted(cands, key=lambda k: rk[name][k])
                first = next(i for i, k in enumerate(ranked, 1) if lab[k]["label"] == gold)
                if abs(1 / first - q[f"{name}_rr"]) > 1e-9 or ranked[:5] != q[f"{name}_top5"]:
                    diffs += 1
        ret = json.loads((RES / "retrieval.json").read_text(encoding="utf-8"))
        means_ok = all(abs(np.mean([q[f"{n}_rr"] for q in rr if q["split"] == s and "skipped" not in q]) - ret[s][n]["mrr"]) < 1e-4
                       for s in ("validation", "test") for n in ("R1_bm25", "R2_embedding", "R3_hybrid"))
        check("F5", "retrieval rankings and MRR recomputed with own BM25 / cosine / fusion", diffs == 0 and means_ok,
              {"queries_with_differences": diffs, "chosen": ret["chosen"], "test_mrr": {n: ret["test"][n]["mrr"] for n in ("R1_bm25", "R2_embedding", "R3_hybrid")}})

        # F6 signals recomputed from the database
        months = [f"{y}-{m:02d}" for y in (2022, 2023, 2024) for m in range(1, 13)]
        series = defaultdict(Counter)
        for k, m in db_modes.items():
            c, p, d = info[k]
            series[(c, p, m)][d.strftime("%Y-%m")] += 1
        mine = set()
        for (c, p, m), cnt in series.items():
            v = [cnt.get(x, 0) for x in months]
            for t in range(12, 36):
                lam = max(0.5, sum(v[t - 12:t]) / 12)
                if v[t] >= 5 and poisson_tail(v[t], lam) < 0.001:
                    mine.add((c, p, m, months[t], v[t]))
        sig = json.loads((RES / "signals.json").read_text(encoding="utf-8"))
        theirs = {(s["code"], s["parent"], s["mode"], s["month"], s["count"]) for s in sig["signal_list"]}
        db_sig = {tuple(r) for r in con.execute("SELECT product_code, parent_company, mode, month, count FROM analytics.signal_month").fetchall()}
        events = con.execute("""SELECT c.res_event_number, c.product_code, m.parent_company, min(c.event_date_initiated)
            FROM core.fact_recall c JOIN core.dim_manufacturer m USING (manufacturer_id)
            WHERE c.event_date_initiated BETWEEN '2023-01-01' AND '2024-12-31' AND c.res_event_number IS NOT NULL
            GROUP BY 1, 2, 3""").fetchall()
        smon = defaultdict(set)
        for c, p, m, mo, _ in mine:
            y, mm = map(int, mo.split("-"))
            smon[(c, p)].add((y - 2022) * 12 + mm - 1)
        hits = 0
        for _, c, p, start in events:
            mi = (start.year - 2022) * 12 + start.month - 1
            hits += any(mi - 6 <= x <= mi for x in smon.get((c, p), ()))
        pairs = {(c, p) for c, p, _ in series}
        win = [(pair, e) for pair in pairs for e in range(18, 36)]
        base = round(sum(any(e - 6 <= x <= e for x in smon.get(pair, ())) for pair, e in win) / len(win), 4)
        check("F6", "signals and backtest recomputed from the database (own Poisson tail)",
              mine == theirs == db_sig and hits == sig["hits"] and len(events) == sig["recall_events"] and base == sig["base_rate"],
              {"signals": len(mine), "recall_events": len(events), "hits": hits, "base_rate": base})
        con.close()

    if not offline:  # F8 = CI; locally it means the unit tests pass
        tests = subprocess.run([sys.executable, "-m", "pytest", "tests/test_phase3.py"], cwd=ROOT,
                               capture_output=True, text=True)
        check("F8", "Phase 3 unit tests pass (CI runs them plus the offline verifier)", tests.returncode == 0,
              {"pytest": tests.stdout.strip().splitlines()[-1] if tests.stdout.strip() else tests.stderr[-200:]})

    ok = all(c["pass"] for c in checks)
    passed = {c["id"] for c in checks if c["pass"]}
    card = json.loads((ROOT / "config" / "phase3_scorecard.json").read_text(encoding="utf-8"))["items"]
    scorecard = {name: all(cid in passed for cid in item["criteria"]) for name, item in card.items()}
    if evidence:
        evidence.write_text(json.dumps({"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "offline": offline, "all_pass": ok, "checks": checks,
                                        "scorecard": scorecard,
                                        "scorecard_score": f"{sum(scorecard.values())}/{len(scorecard)}"},
                                       indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    print(f"\n{sum(c['pass'] for c in checks)}/{len(checks)} checks pass")
    if not offline:
        for name, good in scorecard.items():
            print(f"  {'PASS' if good else 'FAIL'} {name}")
        print(f"Scorecard: {sum(scorecard.values())}/{len(scorecard)}")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 3 verifier")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--evidence", type=Path, default=None)
    a = ap.parse_args()
    sys.exit(main(a.offline, a.evidence or (None if a.offline else RES / "verify_phase3.json")))
