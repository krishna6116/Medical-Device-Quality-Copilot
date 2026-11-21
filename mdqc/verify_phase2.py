"""Phase 2 independent verification (criteria P1-P9 in config/phase2_criteria.json).

Run:  python -m mdqc.verify_phase2                         full data vs schema core (writes evidence)
      python -m mdqc.verify_phase2 --raw tests/fixtures/phase1/raw --schema fixture --fixture   CI: fixture, no Phase 1 check

Independence: this file never imports mdqc.load. It re-reads the raw files with its own parser,
re-implements every rule from config/phase2_criteria.json and config/manufacturer_aliases.json,
rebuilds every table's rows and compares them with what is in PostgreSQL. It runs the loader only
as a black box (subprocess) for the idempotence (P4) and planted-fault (P5) tests.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SCOPE = json.loads((ROOT / "config" / "scope.json").read_text(encoding="utf-8"))
ALIASES = json.loads((ROOT / "config" / "manufacturer_aliases.json").read_text(encoding="utf-8"))
CODES = list(SCOPE["product_codes"])
WF, WT = SCOPE["event_window"]["from"], SCOPE["event_window"]["to"]
DROPPED_COLUMN_WORDS = ("contact", "patient_age", "patient_sex", "patient_weight", "patient_race", "patient_ethnicity")


# ---- independent re-implementation of the rules ---------------------------------------------------
def to_date(s, fmt):
    try:
        return datetime.strptime(s, fmt).date() if isinstance(s, str) and s else None
    except ValueError:
        return None


def blank_to_none(v):
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v if x)
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v if v else None


def clean(name):
    s = (name or "").upper()
    parts = s.rsplit("-", 1)
    if len(parts) == 2 and parts[1].strip().isdigit() and parts[0].endswith(" "):
        s = parts[0]
    s = "".join(ch if (ch.isascii() and ch.isalnum()) or ch in "& " else " " for ch in s)
    words = s.split()
    suffixes = [x.split() for x in ALIASES["legal_suffixes"]]
    trimmed = True
    while trimmed and words:
        trimmed = False
        for suf in sorted(suffixes, key=lambda w: -len(" ".join(w))):
            if len(words) > len(suf) and words[-len(suf):] == suf:
                words = words[:-len(suf)]
                trimmed = True
                break
    return " ".join(words)


def parent(clean_name):
    if not clean_name:
        return "(BLANK)"
    padded = f" {clean_name} "
    for rule in ALIASES["parents"]:
        if any(f" {p} " in padded for p in rule["patterns"]):
            return rule["parent"]
    return clean_name


def lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def expected(raw: Path) -> dict:
    exp = defaultdict(list)
    quarantine, makers, raw_counts = [], set(), {}
    for code in CODES:
        name, seen = f"events_{code}.jsonl.gz", set()
        recs = lines(raw / name)
        raw_counts[name] = len(recs)
        for r in recs:
            key = r.get("mdr_report_key")
            dr = to_date(r.get("date_received"), "%Y%m%d") if len(r.get("date_received") or "") == 8 else None
            devs = r.get("device") or []
            mine = [d for d in devs if d.get("device_report_product_code") == code]
            et = (r.get("event_type") or "").strip()
            has_text = any((t.get("text") or "").strip() for t in (r.get("mdr_text") or []))
            if not key or key in seen:
                rule = "R1"
            elif dr is None or not (WF <= r["date_received"] <= WT):
                rule = "R2"
            elif not mine:
                rule = "R3"
            elif et and et not in ("Malfunction", "Injury", "Death", "Other"):
                rule = "R4"
            elif not has_text:
                rule = "R5"
            else:
                rule = None
            if key:
                seen.add(key)
            if rule:
                quarantine.append((name, key, rule))
                continue
            m = mine[0]
            de_raw = (r.get("date_of_event") or "").strip()
            de = to_date(de_raw, "%Y%m%d") if len(de_raw) == 8 and de_raw.isdigit() else None
            flag = "missing" if not de_raw else ("invalid" if de is None else ("after_received" if de > dr else "ok"))
            maker = m.get("manufacturer_d_name") or ""
            makers.add(maker)
            exp["fact_report"].append((
                key, blank_to_none(r.get("report_number")), code, maker, dr, de, flag,
                (dr - de).days if de else None, et or "Not provided", blank_to_none(r.get("report_source_code")),
                blank_to_none(r.get("type_of_report")), ((r.get("pma_pmn_number") or "").strip().upper() or None),
                blank_to_none(m.get("brand_name")), blank_to_none(m.get("generic_name")),
                blank_to_none(m.get("model_number")), blank_to_none(m.get("lot_number")), len(devs),
                len(r.get("patient") or []), blank_to_none(r.get("adverse_event_flag")),
                blank_to_none(r.get("product_problem_flag"))))
            for i, d in enumerate(devs, start=1):
                exp["report_device"].append((key, i) + tuple(blank_to_none(d.get(f)) for f in (
                    "device_report_product_code", "brand_name", "generic_name", "manufacturer_d_name",
                    "model_number", "catalog_number", "lot_number", "implant_flag")))
            exp["report_problem"] += [(key, t) for t in set(r.get("product_problems") or [])]
            exp["report_patient_problem"] += [(key, t) for t in
                                              {t for p in (r.get("patient") or []) for t in (p.get("patient_problems") or [])}]
            exp["report_text"] += [(key, i, blank_to_none(t.get("text_type_code")), t.get("text") or "")
                                   for i, t in enumerate(r.get("mdr_text") or [], start=1)]
    for code in CODES:
        name, seen = f"recalls_{code}.jsonl.gz", set()
        recs = lines(raw / name)
        raw_counts[name] = len(recs)
        for r in recs:
            prn = (r.get("product_res_number") or "").strip()
            ini_raw, posted = r.get("event_date_initiated") or "", to_date(r.get("event_date_posted"), "%Y-%m-%d")
            ini, repaired = to_date(ini_raw, "%Y-%m-%d"), False
            if ini is None or ini.year < 1976:
                ini = None
                if posted and len(ini_raw) == 10:
                    try:
                        ini = date(posted.year, int(ini_raw[5:7]), int(ini_raw[8:10]))
                        if ini > posted:
                            ini = ini.replace(year=posted.year - 1)
                        repaired = True
                    except ValueError:
                        ini = None
            rule = "Q1" if (not prn or prn in seen) else ("Q2" if ini is None else None)
            if prn:
                seen.add(prn)
            if rule:
                quarantine.append((name, prn or None, rule))
                continue
            firm = r.get("recalling_firm") or ""
            makers.add(firm)
            exp["fact_recall"].append((
                prn, blank_to_none(r.get("res_event_number")), code, blank_to_none(firm), firm,
                blank_to_none(r.get("recall_status")), ini, repaired, posted,
                to_date(r.get("event_date_terminated"), "%Y-%m-%d"), blank_to_none(r.get("root_cause_description")),
                blank_to_none(r.get("reason_for_recall")), blank_to_none(r.get("action")),
                blank_to_none(r.get("product_description")), blank_to_none(r.get("product_quantity")),
                sorted({k.strip().upper() for k in (r.get("k_numbers") or []) if k and k.strip()}),
                blank_to_none(r.get("code_info"))))
    exp["dim_manufacturer"] = [(m, clean(m), parent(clean(m))) for m in makers]
    # links
    by_k, by_parent = defaultdict(list), defaultdict(list)  # indexes so each recall only sees its candidates
    for row in exp["fact_report"]:
        key, code, maker, rdate, pma = row[0], row[2], row[3], row[4], row[11]
        if pma:
            by_k[(code, pma)].append((key, rdate))
        by_parent[(code, parent(clean(maker)))].append((key, rdate))
    links = set()
    for c in exp["fact_recall"]:
        prn, code, firm_parent, ini = c[0], c[2], parent(clean(c[4])), c[6]
        for k in c[15]:
            for key, rdate in by_k.get((code, k), []):
                links.add((key, prn, "510k", (rdate - ini).days))
        if firm_parent != "(BLANK)":
            lo, hi = ini - timedelta(days=180), ini + timedelta(days=365)
            for key, rdate in by_parent.get((code, firm_parent), []):
                if lo <= rdate <= hi:
                    links.add((key, prn, "firm_window", (rdate - ini).days))
    exp["report_recall_link"] = links
    exp["quarantine"] = quarantine
    exp["raw_counts"] = raw_counts
    return exp


# ---- database side ---------------------------------------------------------------------------------
DB_QUERIES = {
    "fact_report": """SELECT r.mdr_report_key, r.report_number, r.product_code, m.raw_name, r.date_received,
        r.date_of_event, r.event_date_flag, r.lag_days, r.event_type, r.report_source_code, r.type_of_report,
        r.pma_pmn_number, r.brand_name, r.generic_name, r.model_number, r.lot_number, r.n_devices, r.n_patients,
        r.adverse_event_flag, r.product_problem_flag FROM {s}.fact_report r JOIN {s}.dim_manufacturer m USING (manufacturer_id)""",
    "report_device": "SELECT mdr_report_key, device_seq, product_code, brand_name, generic_name, manufacturer_raw, model_number, catalog_number, lot_number, implant_flag FROM {s}.report_device",
    "report_problem": "SELECT mdr_report_key, term FROM {s}.report_problem",
    "report_patient_problem": "SELECT mdr_report_key, term FROM {s}.report_patient_problem",
    "report_text": "SELECT mdr_report_key, text_seq, text_type, text FROM {s}.report_text",
    "fact_recall": """SELECT c.product_res_number, c.res_event_number, c.product_code, c.recalling_firm, m.raw_name,
        c.recall_status, c.event_date_initiated, c.initiated_date_repaired, c.event_date_posted, c.event_date_terminated,
        c.root_cause, c.reason_for_recall, c.action, c.product_description, c.product_quantity, c.k_numbers, c.code_info
        FROM {s}.fact_recall c JOIN {s}.dim_manufacturer m USING (manufacturer_id)""",
    "dim_manufacturer": "SELECT raw_name, clean_name, parent_company FROM {s}.dim_manufacturer",
    "report_recall_link": "SELECT mdr_report_key, product_res_number, link_type, days_from_initiation FROM {s}.report_recall_link",
}


def hashable(row):
    return tuple(tuple(x) if isinstance(x, list) else x for x in row)


def fingerprint(con, schema):
    out = {}
    tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s "
                                        "AND table_name <> 'load_run' ORDER BY 1", (schema,)).fetchall()]
    for t in tables:
        out[t] = con.execute(f"SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) FROM "
                             f"(SELECT md5(x::text) h FROM {schema}.{t} x) y").fetchone()
    return out


def run_loader(raw: Path, schema: str):
    subprocess.run([sys.executable, "-m", "mdqc.load", "--raw", str(raw), "--schema", schema, "--no-summary"],
                   cwd=ROOT, check=True, capture_output=True, text=True)


def plant_faults(src: Path, dst: Path) -> dict:
    """Copy the fixture and plant one fault per rule. Returns {rule: (file, key)}."""
    shutil.copytree(src, dst)

    def rw(name, fn):
        recs = lines(dst / name)
        recs, info = fn(recs)
        with gzip.open(dst / name, "wt", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in recs)
        return info

    planted = {}
    planted["R1"] = rw("events_LPH.jsonl.gz", lambda r: (r + [copy.deepcopy(r[0])], ("events_LPH.jsonl.gz", r[0]["mdr_report_key"])))

    def r2(r): r[1]["date_received"] = "20210615"; return r, ("events_JWH.jsonl.gz", r[1]["mdr_report_key"])
    def r3(r):
        for d in r[2]["device"]:
            d["device_report_product_code"] = "XXX"
        return r, ("events_MBH.jsonl.gz", r[2]["mdr_report_key"])
    def r4(r): r[3]["event_type"] = "Banana"; return r, ("events_LWP.jsonl.gz", r[3]["mdr_report_key"])
    def r5(r): r[4]["mdr_text"] = []; return r, ("events_LZG.jsonl.gz", r[4]["mdr_report_key"])
    def q1(r): return r + [copy.deepcopy(r[0])], ("recalls_LPH.jsonl.gz", r[0]["product_res_number"])
    def q2(r):
        r[1]["event_date_initiated"], r[1]["event_date_posted"] = "not-a-date", ""
        return r, ("recalls_JWH.jsonl.gz", r[1]["product_res_number"])
    planted["R2"] = rw("events_JWH.jsonl.gz", r2)
    planted["R3"] = rw("events_MBH.jsonl.gz", r3)
    planted["R4"] = rw("events_LWP.jsonl.gz", r4)
    planted["R5"] = rw("events_LZG.jsonl.gz", r5)
    planted["Q1"] = rw("recalls_LPH.jsonl.gz", q1)
    planted["Q2"] = rw("recalls_JWH.jsonl.gz", q2)
    return planted


def table_diffs(con, schema: str, exp: dict) -> tuple[dict, dict]:
    """Compare every row and column of the six data tables with the independent rebuild."""
    diffs, sizes = {}, {}
    for table in ("fact_report", "report_device", "report_problem", "report_patient_problem", "report_text",
                  "fact_recall"):
        db = Counter(hashable(r) for r in con.execute(DB_QUERIES[table].format(s=schema)).fetchall())
        ex = Counter(hashable(r) for r in exp[table])
        sizes[table] = sum(ex.values())
        if db != ex:
            diffs[table] = {"only_db": [str(x)[:200] for x in list((db - ex).elements())[:3]],
                            "only_expected": [str(x)[:200] for x in list((ex - db).elements())[:3]],
                            "n_only_db": sum((db - ex).values()), "n_only_expected": sum((ex - db).values())}
    return diffs, sizes


def main(raw: Path, schema: str, fixture: bool, reload: bool, evidence: Path | None) -> int:
    load_dotenv(ROOT / ".env")
    url = os.environ["DATABASE_URL"]
    checks = []

    def check(cid, name, ok, detail):
        checks.append({"id": cid, "check": name, "pass": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {cid} {name}: {json.dumps(detail, default=str)[:220]}")

    exp = expected(raw)
    with psycopg.connect(url) as con:
        # P1 accounted
        loaded = {}
        for code in CODES:
            loaded[f"events_{code}.jsonl.gz"] = con.execute(f"SELECT count(*) FROM {schema}.fact_report WHERE product_code=%s", (code,)).fetchone()[0]
            loaded[f"recalls_{code}.jsonl.gz"] = con.execute(f"SELECT count(*) FROM {schema}.fact_recall WHERE product_code=%s", (code,)).fetchone()[0]
        q = Counter(r[0] for r in con.execute(f"SELECT source FROM {schema}.quarantine").fetchall())
        p1 = {f: {"raw": exp["raw_counts"][f], "loaded": loaded[f], "quarantined": q.get(f, 0)} for f in loaded}
        check("P1", "loaded + quarantined = raw records, every file",
              all(v["raw"] == v["loaded"] + v["quarantined"] for v in p1.values()), p1)

        # P2 cell for cell (+ P6 manufacturers, P7 recall dates, P8 links use the same machinery)
        diffs, sizes = table_diffs(con, schema, exp)
        q_db = sorted((r[0], r[1], r[2]) for r in con.execute(f"SELECT source, record_key, rule FROM {schema}.quarantine").fetchall())
        q_ok = q_db == sorted(exp["quarantine"], key=lambda x: (x[0], x[1] or "", x[2]))
        check("P2", "every loaded row and column = independent rebuild from raw", not diffs and q_ok,
              {"rows_compared": sizes, "differences": diffs, "quarantine_matches": q_ok})

        # P3 privacy
        cols = [r[0] for r in con.execute("SELECT table_name || '.' || column_name FROM information_schema.columns "
                                          "WHERE table_schema=%s", (schema,)).fetchall()]
        bad_cols = [c for c in cols if any(w in c for w in DROPPED_COLUMN_WORDS)]
        leaked_keys = con.execute(f"SELECT count(*) FROM {schema}.quarantine WHERE raw::text ~ "
                                  "'manufacturer_contact_|patient_age|patient_sex|patient_weight|patient_race|patient_ethnicity'").fetchone()[0]
        sample, hits = 0, []
        for code in CODES:
            for r in lines(raw / f"events_{code}.jsonl.gz")[:200]:
                full = " ".join(x for x in ((r.get("manufacturer_contact_f_name") or "").strip(),
                                            (r.get("manufacturer_contact_l_name") or "").strip()) if x)
                phone = (r.get("manufacturer_contact_phone_number") or "").strip()
                needles = [x for x in (full if " " in full else "", phone if len(phone) >= 7 else "") if x]
                if not needles:
                    continue
                sample += 1
                texts = con.execute(f"SELECT coalesce(string_agg(text, ' '), '') FROM {schema}.report_text WHERE mdr_report_key=%s",
                                    (r.get("mdr_report_key"),)).fetchone()[0]
                row = con.execute(f"SELECT row_to_json(r)::text FROM {schema}.fact_report r WHERE mdr_report_key=%s",
                                  (r.get("mdr_report_key"),)).fetchone()
                blob = texts + " " + (row[0] if row else "")
                hits += [r.get("mdr_report_key") for n in needles if n in blob]
        check("P3", "no personal columns; contact names/phones absent from loaded rows",
              not bad_cols and not leaked_keys and not hits,
              {"personal_columns": bad_cols, "quarantine_rows_with_personal_keys": leaked_keys,
               "reports_sampled_with_contact_values": sample, "reports_where_found": hits[:10]})

        # P6 manufacturers
        db_m = sorted(con.execute(DB_QUERIES["dim_manufacturer"].format(s=schema)).fetchall())
        ex_m = sorted(exp["dim_manufacturer"])
        mism = [(a, b) for a, b in zip(db_m, ex_m) if a != b][:5]
        check("P6", "manufacturer clean/parent mapping = independent application of the alias file",
              db_m == ex_m, {"names": len(ex_m), "parents": len({x[2] for x in ex_m}), "mismatches": [str(x) for x in mism]})

        # P7 recall dates
        rep = con.execute(f"SELECT product_res_number, event_date_initiated FROM {schema}.fact_recall WHERE initiated_date_repaired ORDER BY 1").fetchall()
        rep_ex = sorted((r[0], r[6]) for r in exp["fact_recall"] if r[7])
        q2 = [x for x in exp["quarantine"] if x[2] == "Q2"]
        check("P7", "invalid recall dates repaired by the registered rule or quarantined",
              [tuple(x) for x in rep] == rep_ex, {"repaired": [(a, str(b)) for a, b in rep_ex], "quarantined_Q2": q2})

        # P8 links
        db_l = set(con.execute(DB_QUERIES["report_recall_link"].format(s=schema)).fetchall())
        by_type = Counter(x[2] for x in exp["report_recall_link"])
        check("P8", "report-recall links = independent recomputation", db_l == exp["report_recall_link"],
              {"expected_by_type": dict(by_type), "only_db": len(db_l - exp["report_recall_link"]),
               "only_expected": len(exp["report_recall_link"] - db_l)})

        # P4 idempotence (reload through the loader as a black box)
        if reload:
            before = fingerprint(con, schema)
            con.commit()
            run_loader(raw, schema)
            after = fingerprint(con, schema)
            check("P4", "second load gives identical table fingerprints", before == after,
                  {t: {"rows": before[t][0], "same": before[t] == after.get(t)} for t in before})

        # P5 planted faults
        with tempfile.TemporaryDirectory() as tmp:
            src = ROOT / "tests" / "fixtures" / "phase1" / "raw"
            planted = plant_faults(src, Path(tmp) / "raw")
            run_loader(Path(tmp) / "raw", "planted")
            got = {(r[0], r[1]): r[2] for r in con.execute("SELECT source, record_key, rule FROM planted.quarantine").fetchall()}
            hit = {rule: got.get(where) == rule for rule, where in planted.items()}
            fx = {name: len(lines(src / name)) for name in os.listdir(src)}
            n_rep = con.execute("SELECT count(*) FROM planted.fact_report").fetchone()[0]
            n_rc = con.execute("SELECT count(*) FROM planted.fact_recall").fetchone()[0]
            exp_rep = sum(v for k, v in fx.items() if k.startswith("events_")) - 4  # R2-R5 alter existing rows; R1 adds a copy
            exp_rc = sum(v for k, v in fx.items() if k.startswith("recalls_")) - 1  # Q2 alters one; Q1 adds a copy
            con.execute("DROP SCHEMA planted CASCADE")
            con.commit()
            check("P5", "each planted fault quarantined with its rule; clean rows still load",
                  all(hit.values()) and len(got) == len(planted) and n_rep == exp_rep and n_rc == exp_rc,
                  {"caught": hit, "quarantined": len(got), "reports_loaded": [n_rep, exp_rep], "recalls_loaded": [n_rc, exp_rc]})

        # P9 Phase 1 numbers reproduced (full data only)
        if not fixture:
            s1 = json.loads((ROOT / "results" / "phase1" / "eda_summary.json").read_text(encoding="utf-8"))
            qrecs = [json.loads(r[1]) | {"_src": r[0]} for r in con.execute(
                f"SELECT source, raw::text FROM {schema}.quarantine WHERE source LIKE 'events_%%'").fetchall()]
            bad = []
            for code in CODES:
                p1c = s1["per_code"][code]
                qc = [r for r in qrecs if r["_src"] == f"events_{code}.jsonl.gz"]
                n = con.execute(f"SELECT count(*) FROM {schema}.fact_report WHERE product_code=%s", (code,)).fetchone()[0] + len(qc)
                if n != p1c["reports"]:
                    bad.append((code, "reports", n, p1c["reports"]))
                months = dict(con.execute(f"SELECT to_char(date_received,'YYYY-MM'), count(*) FROM {schema}.fact_report "
                                          "WHERE product_code=%s GROUP BY 1", (code,)).fetchall())
                for r in qc:
                    m = r["date_received"][:4] + "-" + r["date_received"][4:6]
                    months[m] = months.get(m, 0) + 1
                if max(months.values()) != p1c["q1_monthly_max"] or max(months, key=lambda k: (months[k], -int(k.replace("-", "")))) != p1c["q1_monthly_max_month"]:
                    bad.append((code, "monthly max", max(months.values()), p1c["q1_monthly_max"]))
                et = dict(con.execute(f"SELECT CASE WHEN event_type='Not provided' THEN '(blank)' ELSE event_type END, count(*) "
                                      f"FROM {schema}.fact_report WHERE product_code=%s GROUP BY 1", (code,)).fetchall())
                for r in qc:
                    k = (r.get("event_type") or "").strip() or "(blank)"
                    et[k] = et.get(k, 0) + 1
                if et != p1c["q2_event_type"]:
                    bad.append((code, "event types", et, p1c["q2_event_type"]))
                terms = dict(con.execute(f"SELECT term, count(*) FROM {schema}.report_problem p JOIN {schema}.fact_report r "
                                         "USING (mdr_report_key) WHERE r.product_code=%s GROUP BY 1", (code,)).fetchall())
                for r in qc:
                    for t in set(r.get("product_problems") or []):
                        terms[t] = terms.get(t, 0) + 1
                top = sorted(terms.items(), key=lambda x: (-x[1], x[0]))[:10]
                if [list(x) for x in top] != p1c["q3_top_problems"]:
                    bad.append((code, "top problem terms"))
                mk = dict(con.execute(f"SELECT upper(trim(m.raw_name)), count(*) FROM {schema}.fact_report r JOIN "
                                      f"{schema}.dim_manufacturer m USING (manufacturer_id) WHERE r.product_code=%s GROUP BY 1",
                                      (code,)).fetchall())
                for r in qc:
                    d = next((d for d in r.get("device") or [] if d.get("device_report_product_code") == code), {})
                    k = (d.get("manufacturer_d_name") or "").strip().upper() or "(blank)"
                    mk[k] = mk.get(k, 0) + 1
                topm = sorted(mk.items(), key=lambda x: (-x[1], x[0]))[0]
                if list(topm) != p1c["q4_top_manufacturers"][0]:
                    bad.append((code, "top manufacturer", topm, p1c["q4_top_manufacturers"][0]))
                nrc = con.execute(f"SELECT count(*) FROM {schema}.fact_recall WHERE product_code=%s", (code,)).fetchone()[0]
                nrc += sum(1 for x in exp["quarantine"] if x[0] == f"recalls_{code}.jsonl.gz")
                if nrc != p1c["q6_recalls"]:
                    bad.append((code, "recalls", nrc, p1c["q6_recalls"]))
            check("P9", "SQL reproduces Phase 1 numbers (quarantined records added back)", not bad,
                  {"mismatches": bad, "quarantined_reports_added_back": len(qrecs)})

    ok = all(c["pass"] for c in checks)
    if evidence:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "schema": schema, "all_pass": ok, "checks": checks}, indent=2, default=str) + "\n",
                            encoding="utf-8", newline="\n")
    print(f"\n{sum(c['pass'] for c in checks)}/{len(checks)} checks pass")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 2 verifier")
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--schema", default="core")
    ap.add_argument("--fixture", action="store_true", help="skip P9 (needs the full data) and write no evidence")
    ap.add_argument("--no-reload", action="store_true", help="skip P4 (it re-runs the loader)")
    ap.add_argument("--evidence", type=Path, default=None)
    a = ap.parse_args()
    ev = a.evidence or (None if a.fixture else ROOT / "results" / "phase2" / "verify_phase2.json")
    sys.exit(main(a.raw.resolve(), a.schema, a.fixture, not a.no_reload, ev))
