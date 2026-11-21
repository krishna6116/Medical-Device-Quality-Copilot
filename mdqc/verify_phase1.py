"""Phase 1 independent verification (criteria C1-C7 in config/phase1_criteria.json).

Run:  python -m mdqc.verify_phase1                 full data in data/raw (writes evidence)
      python -m mdqc.verify_phase1 --network       also re-asks openFDA for today's totals (info only)
      python -m mdqc.verify_phase1 --raw DIR --summary FILE --no-download-checks
                                                   any other copy, e.g. the CI fixture

"Independent" means: this file never imports mdqc.eda or pandas. It re-reads the raw .jsonl.gz
files with the standard library, re-implements every definition from the eda docstring, and
compares its numbers with results/phase1/eda_summary.json, which is where every number in
docs/EDA_FINDINGS.md comes from. A mismatch anywhere is a FAIL.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPE = json.loads((ROOT / "config" / "scope.json").read_text(encoding="utf-8"))
CODES = list(SCOPE["product_codes"])
W_FROM, W_TO = SCOPE["event_window"]["from"], SCOPE["event_window"]["to"]
CONTACT = ("manufacturer_contact_f_name", "manufacturer_contact_l_name", "manufacturer_contact_phone_number")


def lines(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                yield json.loads(ln)


def ymd(s):
    try:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8])) if isinstance(s, str) and len(s) == 8 and s.isdigit() else None
    except ValueError:
        return None


def interp_percentile(values, q):
    """Linear interpolation between order statistics, written out by hand."""
    v = sorted(values)
    if not v:
        return None
    pos = (len(v) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return round(v[lo] + (v[hi] - v[lo]) * (pos - lo), 1)


def months():
    out = []
    for y in range(int(W_FROM[:4]), int(W_TO[:4]) + 1):
        out += [f"{y}-{m:02d}" for m in range(1, 13)]
    return out


def recompute(raw: Path) -> dict:
    per, keys_all, overall_types, contact_total = {}, set(), Counter(), 0
    recalls_total = 0
    for code in CODES:
        seen, month_n, types, makers, probs = set(), Counter(), Counter(), Counter(), Counter()
        maker_month = defaultdict(Counter)
        no_probs = with_text = 0
        text_lens, lags = [], []
        multi = other = not_listed = outside = contact = 0
        for rec in lines(raw / f"events_{code}.jsonl.gz"):
            k = rec.get("mdr_report_key")
            if k in seen:
                continue
            seen.add(k)
            keys_all.add(k)
            dr = rec.get("date_received") or ""
            month_n[dr[:4] + "-" + dr[4:6]] += 1
            et = (rec.get("event_type") or "").strip() or "(blank)"
            types[et] += 1
            overall_types[et] += 1
            devs = rec.get("device") or []
            first = None
            for d in devs:
                if d.get("device_report_product_code") == code:
                    first = d
                    break
            maker = ((first or {}).get("manufacturer_d_name") or "").strip().upper() or "(blank)"
            makers[maker] += 1
            maker_month[maker][dr[:4] + "-" + dr[4:6]] += 1
            pp = rec.get("product_problems") or []
            if not pp:
                no_probs += 1
            for p in set(pp):  # once per report: openFDA repeats terms inside a report
                probs[p] += 1
            text = " ".join((t.get("text") or "") for t in (rec.get("mdr_text") or []))
            if text.strip():
                with_text += 1
                text_lens.append(len(text))
            a, b = ymd(dr), ymd(rec.get("date_of_event"))
            if a and b:
                lags.append((a - b).days)
            listed = {d.get("device_report_product_code") for d in devs}
            multi += len(devs) > 1
            other += any(c in CODES and c != code for c in listed)
            not_listed += code not in listed
            outside += not (W_FROM <= dr <= W_TO)
            contact += any((rec.get(f) or "").strip() for f in CONTACT)
        n = len(seen)
        series = [month_n.get(m, 0) for m in months()]
        med = float(statistics.median(series))
        top_m = max(range(len(series)), key=lambda i: (series[i], -i))
        rc_years, rc_causes, rc_events = Counter(), Counter(), set()
        rc_n = rc_invalid = 0
        for r in lines(raw / f"recalls_{code}.jsonl.gz"):
            rc_n += 1
            d = r.get("event_date_initiated") or ""
            y = d[:4]
            if len(y) == 4 and y.isdigit() and "1976" <= y:
                rc_years[str(int(y))] += 1
            else:
                rc_invalid += 1
            rc_causes[(r.get("root_cause_description") or "").strip() or "(blank)"] += 1
            if r.get("res_event_number") is not None:
                rc_events.add(r.get("res_event_number"))
        recalls_total += rc_n
        nonneg = [x for x in lags if x >= 0]
        contact_total += contact
        per[code] = {
            "reports": n,
            "q1_monthly_median": med,
            "q1_monthly_max": series[top_m],
            "q1_monthly_max_month": months()[top_m],
            "q1_spike_months_over_3x_median": {m: c for m, c in zip(months(), series) if c > 3 * med},
            "q2_event_type": dict(types),
            "q3_top_problems": [[p, c] for p, c in sorted(probs.items(), key=lambda x: (-x[1], x[0]))[:10]],
            "q3_reports_without_problem_terms": no_probs,
            "q4_top_manufacturers": [[m, c] for m, c in sorted(makers.items(), key=lambda x: (-x[1], x[0]))[:5]],
            "q4_top_manufacturer_share": round(max(makers.values()) / n, 4),
            "q4_distinct_manufacturers": len(makers),
            "q5_share_with_narrative": round(with_text / n, 4),
            "q5_narrative_len_median": interp_percentile(text_lens, 50),
            "q5_narrative_len_p90": interp_percentile(text_lens, 90),
            "q6_recalls": rc_n,
            "q6_recall_events_distinct": len(rc_events),
            "q6_recalls_in_window": sum(c for y, c in rc_years.items() if W_FROM[:4] <= y <= W_TO[:4]),
            "q6_recalls_invalid_initiation_date": rc_invalid,
            "q6_recalls_by_year": {y: rc_years[y] for y in sorted(rc_years)},
            "q6_recalls_by_root_cause": dict(sorted(rc_causes.items(), key=lambda x: (-x[1], x[0]))),
            "q7_lag_reports_with_both_dates": len(lags),
            "q7_lag_negative": len(lags) - len(nonneg),
            "q7_lag_median_days": interp_percentile(nonneg, 50),
            "q7_lag_p90_days": interp_percentile(nonneg, 90),
            "q8_multi_device_reports": multi,
            "q8_listed_under_other_scope_code": other,
            "c3_code_not_in_device_list": not_listed,
            "c3_outside_window": outside,
            "c7_reports_with_contact_fields": contact,
        }
        top3 = [m for m, _ in sorted(makers.items(), key=lambda x: (-x[1], x[0]))[:3]]
        ms = months()
        per[code]["q9_top3_monthly"] = {m: [maker_month[m].get(x, 0) for x in ms] for m in top3}
        per[code]["q9_top3_by_year"] = {m: {y: sum(v for x, v in maker_month[m].items() if x[:4] == y)
                                            for y in sorted({x[:4] for x in ms})} for m in top3}
        per[code]["q9_busiest_month_by_maker"] = {m: maker_month[m].get(ms[top_m], 0) for m in top3}
    total = sum(p["reports"] for p in per.values())
    return {"per_code": per, "overall": {
        "reports": total, "distinct_report_keys_across_codes": len(keys_all), "recalls": recalls_total,
        "event_type": dict(overall_types), "reports_with_contact_fields": contact_total}}


def compare(mine, theirs, path=""):
    """Return a list of mismatch descriptions (dict key order is ignored)."""
    if isinstance(mine, dict) and isinstance(theirs, dict):
        out = []
        for k in sorted(set(mine) | set(theirs)):
            if k not in mine or k not in theirs:
                out.append(f"{path}/{k}: missing on one side")
            else:
                out += compare(mine[k], theirs[k], f"{path}/{k}")
        return out
    if isinstance(mine, float) or isinstance(theirs, float):
        return [] if mine is not None and theirs is not None and abs(float(mine) - float(theirs)) < 1e-9 \
            else ([] if mine == theirs else [f"{path}: {mine} != {theirs}"])
    return [] if mine == theirs else [f"{path}: {mine} != {theirs}"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(raw: Path, summary_path: Path, download_checks: bool, network: bool, evidence: Path | None) -> int:
    checks = []

    def check(cid, name, ok, detail):
        checks.append({"id": cid, "check": name, "pass": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {cid} {name}: {json.dumps(detail)[:200]}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    mine = recompute(raw)

    if download_checks:
        man = json.loads((ROOT / "results" / "phase1" / "download_manifest.json").read_text(encoding="utf-8"))
        c1 = {c: {"server": e["server_total_before"], "downloaded": e["downloaded"],
                  "distinct": e["distinct_mdr_report_key"], "recounted": mine["per_code"][c]["reports"]}
              for c, e in man["events"].items()}
        check("C1", "event counts = server totals at download", all(
            v["server"] == v["downloaded"] == v["distinct"] == v["recounted"] for v in c1.values()), c1)
        c2 = {c: {"server": r["server_total_before"], "downloaded": r["downloaded"],
                  "recounted": mine["per_code"][c]["q6_recalls"]} for c, r in man["recalls"].items()}
        check("C2", "recall counts = server totals", all(
            v["server"] == v["downloaded"] == v["recounted"] for v in c2.values()), c2)
        dups = {c: e["duplicates"] for c, e in man["events"].items()}
        check("C4", "no duplicate report keys within a code", all(v == 0 for v in dups.values()),
              {"duplicates": dups, "reports_under_two_scope_codes":
               {c: mine["per_code"][c]["q8_listed_under_other_scope_code"] for c in CODES}})
        listed = {}
        for ln in (ROOT / "data" / "checksums.sha256").read_text(encoding="utf-8").splitlines():
            h, name = ln.split(maxsplit=1)
            listed[name] = h
        bad = [n for n, h in listed.items() if sha256(ROOT / n) != h]
        missing = [p.name for p in raw.glob("*.jsonl.gz") if f"data/raw/{p.name}" not in listed]
        check("C5", "checksums match", not bad and not missing and listed,
              {"files": len(listed), "mismatch": bad, "unlisted": missing})

    c3 = {c: {"outside_window": mine["per_code"][c]["c3_outside_window"],
              "code_not_listed": mine["per_code"][c]["c3_code_not_in_device_list"]} for c in CODES}
    check("C3", "every report in window and lists its code",
          all(v["outside_window"] == 0 and v["code_not_listed"] == 0 for v in c3.values()), c3)

    diffs = compare({"per_code": mine["per_code"], "overall": mine["overall"]},
                    {"per_code": summary["per_code"], "overall": summary["overall"]})
    n_values = sum(1 for _ in _leaves(mine))
    check("C6", "independent recount of every summary number", not diffs,
          {"values_compared": n_values, "mismatches": diffs[:20]})

    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    leaks = [f for f in tracked if not f.startswith("tests/fixtures/") and (
             f == ".env" or f.endswith((".gz", ".duckdb", ".parquet", ".zip"))
             or (f.startswith("data/") and f != "data/checksums.sha256"))]
    check("C7", "no data or secrets in git; contact fields counted", not leaks,
          {"tracked_leaks": leaks, "reports_with_contact_fields": mine["overall"]["reports_with_contact_fields"]})

    if network:
        sys.path.insert(0, str(ROOT))
        from mdqc.openfda import OpenFDAClient, build_search
        c = OpenFDAClient()
        today = {}
        for code in CODES:
            d, _ = c.get("event", search=build_search(product_code=code, date_field="date_received",
                                                      date_from=W_FROM, date_to=W_TO), limit=1)
            today[code] = {"server_now": d["meta"]["results"]["total"], "ours": mine["per_code"][code]["reports"]}
        checks.append({"id": "info", "check": "server totals today (openFDA keeps adding late reports)",
                       "pass": True, "detail": today})
        print("INFO server totals today:", json.dumps(today))
        check("C8", "published numbers = openFDA's own server-side counts (post hoc)",
              *server_crosscheck(c, summary))

    ok = all(c["pass"] for c in checks)
    if evidence:
        evidence.write_text(json.dumps({"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "all_pass": ok, "checks": checks}, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
    print(f"\n{sum(c['pass'] for c in checks)}/{len(checks)} checks pass")
    return 0 if ok else 1


def server_crosscheck(c, summary) -> tuple[bool, dict]:
    """Third, fully external check (added post hoc after it found the doubled problem-term counts):
    openFDA counts on its own server and we compare with what we publish. Monthly volume (from
    results/phase1/monthly_counts.csv), event types, top-10 problem terms and recall root causes must
    match exactly. The top manufacturer is reported only: the server counts raw spellings, we merge
    upper/lower case on purpose."""
    import csv
    from mdqc.openfda import build_search

    monthly = list(csv.DictReader(open(ROOT / "results" / "phase1" / "monthly_counts.csv", encoding="utf-8")))
    detail, ok = {}, True
    for code in CODES:
        pc = summary["per_code"][code]
        s = build_search(product_code=code, date_field="date_received", date_from=W_FROM, date_to=W_TO)

        def count(endpoint, search, field, limit=None):
            params = {"search": search, "count": field}
            if limit:
                params["limit"] = limit
            return c.get(endpoint, **params)[0]["results"]

        srv_month = Counter()
        for row in count("event", s, "date_received"):
            srv_month[row["time"][:4] + "-" + row["time"][4:6]] += row["count"]
        months_ok = all(srv_month.get(r["month"], 0) == int(r[code]) for r in monthly) \
            and sum(srv_month.values()) == pc["reports"]
        et_srv = {r["term"]: r["count"] for r in count("event", s, "event_type.exact")}
        types_ok = et_srv == {k: v for k, v in pc["q2_event_type"].items() if k != "(blank)"}
        pr_srv = {r["term"]: r["count"] for r in count("event", s, "product_problems.exact", 999)}
        terms_bad = {p: [k, pr_srv.get(p)] for p, k in pc["q3_top_problems"] if pr_srv.get(p) != k}
        rc_srv = {r["term"]: r["count"] for r in count("recall", f"product_code:{code}", "root_cause_description.exact")}
        causes_ok = rc_srv == {k: v for k, v in pc["q6_recalls_by_root_cause"].items() if k != "(blank)"}
        mf = count("event", s, "device.manufacturer_d_name.exact", 5)[0]
        detail[code] = {"monthly": months_ok, "event_types": types_ok, "problem_terms_mismatch": terms_bad,
                        "recall_root_causes": causes_ok,
                        "top_maker_server_raw": [mf["term"], mf["count"]],
                        "top_maker_ours_merged_case": pc["q4_top_manufacturers"][0]}
        ok &= months_ok and types_ok and not terms_bad and causes_ok
    return ok, detail


def _leaves(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from _leaves(v)
    else:
        yield o


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 1 verifier")
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--summary", type=Path, default=ROOT / "results" / "phase1" / "eda_summary.json")
    ap.add_argument("--no-download-checks", action="store_true", help="skip C1, C2, C4, C5 (no manifest/checksums)")
    ap.add_argument("--network", action="store_true")
    ap.add_argument("--evidence", type=Path, default=None)
    a = ap.parse_args()
    ev = a.evidence if a.evidence else (None if a.no_download_checks else ROOT / "results" / "phase1" / "verify_phase1.json")
    sys.exit(main(a.raw, a.summary, not a.no_download_checks, a.network, ev))
