"""Phase 3 runner: failure-mode methods, selection on validation, one test run, full-corpus labels,
similar-report search evaluation, early-warning signals and the recall backtest.

Run:  python -m mdqc.run_phase3      (needs data/processed/embeddings_bge_small.npy from mdqc.embed)

Writes results/phase3/ (committed): predictions_sample.csv, selection.json, retrieval.json,
signals.json, mode_counts.json; data/processed/full_modes.csv (git-ignored); database schema
`analytics` (kept apart from `core`, which mdqc.load rebuilds): report_failure_mode, signal_month.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import psycopg
from dotenv import load_dotenv
from scipy.stats import poisson

from mdqc import embed
from mdqc import failure_modes as fm
from mdqc.textprep import load_texts

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "phase3"
PROC = ROOT / "data" / "processed"
CRIT = json.loads((ROOT / "config" / "phase3_criteria.json").read_text(encoding="utf-8"))
THRESHOLDS = [None, 0.55, 0.60, 0.65]
M2_SETTINGS = ["earliest", "priority"]
N_BOOT, SEED = 2000, 0
MONTHS = [f"{y}-{m:02d}" for y in (2022, 2023, 2024) for m in range(1, 13)]


# ---- metrics -----------------------------------------------------------------------------------------
def accuracy(gold, pred):
    return float(np.mean([g == p for g, p in zip(gold, pred)]))


def macro_f1(gold, pred):
    f1s = []
    for m in sorted(set(gold) | set(pred)):
        tp = sum(1 for g, p in zip(gold, pred) if g == m and p == m)
        fp = sum(1 for g, p in zip(gold, pred) if g != m and p == m)
        fn = sum(1 for g, p in zip(gold, pred) if g == m and p != m)
        f1s.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s))


def boot_ci(values, n=N_BOOT, seed=SEED):
    v = np.asarray(values, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(v), size=(n, len(v)))
    means = v[idx].mean(axis=1)
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


# ---- data --------------------------------------------------------------------------------------------
def load_db(con):
    rep = {k: {"code": c, "parent": p, "received": d} for k, c, p, d in con.execute(
        "SELECT r.mdr_report_key, r.product_code, m.parent_company, r.date_received FROM core.fact_report r "
        "JOIN core.dim_manufacturer m USING (manufacturer_id)").fetchall()}
    dev, pat = defaultdict(list), defaultdict(list)
    for k, t in con.execute("SELECT mdr_report_key, term FROM core.report_problem").fetchall():
        dev[k].append(t)
    for k, t in con.execute("SELECT mdr_report_key, term FROM core.report_patient_problem").fetchall():
        pat[k].append(t)
    return rep, dev, pat


def load_embeddings():
    keys = (PROC / "embeddings_bge_small_keys.txt").read_text(encoding="utf-8").split()
    emb = np.load(PROC / "embeddings_bge_small.npy").astype(np.float32)
    return keys, emb


# ---- retrieval -------------------------------------------------------------------------------------------
def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def retrieval_eval(labels, texts, vec_of):
    from rank_bm25 import BM25Okapi

    pools = defaultdict(list)
    for k, v in labels.items():
        pools[(v["code"], v["split"])].append(k)
    rows = []
    for (code, split), keys in sorted(pools.items()):
        keys = sorted(keys)
        for q in keys:
            gold = labels[q]["label"]
            if gold.endswith("_OTHER"):
                continue
            cands = [k for k in keys if k != q]
            rel = [labels[k]["label"] == gold for k in cands]
            if not any(rel):
                rows.append({"query": q, "code": code, "split": split, "skipped": "no relevant candidate"})
                continue
            bm = BM25Okapi([tokens(texts[k]) for k in cands]).get_scores(tokens(texts[q]))
            em = np.array([float(vec_of[q] @ vec_of[k]) for k in cands])
            rank = {}
            for name, sc in (("R1_bm25", bm), ("R2_embedding", em)):
                order = sorted(range(len(cands)), key=lambda i: (-sc[i], cands[i]))
                rank[name] = {cands[i]: r for r, i in enumerate(order, 1)}
            rrf = {k: 1 / (60 + rank["R1_bm25"][k]) + 1 / (60 + rank["R2_embedding"][k]) for k in cands}
            order = sorted(cands, key=lambda k: (-rrf[k], k))
            rank["R3_hybrid"] = {k: r for r, k in enumerate(order, 1)}
            row = {"query": q, "code": code, "split": split}
            for name, rk in rank.items():
                ranked = sorted(cands, key=lambda k: rk[k])
                first = next(i for i, k in enumerate(ranked, 1) if labels[k]["label"] == gold)
                row[f"{name}_rr"] = 1 / first
                row[f"{name}_p5"] = sum(labels[k]["label"] == gold for k in ranked[:5]) / 5
                row[f"{name}_top5"] = ranked[:5]
            rows.append(row)
    return rows


# ---- signals ------------------------------------------------------------------------------------------
def signals(rep, mode_of):
    series = defaultdict(Counter)
    for k, r in rep.items():
        series[(r["code"], r["parent"], mode_of[k])][r["received"].strftime("%Y-%m")] += 1
    out = []
    for (code, parent, mode), cnt in series.items():
        vals = [cnt.get(m, 0) for m in MONTHS]
        for t in range(12, len(MONTHS)):
            lam = max(0.5, float(np.mean(vals[t - 12:t])))
            c = vals[t]
            p = float(poisson.sf(c - 1, lam)) if c > 0 else 1.0
            if c >= 5 and p < 0.001:
                out.append({"code": code, "parent": parent, "mode": mode, "month": MONTHS[t], "count": c,
                            "expected": round(lam, 3), "p_value": p})
    return out, series


def month_index(d: date) -> int:
    return (d.year - 2022) * 12 + d.month - 1


def backtest(con, sigs, series):
    events = con.execute("""SELECT DISTINCT c.res_event_number, c.product_code, m.parent_company, min(c.event_date_initiated)
        FROM core.fact_recall c JOIN core.dim_manufacturer m USING (manufacturer_id)
        WHERE c.event_date_initiated BETWEEN '2023-01-01' AND '2024-12-31' AND c.res_event_number IS NOT NULL
        GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""").fetchall()
    sig_months = defaultdict(set)
    for s in sigs:
        y, m = map(int, s["month"].split("-"))
        sig_months[(s["code"], s["parent"])].add((y - 2022) * 12 + m - 1)
    rows = []
    for ev, code, parent, start in events:
        mi = month_index(start)
        hit = any(mi - 6 <= x <= mi for x in sig_months.get((code, parent), ()))
        rows.append({"event": ev, "code": code, "parent": parent, "initiated": str(start), "hit": hit,
                     "pair_has_reports": any(k[0] == code and k[1] == parent for k in series)})
    pairs = sorted({(k[0], k[1]) for k in series})
    windows = hits = 0
    for pair in pairs:
        for end in range(month_index(date(2023, 7, 1)), month_index(date(2024, 12, 1)) + 1):
            windows += 1
            hits += any(end - 6 <= x <= end for x in sig_months.get(pair, ()))
    return rows, {"windows": windows, "windows_with_signal": hits, "base_rate": round(hits / windows, 4)}


# ---- main ---------------------------------------------------------------------------------------------
def main() -> dict:
    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    labels = {r["mdr_report_key"]: {"code": r["product_code"], "split": r["split"], "label": r["label"]}
              for r in csv.DictReader(open(ROOT / "config" / "phase3_labels.csv", encoding="utf-8"))}
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        rep, dev, pat = load_db(con)
        texts = load_texts(con)
        keys, emb = load_embeddings()
        assert set(keys) == set(rep), "embeddings are stale: re-run python -m mdqc.embed"
        vec_of = {k: emb[i] for i, k in enumerate(keys)}
        model = embed.load_model()
        revision = embed.model_revision(model)
        defs = {}
        for fam in fm.CODEBOOK["families"]:
            modes, d = fm.mode_definitions(fam)
            defs[fam] = (modes, embed.encode(model, d, query=True))
        # saved so the verifier can recompute M3 without the model (small: modes x 384 floats)
        np.savez(OUT / "mode_definition_vectors.npz", **{f"{fam}__{m}": v for fam, (ms, dv) in defs.items()
                                                         for m, v in zip(ms, dv)})

        # predictions for every report and every method/setting
        codes = {k: r["code"] for k, r in rep.items()}
        clusters = fm.m5_clusters(texts, codes)
        val_labels = {k: v["label"] for k, v in labels.items() if v["split"] == "validation"}
        names = fm.m5_names(clusters, val_labels, codes)
        preds = defaultdict(dict)  # method/setting -> key -> mode
        for k, r in rep.items():
            fam = fm.family(r["code"])
            t = texts[k]
            preds["M1"][k] = fm.m1(fam, dev.get(k, []), pat.get(k, []))
            for s in M2_SETTINGS:
                preds[f"M2:{s}"][k] = fm.m2(fam, t, s)
            modes, dv = defs[fam]
            for th in THRESHOLDS:
                preds[f"M3:{th}"][k] = fm.m3(fam, vec_of[k], dv, modes, th)
            preds["M5"][k] = names[clusters[k]]

        def score(method_key, split):
            ks = [k for k, v in labels.items() if v["split"] == split]
            return accuracy([labels[k]["label"] for k in ks], [preds[method_key][k] for k in ks])

        best_m2 = max(M2_SETTINGS, key=lambda s: (score(f"M2:{s}", "validation"), -M2_SETTINGS.index(s)))
        best_m3 = max(THRESHOLDS, key=lambda th: (score(f"M3:{th}", "validation"), -THRESHOLDS.index(th)))
        m4_key = f"M4:{best_m2}+{best_m3}"
        for k, r in rep.items():
            preds[m4_key][k] = fm.m4(fm.family(r["code"]), texts[k], best_m2, preds[f"M3:{best_m3}"][k])
        chosen_setting = {"M1": "M1", "M2": f"M2:{best_m2}", "M3": f"M3:{best_m3}", "M4": m4_key, "M5": "M5"}
        val = {m: round(score(key, "validation"), 4) for m, key in chosen_setting.items()}
        all_settings_val = {key: round(score(key, "validation"), 4) for key in preds}
        chosen = max(fm.METHOD_ORDER, key=lambda m: (val[m], -fm.METHOD_ORDER.index(m)))

        # test, once
        test_keys = sorted(k for k, v in labels.items() if v["split"] == "test")
        gold = [labels[k]["label"] for k in test_keys]
        test = {}
        correct = {}
        for m, key in chosen_setting.items():
            p = [preds[key][k] for k in test_keys]
            correct[m] = [int(g == x) for g, x in zip(gold, p)]
            per_fam = {}
            for fam in fm.CODEBOOK["families"]:
                idx = [i for i, k in enumerate(test_keys) if fm.family(labels[k]["code"]) == fam]
                per_fam[fam] = round(float(np.mean([correct[m][i] for i in idx])), 4)
            test[m] = {"setting": key, "accuracy": round(float(np.mean(correct[m])), 4),
                       "accuracy_ci95": boot_ci(correct[m]), "macro_f1": round(macro_f1(gold, p), 4),
                       "accuracy_by_family": per_fam}
        diff = [a - b for a, b in zip(correct[chosen], correct["M1"])]
        cmp = {"chosen": chosen, "baseline": "M1", "difference": round(float(np.mean(diff)), 4),
               "difference_ci95": boot_ci(diff)}
        cmp["chosen_better"] = bool(cmp["difference_ci95"][0] > 0) if chosen != "M1" else False

        # save sample predictions
        with open(OUT / "predictions_sample.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            cols = sorted(preds)
            w.writerow(["mdr_report_key", "product_code", "split", "label"] + cols)
            for k in sorted(labels):
                w.writerow([k, labels[k]["code"], labels[k]["split"], labels[k]["label"]] + [preds[c][k] for c in cols])

        # full corpus with the chosen method
        mode_of = preds[chosen_setting[chosen]]
        with open(PROC / "full_modes.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["mdr_report_key", "mode"])
            w.writerows(sorted(mode_of.items()))
        con.execute("CREATE SCHEMA IF NOT EXISTS analytics")
        con.execute("DROP TABLE IF EXISTS analytics.report_failure_mode")
        con.execute("""CREATE TABLE analytics.report_failure_mode (mdr_report_key text PRIMARY KEY,
                       product_code text NOT NULL, mode text NOT NULL, method text NOT NULL)""")
        with con.cursor().copy("COPY analytics.report_failure_mode FROM STDIN") as cp:
            for k in sorted(mode_of):
                cp.write_row((k, rep[k]["code"], mode_of[k], chosen_setting[chosen]))
        mode_counts = defaultdict(Counter)
        for k, m in mode_of.items():
            mode_counts[rep[k]["code"]][m] += 1

        # retrieval
        rrows = retrieval_eval(labels, texts, vec_of)
        ret = {}
        for split in ("validation", "test"):
            rs = [r for r in rrows if r["split"] == split and "skipped" not in r]
            ret[split] = {name: {"mrr": round(float(np.mean([r[f"{name}_rr"] for r in rs])), 4),
                                 "p_at_5": round(float(np.mean([r[f"{name}_p5"] for r in rs])), 4),
                                 "mrr_ci95": boot_ci([r[f"{name}_rr"] for r in rs])}
                          for name in ("R1_bm25", "R2_embedding", "R3_hybrid")}
            ret[split]["queries"] = len(rs)
            ret[split]["skipped_no_relevant"] = sum(1 for r in rrows if r["split"] == split and "skipped" in r)
        r_order = ["R1_bm25", "R2_embedding", "R3_hybrid"]
        r_chosen = max(r_order, key=lambda n: (ret["validation"][n]["mrr"], -r_order.index(n)))
        rs = [r for r in rrows if r["split"] == "test" and "skipped" not in r]
        rdiff = [r[f"{r_chosen}_rr"] - r["R1_bm25_rr"] for r in rs]
        ret["chosen"] = r_chosen
        ret["chosen_vs_bm25_test"] = {"difference": round(float(np.mean(rdiff)), 4), "ci95": boot_ci(rdiff),
                                      "chosen_better": bool(boot_ci(rdiff)[0] > 0) if r_chosen != "R1_bm25" else False}
        with open(OUT / "retrieval_rankings.json", "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rrows, fh, indent=1)

        # signals + backtest
        sigs, series = signals(rep, mode_of)
        con.execute("DROP TABLE IF EXISTS analytics.signal_month")
        con.execute("""CREATE TABLE analytics.signal_month (product_code text, parent_company text, mode text,
                       month text, count integer, expected double precision, p_value double precision,
                       PRIMARY KEY (product_code, parent_company, mode, month))""")
        with con.cursor().copy("COPY analytics.signal_month FROM STDIN") as cp:
            for s in sigs:
                cp.write_row((s["code"], s["parent"], s["mode"], s["month"], s["count"], s["expected"], s["p_value"]))
        bt_rows, base = backtest(con, sigs, series)
        con.commit()

    hits = sum(r["hit"] for r in bt_rows)
    sig_summary = {"signals": len(sigs), "signals_per_year": round(len(sigs) / 2, 1),
                   "series": len(series), "series_with_signal": len({(s['code'], s['parent'], s['mode']) for s in sigs}),
                   "by_code": dict(Counter(s["code"] for s in sigs)),
                   "recall_events": len(bt_rows), "hits": hits,
                   "hit_rate": round(hits / len(bt_rows), 4) if bt_rows else None, **base,
                   "events": bt_rows, "signal_list": sorted(sigs, key=lambda s: (s["code"], s["parent"], s["mode"], s["month"]))}
    selection = {"model": embed.MODEL_NAME, "model_revision": revision, "validation_accuracy": val,
                 "validation_accuracy_all_settings": all_settings_val, "chosen_settings": chosen_setting,
                 "chosen": chosen, "test": test, "chosen_vs_m1_test": cmp,
                 "n": {"validation": sum(v["split"] == "validation" for v in labels.values()), "test": len(test_keys)}}
    for name, obj in (("selection", selection), ("retrieval", ret), ("signals", sig_summary),
                      ("mode_counts", {c: dict(sorted(v.items())) for c, v in sorted(mode_counts.items())})):
        (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"validation": val, "chosen": chosen, "test": {m: test[m]["accuracy"] for m in test},
                      "vs_M1": cmp, "retrieval_chosen": r_chosen,
                      "retrieval_test_mrr": {n: ret["test"][n]["mrr"] for n in r_order},
                      "signals": len(sigs), "recall_hits": f"{hits}/{len(bt_rows)}", "base_rate": base["base_rate"]}, indent=1))
    return selection


if __name__ == "__main__":
    main()
