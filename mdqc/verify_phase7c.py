"""Phase 7c verification (checks D1-D9 in config/phase7c_criteria.json). Needs the database and raw files; writes results/phase7c/verify_phase7c.json.

Run:  python -m mdqc.verify_phase7c

Rows are rebuilt from the raw files by this file's own code (no mdqc.load). Same author as the loader.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "phase7c"
CODES = ["LPH", "JWH", "MBH", "LWP", "LZG"]


def lines(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def count(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return sum(1 for x in f if x.strip())


def day(s):
    try:
        return datetime.strptime(s, "%Y%m%d").date() if isinstance(s, str) and len(s) == 8 and s.isdigit() else None
    except ValueError:
        return None


def val(v):
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v if x)
    return (v.strip() if isinstance(v, str) else v) or None


def expected(code):
    """(reports, problems, patient problems, texts) that should be loaded for a product, rebuilt from raw_all."""
    R, P, Q, T, bad, seen = {}, set(), set(), {}, 0, set()
    for r in lines(ROOT / "data/raw_all" / f"events_{code}.jsonl.gz"):
        k, rec = r.get("mdr_report_key"), day(r.get("date_received"))
        d = [x for x in r.get("device") or [] if x.get("device_report_product_code") == code]
        et, tx = (r.get("event_type") or "").strip(), r.get("mdr_text") or []
        dup = not k or k in seen
        seen.add(k)
        if dup or rec is None or not date(2022, 1, 1) <= rec <= date(2026, 12, 31) or not d or et not in ("", "Malfunction", "Injury", "Death", "Other") \
                or (rec <= date(2024, 12, 31) and not any((x.get("text") or "").strip() for x in tx)):
            bad += 1
            continue
        ev, rawev = day(r.get("date_of_event")), (r.get("date_of_event") or "").strip()
        flag = "missing" if not rawev else "invalid" if ev is None else "after_received" if ev > rec else "ok"
        R[k] = (val(r.get("report_number")), code, d[0].get("manufacturer_d_name") or "", rec, ev, flag, (rec - ev).days if ev else None, et or "Not provided",
                val(r.get("report_source_code")), val(r.get("type_of_report")), (r.get("pma_pmn_number") or "").strip().upper() or None, val(d[0].get("brand_name")),
                val(d[0].get("generic_name")), val(d[0].get("model_number")), val(d[0].get("lot_number")), len(r.get("device") or []), len(r.get("patient") or []),
                val(r.get("adverse_event_flag")), val(r.get("product_problem_flag")))
        P |= {(k, t) for t in r.get("product_problems") or [] if t}
        Q |= {(k, t) for p in r.get("patient") or [] for t in p.get("patient_problems") or [] if t}
        for i, x in enumerate(tx, 1):
            T[(k, i)] = hashlib.md5(((val(x.get("text_type_code")) or "") + "|" + (x.get("text") or "")).encode()).hexdigest()
    return R, P, Q, T, bad


COLS = ("report_number, product_code, m.raw_name, date_received, date_of_event, event_date_flag, lag_days, event_type, report_source_code, type_of_report, "
        "pma_pmn_number, brand_name, generic_name, model_number, lot_number, n_devices, n_patients, adverse_event_flag, product_problem_flag")


def main() -> int:
    import psycopg
    from dotenv import load_dotenv

    from mdqc.fingerprint import fingerprints
    from mdqc.tools import MODES, run_tool

    load_dotenv(ROOT / ".env")
    con = psycopg.connect(os.environ["DATABASE_URL"])
    q = lambda s, *a: con.execute(s, a).fetchall()  # noqa: E731
    checks = []

    def check(cid, name, ok, detail):
        checks.append({"id": cid, "check": name, "pass": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {cid} {name}: {json.dumps(detail, default=str)[:330]}", flush=True)

    # D1 + D2
    man = json.loads((RES / "raw_manifest.json").read_text(encoding="utf-8"))
    d1, d1ok, diffs, n = {}, True, Counter(), Counter()
    for c in CODES:
        R, P, Q, T, bad = expected(c)
        old, new = count(ROOT / "data/raw" / f"events_{c}.jsonl.gz"), count(ROOT / "data/raw_new" / f"events_{c}.jsonl.gz")
        db = {r[0]: r[1:] for r in q(f"SELECT mdr_report_key, {COLS} FROM core_all.fact_report r JOIN core_all.dim_manufacturer m USING (manufacturer_id) WHERE product_code = %s", c)}
        quar = q("SELECT count(*) FROM core_all.quarantine WHERE source = %s", f"events_{c}.jsonl.gz")[0][0]
        rc = man["recalls"][c]
        rdb = q("SELECT count(*) FROM core_all.fact_recall WHERE product_code = %s", c)[0][0]
        rq = q("SELECT count(*) FROM core_all.quarantine WHERE source = %s", f"recalls_{c}.jsonl.gz")[0][0]
        d1[c] = {"old": old, "new": new, "loaded": len(db), "quarantined": quar, "recalls": f"{rdb}+{rq}/{rc['server_total']}"}
        d1ok &= old + new == len(db) + quar and quar == bad and rc["server_total"] == rc["downloaded"] == rdb + rq
        diffs["reports"] += sum(db.get(k) != v for k, v in R.items()) + len(set(db) - set(R))
        for name, want, sql in (("problems", P, "report_problem"), ("patient_problems", Q, "report_patient_problem")):
            got = set(q(f"SELECT p.mdr_report_key, p.term FROM core_all.{sql} p JOIN core_all.fact_report USING (mdr_report_key) WHERE product_code = %s", c))
            diffs[name] += len(got ^ want)
            n[name] += len(want)
        tx = {(a, b): h for a, b, h in q("SELECT t.mdr_report_key, text_seq, md5(coalesce(text_type, '') || '|' || text) FROM core_all.report_text t "
                                         "JOIN core_all.fact_report USING (mdr_report_key) WHERE product_code = %s", c)}
        diffs["texts"] += sum(tx.get(k) != h for k, h in T.items()) + len(set(tx) - set(T))
        n["reports"] += len(R)
        n["texts"] += len(T)
        want = {}
        for r in lines(ROOT / "data/raw_all" / f"recalls_{c}.jsonl.gz"):
            want.setdefault((r.get("product_res_number") or "").strip(), r)
        for prn, firm, start, status, cause, reason, prod, ks in q("SELECT product_res_number, m.raw_name, event_date_initiated, recall_status, root_cause, reason_for_recall, "
                                                                  "product_description, k_numbers FROM core_all.fact_recall JOIN core_all.dim_manufacturer m USING (manufacturer_id) WHERE product_code = %s", c):
            r = want[prn]
            n["recalls"] += 1
            okd = str(start) == r.get("event_date_initiated") or (r.get("event_date_initiated") or "9999")[:4] < "1976"
            diffs["recalls"] += not (okd and firm == (r.get("recalling_firm") or "") and status == val(r.get("recall_status")) and cause == val(r.get("root_cause_description"))
                                     and reason == val(r.get("reason_for_recall")) and prod == val(r.get("product_description"))
                                     and ks == sorted({k.strip().upper() for k in r.get("k_numbers") or [] if k and k.strip()}))
    check("D1", "loaded + quarantined = raw lines; recalls = openFDA totals", d1ok, d1)
    check("D2", "every row rebuilt from raw", not any(diffs.values()) and n["reports"] > 230000, {"compared": dict(n), "differences": dict(diffs)})

    # D3
    before = json.loads((RES / "fingerprint_before.json").read_text(encoding="utf-8"))
    after = fingerprints(con, ["core", "analytics", "memory"])
    check("D3", "core, analytics and memory unchanged", before == after, {"tables": len(after), "changed": [k for k in before if before[k] != after.get(k)]})

    # D4
    d4 = {}
    sel = "SELECT r.mdr_report_key, " + COLS + " FROM {s}.fact_report r JOIN {s}.dim_manufacturer m USING (manufacturer_id)"
    d4["reports missing or different"] = q(f"SELECT count(*) FROM ({sel.format(s='core')} EXCEPT {sel.format(s='core_all')}) x")[0][0]
    d4["2022-2024 reports only in core_all"] = q("SELECT count(*) FROM core_all.fact_report a WHERE date_received <= '2024-12-31' AND NOT EXISTS (SELECT 1 FROM core.fact_report c WHERE c.mdr_report_key = a.mdr_report_key)")[0][0]
    d4["modes different"] = q("SELECT count(*) FROM (SELECT mdr_report_key, mode FROM analytics.report_failure_mode EXCEPT SELECT mdr_report_key, mode FROM analytics_all.report_failure_mode) x")[0][0]
    d4["parents different"] = q("SELECT count(*) FROM core.dim_manufacturer a JOIN core_all.dim_manufacturer b USING (raw_name) WHERE a.parent_company <> b.parent_company")[0][0]
    check("D4", "2022-2024 part equals core", not any(d4.values()), d4)

    # D5
    tot, modes = q("SELECT count(*) FROM core_all.fact_report")[0][0], q("SELECT count(*), count(DISTINCT mdr_report_key) FROM analytics_all.report_failure_mode")[0]
    drift = json.loads((ROOT / "results/phase7/drift_check.json").read_text(encoding="utf-8"))["rows"]
    dbq = {(c, p): k for c, p, k in q("SELECT product_code, to_char(date_received, 'YYYY\"Q\"Q'), count(*) FROM core_all.fact_report WHERE date_received >= '2025-01-01' GROUP BY 1, 2")}
    quar = Counter()
    for src, raw in q("SELECT source, raw ->> 'date_received' FROM core_all.quarantine WHERE source LIKE 'events%%'"):
        quar[(src[7:10], f"{raw[:4]}Q{(int(raw[4:6]) - 1) // 3 + 1}")] += 1
    off = [(r["code"], r["quarter"]) for r in drift if dbq.get((r["code"], r["quarter"]), 0) + quar[(r["code"], r["quarter"])] != r["reports"]]
    book = json.loads((ROOT / "config/failure_modes.json").read_text(encoding="utf-8"))
    terms: dict = {}
    for k, t in q("SELECT mdr_report_key, term FROM core_all.report_problem UNION ALL SELECT mdr_report_key, 'patient:' || term FROM core_all.report_patient_problem"):
        terms.setdefault(k, []).append(t)
    wrong = 0
    for k, c, m in q("SELECT mdr_report_key, product_code, mode FROM analytics_all.report_failure_mode"):
        fam, spec = next((f, v) for f, v in book["families"].items() if c in v["codes"])
        hit = {book["fda_term_map"][fam].get(t) for t in terms.get(k, [])}
        wrong += m != next((x for x in spec["priority"] if x in hit), next(x for x in spec["modes"] if x.endswith("_OTHER")))
    sig_core = set(q("SELECT product_code, parent_company, mode, month, count FROM analytics.signal_month"))
    sig_all = set(q("SELECT product_code, parent_company, mode, month, count FROM analytics_all.signal_month"))
    check("D5", "one mode per report, recomputed; quarter counts equal the drift check; old signals reproduced",
          modes == (tot, tot) and not off and wrong == 0 and sig_core == {s for s in sig_all if s[3] <= "2024-12"},
          {"reports": tot, "quarter_mismatches": off, "modes_recomputed_wrong": wrong, "signals": f"{len(sig_core)} old reproduced, {len(sig_all)} in all"})

    # D6
    same = calls = 0
    for p in sorted((ROOT / "results/phase6").glob("claude-*/*.json")):
        for t in json.loads(p.read_text(encoding="utf-8"))["tool_calls"]:
            if not t["is_error"] and t["name"] not in ("remember", "recall", "update_memory", "forget"):
                calls += 1
                same += json.loads(run_tool(con, t["name"], t["input"])[0]) == json.loads(t["result"])
    rng, gen, bad = random.Random(5), 0, []
    makers = {c: [r[0] for r in q("SELECT m.parent_company FROM core_all.fact_report JOIN core_all.dim_manufacturer m USING (manufacturer_id) WHERE product_code = %s "
                                  "GROUP BY 1 ORDER BY count(*) DESC LIMIT 4", c)] for c in CODES}
    fam_modes = {c: next(list(v["modes"]) for v in book["families"].values() if c in v["codes"]) for c in CODES}
    for i in range(75):
        c, name = rng.choice(CODES), ("count_reports", "trend", "failure_modes", "list_manufacturers", "find_recalls")[i % 5]
        d0 = date(2022, 1, 1) + timedelta(days=rng.randrange(1500))
        d1_ = d0 + timedelta(days=rng.randrange(30, 900))
        a = {"product_code": c, "date_from": str(d0), "date_to": str(d1_)}
        if name != "list_manufacturers" and rng.random() < 0.6:
            a["manufacturer"] = rng.choice(makers[c])
        if name in ("count_reports", "trend", "list_manufacturers") and rng.random() < 0.5:
            a["failure_mode"] = rng.choice(fam_modes[c])
        out, err = run_tool(con, name, a, scope="all")
        r = json.loads(out)
        gen += 1
        if err:
            bad.append((name, a, out))
            continue
        if name == "find_recalls":
            w = q("SELECT count(*), count(DISTINCT res_event_number) FROM core_all.fact_recall c, core_all.dim_manufacturer m WHERE c.manufacturer_id = m.manufacturer_id AND product_code = %s "
                  "AND event_date_initiated >= %s AND event_date_initiated <= %s AND (%s::text IS NULL OR parent_company = %s)", c, d0, d1_, a.get("manufacturer"), a.get("manufacturer"))[0]
            ok = (r["recall_records"], r["recall_events"]) == w
        else:
            rows = q("SELECT r.event_type, r.date_received, m.parent_company, f.mode FROM core_all.fact_report r, core_all.dim_manufacturer m, analytics_all.report_failure_mode f "
                     "WHERE r.manufacturer_id = m.manufacturer_id AND f.mdr_report_key = r.mdr_report_key AND r.product_code = %s", c)
            rows = [x for x in rows if d0 <= x[1] <= min(d1_, date(2026, 12, 31)) and a.get("manufacturer") in (None, x[2]) and a.get("failure_mode") in (None, x[3])]
            if name == "count_reports":
                ok = r["reports"] == len(rows) and {x["event_type"]: x["reports"] for x in r["by_event_type"]} == Counter(x[0] for x in rows)
            elif name == "trend":
                ok = {x["period"]: x["reports"] for x in r["series"]} == Counter(f"{x[1].year}-Q{(x[1].month - 1) // 3 + 1}" for x in rows)
            elif name == "failure_modes":
                ok = {x["failure_mode"]: x["reports"] for x in r["modes"]} == Counter(x[3] for x in rows) and set(Counter(x[3] for x in rows)) <= set(MODES)
            else:
                cnt = Counter(x[2] for x in rows)
                ok = r["total_reports"] == len(rows) and [(x["manufacturer"], x["reports"]) for x in r["manufacturers"]] == sorted(cnt.items(), key=lambda z: (-z[1], z[0]))[:15]
        if not ok:
            bad.append((name, a))
    pages, seen = [], 0
    while True:
        r = json.loads(run_tool(con, "find_recalls", {"product_code": "JWH", "manufacturer": "Exactech", "offset": seen}, scope="all")[0])
        pages += [x["recall_number"] for x in r["recalls"]]
        seen += 10
        if len(r["recalls"]) < 10 or seen > 100:
            break
    longest = q("SELECT mdr_report_key FROM core_all.report_text GROUP BY 1 ORDER BY sum(length(text)) DESC, 1 LIMIT 1")[0][0]
    first = json.loads(run_tool(con, "get_report", {"mdr_report_key": longest}, scope="all")[0])
    whole = "".join(json.loads(run_tool(con, "get_report", {"mdr_report_key": longest, "text_part": i}, scope="all")[0])["narrative"] for i in range(1, first["narrative_parts"] + 1))
    stored = sum(len(" ".join(t.split())) for (t,) in q("SELECT text FROM core_all.report_text WHERE mdr_report_key = %s", longest))
    errs = [run_tool(con, n_, a_, scope="all")[1] for n_, a_ in (("find_recalls", {"offset": 500}), ("find_recalls", {"offset": "x"}), ("get_report", {"mdr_report_key": longest, "text_part": 9999}),
            ("count_reports", {"offset": 1}), ("search_reports", {"query": "leak", "offset": -1}), ("get_report", {"mdr_report_key": "1"}), ("count_reports", {"date_from": "2025-13-01"}))]
    default_errs = [run_tool(con, "find_recalls", {"offset": 10})[1], run_tool(con, "get_report", {"mdr_report_key": longest, "text_part": 1})[1]]
    check("D6", "default scope identical; scope 'all' equals separate SQL; paging and full narratives; bad arguments refused",
          same == calls and gen >= 60 and not bad and len(pages) == len(set(pages)) == r["recall_records"] and len(whole) >= stored and all(errs) and all(default_errs),
          {"recorded_calls_identical": f"{same}/{calls}", "generated_calls": gen, "mismatches": bad[:3], "recall_pages": f"{len(pages)}/{r['recall_records']}",
           "longest_narrative": f"{len(whole)} characters in {first['narrative_parts']} parts", "bad_arguments_refused": f"{sum(errs)}/{len(errs)}"})

    # D7
    proc = ROOT / "data/processed"
    keys = (proc / "embeddings_all_keys.txt").read_text(encoding="utf-8").split()
    emb, old = np.load(proc / "embeddings_all.npy", mmap_mode="r"), np.load(proc / "embeddings_bge_small.npy", mmap_mode="r")
    from mdqc import embed
    from mdqc.textprep import load_texts
    with_text = q("SELECT count(DISTINCT mdr_report_key) FROM core_all.report_text WHERE text ~ '[^[:space:]]'")[0][0]
    pick = random.Random(3).sample(range(len(old), len(keys)), 100)
    tx = load_texts(con, "core_all", [keys[i] for i in pick])
    model = embed.load_model()
    v = np.stack([embed.encode(model, [tx[keys[i]]])[0] for i in pick])
    e = np.stack([np.asarray(emb[i], np.float32) for i in pick])
    cos = (v * e).sum(1) / np.linalg.norm(v, axis=1) / np.linalg.norm(e, axis=1)
    check("D7", "one vector per report; old vectors identical; sample re-encoded", len(keys) == len(set(keys)) == emb.shape[0] == with_text and np.array_equal(emb[: len(old)], old)
          and keys[: len(old)] == (proc / "embeddings_bge_small_keys.txt").read_text(encoding="utf-8").split() and cos.min() >= 0.999,
          {"vectors": int(emb.shape[0]), "reports_with_narrative": with_text, "reports": tot, "lowest_cosine": round(float(cos.min()), 6)})

    # D8
    cols = q("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'core_all' AND column_name ~ 'contact|phone|patient_(age|sex|weight|race|ethn)|reporter_(name|state)'")
    quar_keys = q("SELECT count(*) FROM core_all.quarantine WHERE raw::text ~ '\"manufacturer_contact_|\"patient_(age|sex|weight|race|ethnicity)\"'")[0][0]
    hits = tried = 0
    sample = random.Random(9).sample(lines(ROOT / "data/raw_new/events_LWP.jsonl.gz"), 150) + random.Random(9).sample(lines(ROOT / "data/raw_new/events_LZG.jsonl.gz"), 150)
    for r in sample:
        phone, name = r.get("manufacturer_contact_phone_number") or "", r.get("manufacturer_contact_l_name") or ""
        row = " ".join(str(x) for x in (q("SELECT r::text FROM core_all.fact_report r WHERE mdr_report_key = %s", r["mdr_report_key"]) or [("",)])[0])
        for s in (phone, name):
            if len(s) >= 5 and s.lower() not in ("unknown", "other"):
                tried += 1
                hits += re.search(r"(?<![0-9A-Za-z])" + re.escape(s) + r"(?![0-9A-Za-z])", row, re.I) is not None
    check("D8", "no contact or demographic columns; sampled contacts absent", not cols and quar_keys == 0 and tried > 50 and hits == 0,
          {"columns": cols, "quarantine_rows_with_personal_keys": quar_keys, "values_tried": tried, "found_in_rows": hits})

    # D9
    from mdqc import load as loader
    tmp = Path(tempfile.mkdtemp())
    for f in (ROOT / "tests/fixtures/phase1/raw").glob("*.jsonl.gz"):
        shutil.copy(f, tmp / f.name)
    rec = lines(tmp / "events_LPH.jsonl.gz")
    base_key = rec[0]["mdr_report_key"]
    rec[0]["product_problems"] = [None, "Fracture"]
    late = {**rec[1], "mdr_report_key": "99999901", "date_received": "20270101"}
    ok26 = {**rec[1], "mdr_report_key": "99999902", "date_received": "20260615"}
    with gzip.open(tmp / "events_LPH.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(x) for x in rec + [dict(rec[2]), late, ok26]) + "\n")
    t = loader.build(tmp, date(2026, 12, 31))
    rules = Counter((x[1], x[2]) for x in t["quarantine"])
    plain = loader.build(tmp)
    check("D9", "planted null term, duplicate and late date handled; default window unchanged",
          (base_key, "Fracture") in t["problem"] and not any(x[1] is None for x in t["problem"]) and rules[(rec[2]["mdr_report_key"], "R1")] == 1 and rules[("99999901", "R2")] == 1
          and any(x["mdr_report_key"] == "99999902" for x in t["report"]) and any(x[1] == "99999902" and x[2] == "R2" for x in plain["quarantine"]), {"quarantined": [list(k) for k in rules]})
    shutil.rmtree(tmp)
    con.rollback()
    con.close()
    out = {"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "passed": f"{sum(c['pass'] for c in checks)}/{len(checks)}", "checks": checks}
    (RES / "verify_phase7c.json").write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    print(out["passed"])
    return 0 if all(c["pass"] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
