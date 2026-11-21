"""Phase 2 loader: raw openFDA files -> PostgreSQL star schema (rules in config/phase2_criteria.json).

Run:  python -m mdqc.load                      full data (data/raw) into schema core
      python -m mdqc.load --raw DIR --schema S  any other copy (CI fixture, planted faults)

Each run is one transaction: the schema is dropped and rebuilt from mdqc/schema.sql, every raw
record is either loaded or written to `quarantine` with the rule it broke, and a `load_run` row
records the raw-file checksums and counts. Rebuilding from scratch makes the load idempotent.
Personal fields (manufacturer contacts, patient demographics) are dropped before anything is stored,
including the quarantine copy.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
SCOPE = json.loads((ROOT / "config" / "scope.json").read_text(encoding="utf-8"))
ALIASES = json.loads((ROOT / "config" / "manufacturer_aliases.json").read_text(encoding="utf-8"))
CODES = list(SCOPE["product_codes"])
W_FROM = date(int(SCOPE["event_window"]["from"][:4]), int(SCOPE["event_window"]["from"][4:6]), int(SCOPE["event_window"]["from"][6:]))
W_TO = date(int(SCOPE["event_window"]["to"][:4]), int(SCOPE["event_window"]["to"][4:6]), int(SCOPE["event_window"]["to"][6:]))
EVENT_TYPES = {"Malfunction", "Injury", "Death", "Other"}
PATIENT_DROP = {"patient_age", "patient_sex", "patient_weight", "patient_race", "patient_ethnicity"}
OUT = ROOT / "results" / "phase2"


# ---- cleaning helpers --------------------------------------------------------------------------
def clean_name(name: str | None) -> str:
    s = (name or "").upper()
    s = re.sub(r"\s+-\s*\d+\s*$", "", s)            # trailing site number: 'DEPUY IRELAND - 9616671'
    s = re.sub(r"[^A-Z0-9& ]+", " ", s)             # punctuation -> space, '&' kept
    s = re.sub(r"\s+", " ", s).strip()
    suffixes = sorted(ALIASES["legal_suffixes"], key=len, reverse=True)
    changed = True
    while changed:
        changed = False
        for suf in suffixes:
            if s.endswith(" " + suf):
                s = s[: -len(suf) - 1].strip()
                changed = True
    return s


def parent_company(clean: str) -> str:
    if not clean:
        return "(BLANK)"
    for rule in ALIASES["parents"]:
        for pat in rule["patterns"]:
            if re.search(r"(?<![A-Z0-9])" + re.escape(pat) + r"(?![A-Z0-9])", clean):
                return rule["parent"]
    return clean


def ymd(s) -> date | None:
    if not isinstance(s, str) or len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return None


def iso(s) -> date | None:
    if not isinstance(s, str) or len(s) != 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def repair_initiated(initiated: str | None, posted: str | None) -> tuple[date | None, bool]:
    """Registered rule: a pre-1976 year is replaced by the posted year (or the year before)."""
    d = iso(initiated)
    if d and d.year >= 1976:
        return d, False
    p = iso(posted)
    if p and isinstance(initiated, str) and len(initiated) == 10:
        try:
            cand = date(p.year, int(initiated[5:7]), int(initiated[8:10]))
            if cand > p:
                cand = date(p.year - 1, cand.month, cand.day)
            return cand, True
        except ValueError:
            return None, False
    return None, False


def strip_personal(rec: dict) -> dict:
    out = {k: v for k, v in rec.items() if not k.startswith("manufacturer_contact_")}
    if isinstance(out.get("patient"), list):
        out["patient"] = [{k: v for k, v in p.items() if k not in PATIENT_DROP} for p in out["patient"]]
    return out


def none_if_blank(v):
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v if x)
    v = (v or "").strip() if isinstance(v, str) else v
    return v or None


# ---- reading raw files ---------------------------------------------------------------------------
def read(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(raw: Path) -> dict:
    """Turn the raw files into row lists for every table, plus quarantine rows."""
    t = {k: [] for k in ("report", "device", "problem", "patient_problem", "text", "recall", "quarantine")}
    makers: set[str] = set()
    raw_counts = {}
    for code in CODES:
        name = f"events_{code}.jsonl.gz"
        seen, n = set(), 0
        for rec in read(raw / name):
            n += 1
            key = rec.get("mdr_report_key")
            received = ymd(rec.get("date_received"))
            devices = rec.get("device") or []
            mine = next((d for d in devices if d.get("device_report_product_code") == code), None)
            et = (rec.get("event_type") or "").strip()
            texts = rec.get("mdr_text") or []
            rule = None
            if not key or key in seen:
                rule, detail = "R1", "missing or duplicate mdr_report_key"
            elif not received or not (W_FROM <= received <= W_TO):
                rule, detail = "R2", f"date_received {rec.get('date_received')!r} invalid or outside the window"
            elif mine is None:
                rule, detail = "R3", f"no device entry with product code {code}"
            elif et and et not in EVENT_TYPES:
                rule, detail = "R4", f"unknown event_type {et!r}"
            elif not any((x.get("text") or "").strip() for x in texts):
                rule, detail = "R5", "no narrative text"
            if key:
                seen.add(key)
            if rule:
                t["quarantine"].append((name, key, rule, detail, json.dumps(strip_personal(rec), sort_keys=True)))
                continue
            occurred = ymd(rec.get("date_of_event"))
            raw_event = (rec.get("date_of_event") or "").strip()
            if not raw_event:
                flag = "missing"
            elif occurred is None:
                flag = "invalid"
            elif occurred > received:
                flag = "after_received"
            else:
                flag = "ok"
            maker = mine.get("manufacturer_d_name") or ""
            makers.add(maker)
            pma = (rec.get("pma_pmn_number") or "").strip().upper() or None
            t["report"].append({
                "mdr_report_key": key, "report_number": none_if_blank(rec.get("report_number")),
                "product_code": code, "maker": maker, "date_received": received,
                "date_of_event": occurred, "event_date_flag": flag,
                "lag_days": (received - occurred).days if occurred else None,
                "event_type": et or "Not provided",
                "report_source_code": none_if_blank(rec.get("report_source_code")),
                "type_of_report": none_if_blank(rec.get("type_of_report")),
                "pma_pmn_number": pma,
                "brand_name": none_if_blank(mine.get("brand_name")),
                "generic_name": none_if_blank(mine.get("generic_name")),
                "model_number": none_if_blank(mine.get("model_number")),
                "lot_number": none_if_blank(mine.get("lot_number")),
                "n_devices": len(devices), "n_patients": len(rec.get("patient") or []),
                "adverse_event_flag": none_if_blank(rec.get("adverse_event_flag")),
                "product_problem_flag": none_if_blank(rec.get("product_problem_flag")),
            })
            for i, d in enumerate(devices, 1):
                t["device"].append((key, i, none_if_blank(d.get("device_report_product_code")),
                                    none_if_blank(d.get("brand_name")), none_if_blank(d.get("generic_name")),
                                    none_if_blank(d.get("manufacturer_d_name")), none_if_blank(d.get("model_number")),
                                    none_if_blank(d.get("catalog_number")), none_if_blank(d.get("lot_number")),
                                    none_if_blank(d.get("implant_flag"))))
            for term in sorted(set(rec.get("product_problems") or [])):
                t["problem"].append((key, term))
            pterms = {p for pt in (rec.get("patient") or []) for p in (pt.get("patient_problems") or [])}
            for term in sorted(pterms):
                t["patient_problem"].append((key, term))
            for i, x in enumerate(texts, 1):
                t["text"].append((key, i, none_if_blank(x.get("text_type_code")), x.get("text") or ""))
        raw_counts[name] = n

    for code in CODES:
        name = f"recalls_{code}.jsonl.gz"
        seen, n = set(), 0
        for rec in read(raw / name):
            n += 1
            prn = (rec.get("product_res_number") or "").strip()
            initiated, repaired = repair_initiated(rec.get("event_date_initiated"), rec.get("event_date_posted"))
            rule = None
            if not prn or prn in seen:
                rule, detail = "Q1", "missing or duplicate product_res_number"
            elif initiated is None:
                rule, detail = "Q2", f"event_date_initiated {rec.get('event_date_initiated')!r} invalid, not repairable"
            if prn:
                seen.add(prn)
            if rule:
                t["quarantine"].append((name, prn or None, rule, detail, json.dumps(strip_personal(rec), sort_keys=True)))
                continue
            firm = rec.get("recalling_firm") or ""
            makers.add(firm)
            t["recall"].append({
                "product_res_number": prn, "res_event_number": none_if_blank(rec.get("res_event_number")),
                "product_code": code, "recalling_firm": none_if_blank(firm), "maker": firm,
                "recall_status": none_if_blank(rec.get("recall_status")),
                "event_date_initiated": initiated, "initiated_date_repaired": repaired,
                "event_date_posted": iso(rec.get("event_date_posted")),
                "event_date_terminated": iso(rec.get("event_date_terminated")),
                "root_cause": none_if_blank(rec.get("root_cause_description")),
                "reason_for_recall": none_if_blank(rec.get("reason_for_recall")),
                "action": none_if_blank(rec.get("action")),
                "product_description": none_if_blank(rec.get("product_description")),
                "product_quantity": none_if_blank(rec.get("product_quantity")),
                "k_numbers": sorted({k.strip().upper() for k in (rec.get("k_numbers") or []) if k and k.strip()}),
                "code_info": none_if_blank(rec.get("code_info")),
            })
        raw_counts[name] = n

    t["makers"] = sorted(makers)
    t["classification"] = list(read(raw / "classification.jsonl.gz")) if (raw / "classification.jsonl.gz").exists() else []
    t["raw_counts"] = raw_counts
    return t


# ---- writing -------------------------------------------------------------------------------------
def copy_rows(cur, table: str, columns: list[str], rows) -> None:
    stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)))
    with cur.copy(stmt) as cp:
        for r in rows:
            cp.write_row(r)


LINK_SQL = """
INSERT INTO report_recall_link (mdr_report_key, product_res_number, link_type, days_from_initiation)
SELECT r.mdr_report_key, c.product_res_number, '510k', r.date_received - c.event_date_initiated
FROM fact_report r JOIN fact_recall c
  ON r.product_code = c.product_code AND r.pma_pmn_number = ANY (c.k_numbers);

INSERT INTO report_recall_link (mdr_report_key, product_res_number, link_type, days_from_initiation)
SELECT r.mdr_report_key, c.product_res_number, 'firm_window', r.date_received - c.event_date_initiated
FROM fact_report r
JOIN dim_manufacturer mr ON mr.manufacturer_id = r.manufacturer_id
JOIN fact_recall c ON c.product_code = r.product_code
JOIN dim_manufacturer mc ON mc.manufacturer_id = c.manufacturer_id
WHERE mr.parent_company = mc.parent_company AND mr.parent_company <> '(BLANK)'
  AND r.date_received BETWEEN c.event_date_initiated - 180 AND c.event_date_initiated + 365;
"""


def pipeline_stats(cur) -> dict:
    """Descriptive numbers for docs/PIPELINE.md (the doc is generated from these, never typed)."""
    q = lambda s, *a: cur.execute(s, a).fetchall()  # noqa: E731
    s = {}
    s["quarantine"] = [list(r) for r in q("SELECT source, record_key, rule, detail FROM quarantine ORDER BY 1, 2")]
    s["event_date_flag"] = dict(q("SELECT event_date_flag, count(*) FROM fact_report GROUP BY 1 ORDER BY 1"))
    s["pma_prefix"] = dict(q("""SELECT CASE WHEN pma_pmn_number IS NULL THEN 'none' WHEN pma_pmn_number ~ '^K[0-9]' THEN 'K (510(k))'
        WHEN pma_pmn_number ~ '^P[0-9]' THEN 'P (PMA)' WHEN pma_pmn_number ~ '^DEN' THEN 'DEN (De Novo)'
        ELSE 'other' END, count(*) FROM fact_report GROUP BY 1 ORDER BY 2 DESC"""))
    s["manufacturer_names"] = q("SELECT count(*), count(DISTINCT parent_company) FROM dim_manufacturer")[0]
    s["parents_per_code"] = {}
    for code in CODES:
        rows = q("""SELECT m.parent_company, count(*), count(DISTINCT m.raw_name) FROM fact_report r
                    JOIN dim_manufacturer m USING (manufacturer_id) WHERE r.product_code = %s
                    GROUP BY 1 ORDER BY 2 DESC, 1""", code)
        total = sum(r[1] for r in rows)
        s["parents_per_code"][code] = {"top": [list(r) for r in rows[:6]], "parents": len(rows),
                                       "reports_outside_top6": total - sum(r[1] for r in rows[:6]),
                                       "reports_under_parents_with_under_20": sum(r[1] for r in rows if r[1] < 20)}
    s["recalls_repaired"] = [[r[0], str(r[1]), str(r[2])] for r in q(
        "SELECT product_res_number, event_date_initiated, event_date_posted FROM fact_recall WHERE initiated_date_repaired")]
    s["links"] = {}
    for lt in ("510k", "firm_window"):
        r = q("""SELECT count(*), count(DISTINCT mdr_report_key), count(DISTINCT product_res_number),
                 percentile_disc(0.5) WITHIN GROUP (ORDER BY days_from_initiation),
                 min(days_from_initiation), max(days_from_initiation),
                 count(*) FILTER (WHERE abs(days_from_initiation) <= 365)
                 FROM report_recall_link WHERE link_type = %s""", lt)[0]
        per = q("""SELECT r.product_code, count(DISTINCT l.mdr_report_key), count(DISTINCT l.product_res_number)
                   FROM report_recall_link l JOIN fact_report r USING (mdr_report_key) WHERE l.link_type = %s
                   GROUP BY 1 ORDER BY 1""", lt)
        s["links"][lt] = {"links": r[0], "reports": r[1], "recalls": r[2], "median_days": r[3], "min_days": r[4],
                          "max_days": r[5], "links_within_365_days": r[6],
                          "per_code": {c: [a, b] for c, a, b in per}}
    s["reports_with_any_link"] = q("SELECT count(DISTINCT mdr_report_key) FROM report_recall_link")[0][0]
    return s


def load(raw: Path = ROOT / "data" / "raw", schema: str = "core", url: str | None = None,
         write_summary: bool = True) -> dict:
    load_dotenv(ROOT / ".env")
    url = url or os.environ["DATABASE_URL"]
    started = datetime.now(timezone.utc)
    t = build(raw)
    maker_id = {name: i for i, name in enumerate(t["makers"], 1)}
    ddl = (ROOT / "mdqc" / "schema.sql").read_text(encoding="utf-8").replace("{schema}", schema)
    with psycopg.connect(url) as con, con.cursor() as cur:
        cur.execute(ddl)
        fam = {c: SCOPE["product_codes"][c]["family"] for c in CODES}
        cls = {r.get("product_code"): r for r in t["classification"]}
        copy_rows(cur, "dim_product_code", ["product_code", "device_name", "device_class", "medical_specialty",
                                            "regulation_number", "family"],
                  [(c, cls.get(c, {}).get("device_name") or SCOPE["product_codes"][c]["device_name"],
                    cls.get(c, {}).get("device_class"), cls.get(c, {}).get("medical_specialty_description"),
                    cls.get(c, {}).get("regulation_number"), fam[c]) for c in CODES])
        copy_rows(cur, "dim_manufacturer", ["manufacturer_id", "raw_name", "clean_name", "parent_company"],
                  [(i, name, clean_name(name), parent_company(clean_name(name))) for name, i in maker_id.items()])
        cur.execute("""INSERT INTO dim_date SELECT d::date, extract(year FROM d), extract(quarter FROM d),
                       extract(month FROM d), date_trunc('month', d)::date
                       FROM generate_series('1976-01-01'::date, '2026-12-31'::date, interval '1 day') d""")
        rcols = ["mdr_report_key", "report_number", "product_code", "manufacturer_id", "date_received", "date_of_event",
                 "event_date_flag", "lag_days", "event_type", "report_source_code", "type_of_report", "pma_pmn_number",
                 "brand_name", "generic_name", "model_number", "lot_number", "n_devices", "n_patients",
                 "adverse_event_flag", "product_problem_flag"]
        copy_rows(cur, "fact_report", rcols,
                  ([r[c] if c != "manufacturer_id" else maker_id[r["maker"]] for c in rcols] for r in t["report"]))
        copy_rows(cur, "report_device", ["mdr_report_key", "device_seq", "product_code", "brand_name", "generic_name",
                                         "manufacturer_raw", "model_number", "catalog_number", "lot_number",
                                         "implant_flag"], t["device"])
        copy_rows(cur, "report_problem", ["mdr_report_key", "term"], t["problem"])
        copy_rows(cur, "report_patient_problem", ["mdr_report_key", "term"], t["patient_problem"])
        copy_rows(cur, "report_text", ["mdr_report_key", "text_seq", "text_type", "text"], t["text"])
        ccols = ["product_res_number", "res_event_number", "product_code", "recalling_firm", "manufacturer_id",
                 "recall_status", "event_date_initiated", "initiated_date_repaired", "event_date_posted",
                 "event_date_terminated", "root_cause", "reason_for_recall", "action", "product_description",
                 "product_quantity", "k_numbers", "code_info"]
        copy_rows(cur, "fact_recall", ccols,
                  ([r[c] if c != "manufacturer_id" else maker_id[r["maker"]] for c in ccols] for r in t["recall"]))
        copy_rows(cur, "quarantine", ["source", "record_key", "rule", "detail", "raw"], t["quarantine"])
        cur.execute(LINK_SQL)
        counts = {}
        for table in ("dim_product_code", "dim_manufacturer", "fact_report", "report_device", "report_problem",
                      "report_patient_problem", "report_text", "fact_recall", "report_recall_link", "quarantine"):
            counts[table] = cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
        counts["links_by_type"] = dict(cur.execute(
            "SELECT link_type, count(*) FROM report_recall_link GROUP BY 1 ORDER BY 1").fetchall())
        counts["quarantine_by_rule"] = dict(cur.execute(
            "SELECT rule, count(*) FROM quarantine GROUP BY 1 ORDER BY 1").fetchall())
        counts["raw_records"] = t["raw_counts"]
        files = sorted(raw.glob("*.jsonl.gz"))
        checksums = {p.name: sha256(p) for p in files}
        run_id = "load-" + started.strftime("%Y%m%dT%H%M%SZ")
        cur.execute("INSERT INTO load_run VALUES (%s, %s, now(), %s, %s)",
                    (run_id, started, json.dumps(checksums), json.dumps(counts)))
        stats = pipeline_stats(cur) if write_summary else {}
        con.commit()
    summary = {"run_id": run_id, "schema": schema, "stats": stats, "raw_dir": str(raw.relative_to(ROOT)) if raw.is_relative_to(ROOT) else str(raw),
               "counts": counts, "raw_checksums": checksums}
    if write_summary:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "load_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n",
                                               encoding="utf-8", newline="\n")
    print(f"{run_id}: {counts['fact_report']:,} reports, {counts['fact_recall']:,} recalls, "
          f"{counts['quarantine']:,} quarantined, links {counts['links_by_type']} -> schema {schema}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Load raw openFDA files into PostgreSQL")
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--schema", default="core")
    ap.add_argument("--no-summary", action="store_true", help="do not write results/phase2/load_summary.json")
    a = ap.parse_args()
    load(a.raw.resolve(), a.schema, write_summary=not a.no_summary)
