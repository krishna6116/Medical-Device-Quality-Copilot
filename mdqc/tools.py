"""Phase 4 investigation tools: fixed, read-only, parameterised queries the assistant may call.

The model never writes SQL. It picks a tool and arguments; the tool returns JSON. Every number the
assistant states must come from these results (checked by mdqc.verify_phase4), and every report or recall
it cites must appear in them. Tools return pre-computed shares, so the model never has to do arithmetic.

Tools: list_manufacturers, count_reports, trend, failure_modes, search_reports, get_report, find_recalls,
signal_check. Failure modes are the Phase 3 chosen method (FDA terms mapped through the codebook; 70% agreement
with reference labels on the test set), stored in analytics.report_failure_mode.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CODEBOOK = json.loads((ROOT / "config" / "failure_modes.json").read_text(encoding="utf-8"))
CODES = {"LPH": "hip implant (uncemented)", "JWH": "knee implant (cemented)", "MBH": "knee implant (uncemented)",
         "LWP": "pacemaker", "LZG": "insulin pump"}
MODES = {m: d["definition"] for f in CODEBOOK["families"].values() for m, d in f["modes"].items()}
WINDOW = ("2022-01-01", "2024-12-31")
MAX_ROWS = 10


class ToolError(ValueError):
    """A problem with the arguments; returned to the model as an error result so it can correct itself."""


# ---- argument helpers ------------------------------------------------------------------------------
def _code(v, required=True):
    if v is None and not required:
        return None
    v = (v or "").strip().upper()
    if v not in CODES:
        raise ToolError(f"product_code must be one of {sorted(CODES)} ({', '.join(f'{k}={d}' for k, d in CODES.items())})")
    return v


def _date(v, default, lo=WINDOW[0], hi=WINDOW[1]):
    """Parse YYYY-MM-DD and clamp it to [lo, hi] (reports: 2022-2024; recalls: any year 1976-2026)."""
    v = str(v or default).strip()
    try:
        d = date.fromisoformat(v)
    except ValueError as exc:
        raise ToolError(f"dates must be YYYY-MM-DD, got {v!r}") from exc
    return max(date.fromisoformat(lo), min(date.fromisoformat(hi), d)).isoformat()


FAMILY_OF_CODE = {c: f for f, v in CODEBOOK["families"].items() for c in v["codes"]}
FAMILY_OF_MODE = {m: f for f, v in CODEBOOK["families"].items() for m in v["modes"]}


def _mode(v, code=None):
    if v is None:
        return None
    v = str(v).strip().upper()
    if v not in MODES:
        raise ToolError(f"failure_mode must be one of {sorted(MODES)}")
    if code and FAMILY_OF_MODE[v] != FAMILY_OF_CODE[code]:
        allowed = sorted(m for m, f in FAMILY_OF_MODE.items() if f == FAMILY_OF_CODE[code])
        raise ToolError(f"{v} is not a failure mode for {code} ({CODES[code]}); use one of {allowed}")
    return v


def _limit(v, default=5):
    try:
        n = int(v) if v is not None else default
    except (TypeError, ValueError) as exc:
        raise ToolError(f"limit must be a whole number from 1 to {MAX_ROWS}, got {v!r}") from exc
    return max(1, min(n, MAX_ROWS))


def _maker(con, v):
    """Resolve a free-text company name to exactly one parent company (case-insensitive substring)."""
    if v is None:
        return None
    v = str(v)
    if len(v.strip()) < 2:
        raise ToolError("manufacturer must be at least 2 characters; call list_manufacturers to see names")
    pattern = "%" + v.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = [r[0] for r in con.execute("SELECT DISTINCT parent_company FROM core.dim_manufacturer "
                                      "WHERE parent_company ILIKE %s ORDER BY 1", (pattern,)).fetchall()]
    if not rows:
        raise ToolError(f"no manufacturer matches {v!r}; call list_manufacturers first")
    exact = [r for r in rows if r.lower() == v.strip().lower()]
    if len(rows) > 1 and not exact:
        raise ToolError(f"{v!r} matches several manufacturers: {rows[:8]}; use the exact name")
    return exact[0] if exact else rows[0]


def _filters(con, args, alias="r"):
    """WHERE clause + params shared by the counting tools."""
    code = _code(args.get("product_code"), required=False)
    maker = _maker(con, args.get("manufacturer"))
    mode = _mode(args.get("failure_mode"), code)
    d0, d1 = _date(args.get("date_from"), WINDOW[0]), _date(args.get("date_to"), WINDOW[1])
    if d0 > d1:
        raise ToolError("date_from is after date_to")
    where, params = [f"{alias}.date_received BETWEEN %s AND %s"], [d0, d1]
    if code:
        where.append(f"{alias}.product_code = %s")
        params.append(code)
    if maker:
        where.append("m.parent_company = %s")
        params.append(maker)
    if mode:
        where.append("f.mode = %s")
        params.append(mode)
    echo = {"product_code": code, "manufacturer": maker, "failure_mode": mode, "date_from": d0, "date_to": d1}
    return " AND ".join(where), params, echo


FROM = ("core.fact_report r JOIN core.dim_manufacturer m USING (manufacturer_id) "
        "JOIN analytics.report_failure_mode f USING (mdr_report_key)")


# ---- tools ---------------------------------------------------------------------------------------------
def list_manufacturers(con, args):
    code = _code(args.get("product_code"))
    if args.get("manufacturer"):
        raise ToolError("list_manufacturers lists companies; do not pass manufacturer")
    where, params, echo = _filters(con, {**args, "product_code": code})
    rows = con.execute(f"SELECT m.parent_company, count(*) FROM {FROM} WHERE {where} "
                       "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 15", params).fetchall()
    total = con.execute(f"SELECT count(*) FROM {FROM} WHERE {where}", params).fetchone()[0]
    return {"filters": echo, "product_code": code, "device": CODES[code], "total_reports": total,
            "manufacturers": [{"manufacturer": m, "reports": n, "share": round(n / total, 3) if total else 0} for m, n in rows]}


def count_reports(con, args):
    where, params, echo = _filters(con, args)
    total = con.execute(f"SELECT count(*) FROM {FROM} WHERE {where}", params).fetchone()[0]
    by_type = con.execute(f"SELECT r.event_type, count(*) FROM {FROM} WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1",
                          params).fetchall()
    return {"filters": echo, "reports": total,
            "by_event_type": [{"event_type": t, "reports": n, "share": round(n / total, 3) if total else 0} for t, n in by_type]}


def trend(con, args):
    where, params, echo = _filters(con, args)
    gran = (args.get("granularity") or "quarter").lower()
    if gran not in ("month", "quarter", "year"):
        raise ToolError("granularity must be month, quarter or year")
    fmt = {"month": "YYYY-MM", "quarter": "YYYY-\"Q\"Q", "year": "YYYY"}[gran]
    rows = con.execute(f"SELECT to_char(r.date_received, '{fmt}'), count(*) FROM {FROM} WHERE {where} GROUP BY 1 ORDER BY 1",
                       params).fetchall()
    series = [{"period": p, "reports": n} for p, n in rows]
    out = {"filters": echo, "granularity": gran, "series": series,
           "note": "Counts by the date FDA received the report; the latest months fill in later as late reports arrive."}
    if len(series) >= 2 and series[0]["reports"]:
        out["first_to_last_change"] = round((series[-1]["reports"] - series[0]["reports"]) / series[0]["reports"], 3)
    return out


def failure_modes(con, args):
    if args.get("failure_mode"):
        raise ToolError("failure_modes breaks a selection down by mode; do not pass failure_mode")
    where, params, echo = _filters(con, args)
    rows = con.execute(f"SELECT f.mode, count(*) FROM {FROM} WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1", params).fetchall()
    total = sum(n for _, n in rows)
    return {"filters": echo, "reports": total,
            "modes": [{"failure_mode": m, "reports": n, "share": round(n / total, 3), "definition": MODES[m]} for m, n in rows],
            "method_note": "Modes come from FDA problem terms mapped through the project codebook; they agreed with "
                           "reference labels on 70% of test reports (Phase 3)."}


@lru_cache(maxsize=1)
def _embeddings():
    keys = (ROOT / "data" / "processed" / "embeddings_bge_small_keys.txt").read_text(encoding="utf-8").split()
    emb = np.load(ROOT / "data" / "processed" / "embeddings_bge_small.npy").astype(np.float32)
    return {k: i for i, k in enumerate(keys)}, emb


@lru_cache(maxsize=1)
def _model():
    from mdqc import embed
    return embed.load_model()


def search_reports(con, args):
    """Embedding similarity (Phase 3's chosen search). Identical texts are collapsed and counted."""
    query = (args.get("query") or "").strip()
    if len(query) < 3:
        raise ToolError("query must describe what to look for")
    where, params, echo = _filters(con, args)
    limit = _limit(args.get("limit"))
    keys = [k for (k,) in con.execute(f"SELECT r.mdr_report_key FROM {FROM} WHERE {where}", params).fetchall()]
    if not keys:
        return {"filters": echo, "query": query, "matches_considered": 0, "results": []}
    row, emb = _embeddings()
    from mdqc import embed
    qv = embed.encode(_model(), [query], query=True)[0]
    idx = np.array([row[k] for k in keys])
    sims = emb[idx] @ qv
    order = np.argsort(-sims, kind="stable")
    from mdqc.textprep import load_texts
    results, seen = [], {}
    for i in order[: limit * 20]:
        k = keys[int(i)]
        if len(results) >= limit and k not in seen:
            break
        text = load_texts(con, "core", [k])[k]
        sig = text[:300]
        if sig in seen:
            results[seen[sig]]["identical_reports"] += 1
            continue
        if len(results) >= limit:
            continue
        meta = con.execute(f"SELECT r.date_received, m.parent_company, r.event_type, f.mode, r.product_code FROM {FROM} "
                           "WHERE r.mdr_report_key = %s", (k,)).fetchone()
        seen[sig] = len(results)
        results.append({"mdr_report_key": k, "similarity": round(float(sims[int(i)]), 3), "date_received": str(meta[0]),
                        "manufacturer": meta[1], "event_type": meta[2], "failure_mode": meta[3], "product_code": meta[4],
                        "excerpt": text[:300], "identical_reports": 0})
    return {"filters": echo, "query": query, "matches_considered": len(keys), "results": results,
            "note": "identical_reports = further reports among the top matches with the same opening text (templates)."}


def get_report(con, args):
    key = str(args.get("mdr_report_key") or "").strip()
    r = con.execute(f"""SELECT r.mdr_report_key, r.report_number, r.product_code, r.date_received, r.date_of_event,
        r.event_type, m.parent_company, m.raw_name, r.brand_name, r.generic_name, r.model_number, r.pma_pmn_number, f.mode
        FROM {FROM} WHERE r.mdr_report_key = %s""", (key,)).fetchone()
    if not r:
        raise ToolError(f"report {key!r} not found in the project data (LPH, JWH, MBH, LWP, LZG received 2022-2024)")
    from mdqc.textprep import load_texts
    text = load_texts(con, "core", [key])[key]
    terms = [t for (t,) in con.execute("SELECT term FROM core.report_problem WHERE mdr_report_key = %s ORDER BY 1", (key,)).fetchall()]
    pterms = [t for (t,) in con.execute("SELECT term FROM core.report_patient_problem WHERE mdr_report_key = %s ORDER BY 1", (key,)).fetchall()]
    links = con.execute("""SELECT l.product_res_number, l.link_type, l.days_from_initiation, c.event_date_initiated,
        c.root_cause, left(c.reason_for_recall, 300) FROM core.report_recall_link l JOIN core.fact_recall c USING (product_res_number)
        WHERE l.mdr_report_key = %s AND abs(l.days_from_initiation) <= 365
        ORDER BY abs(l.days_from_initiation), l.product_res_number LIMIT 5""", (key,)).fetchall()
    return {"mdr_report_key": r[0], "report_number": r[1], "product_code": r[2], "device": CODES[r[2]],
            "date_received": str(r[3]), "date_of_event": str(r[4]) if r[4] else None, "event_type": r[5],
            "manufacturer": r[6], "manufacturer_as_reported": r[7], "brand_name": r[8], "generic_name": r[9],
            "model_number": r[10], "clearance_number": r[11], "failure_mode": r[12],
            "fda_device_problem_terms": terms, "fda_patient_problem_terms": pterms, "narrative": text[:1500],
            "recalls_within_a_year": [{"recall_number": a, "link": b, "days_from_recall_start": c, "recall_started": str(d),
                                       "root_cause": e, "reason": f} for a, b, c, d, e, f in links],
            "note": "A link means same clearance number, or same company and product code close in time; it is context, not proof."}


def find_recalls(con, args):
    code = _code(args.get("product_code"), required=False)
    maker = _maker(con, args.get("manufacturer"))
    d0 = _date(args.get("date_from"), "1976-01-01", lo="1976-01-01", hi="2026-12-31")
    d1 = _date(args.get("date_to"), "2026-12-31", lo="1976-01-01", hi="2026-12-31")
    if d0 > d1:
        raise ToolError("date_from is after date_to")
    where, params = ["c.event_date_initiated BETWEEN %s AND %s"], [d0, d1]
    if code:
        where.append("c.product_code = %s")
        params.append(code)
    if maker:
        where.append("m.parent_company = %s")
        params.append(maker)
    text = (args.get("text") or "").strip()
    if text:
        where.append("(c.reason_for_recall ILIKE %s OR c.product_description ILIKE %s)")
        params += [f"%{text}%", f"%{text}%"]
    w = " AND ".join(where)
    base = "core.fact_recall c JOIN core.dim_manufacturer m USING (manufacturer_id)"
    total = con.execute(f"SELECT count(*), count(DISTINCT c.res_event_number) FROM {base} WHERE {w}", params).fetchone()
    rows = con.execute(f"""SELECT c.product_res_number, c.res_event_number, c.product_code, m.parent_company,
        c.event_date_initiated, c.recall_status, c.root_cause, left(c.reason_for_recall, 300)
        FROM {base} WHERE {w} ORDER BY c.event_date_initiated DESC, c.product_res_number LIMIT {MAX_ROWS}""", params).fetchall()
    return {"filters": {"product_code": code, "manufacturer": maker, "date_from": d0, "date_to": d1, "text": text or None},
            "recall_records": total[0], "recall_events": total[1], "shown": len(rows),
            "recalls": [{"recall_number": a, "recall_event": b, "product_code": c_, "manufacturer": d, "started": str(e),
                         "status": f, "root_cause": g, "reason": h} for a, b, c_, d, e, f, g, h in rows]}


def signal_check(con, args):
    code = _code(args.get("product_code"))
    maker = _maker(con, args.get("manufacturer"))
    mode = _mode(args.get("failure_mode"), code)
    where, params = ["product_code = %s"], [code]
    if maker:
        where.append("parent_company = %s")
        params.append(maker)
    if mode:
        where.append("mode = %s")
        params.append(mode)
    rows = con.execute(f"""SELECT parent_company, mode, month, count, expected FROM analytics.signal_month
        WHERE {' AND '.join(where)} ORDER BY month DESC, count DESC LIMIT {MAX_ROWS}""", params).fetchall()
    total = con.execute(f"SELECT count(*) FROM analytics.signal_month WHERE {' AND '.join(where)}", params).fetchone()[0]
    return {"filters": {"product_code": code, "manufacturer": maker, "failure_mode": mode}, "signals_total": total,
            "signals": [{"manufacturer": a, "failure_mode": b, "month": c, "reports": d, "expected": round(e, 1)} for a, b, c, d, e in rows],
            "rule": "A month is a signal if it has at least 5 reports and the chance of that many, given the previous 12 "
                    "months' average, is below 0.1% (Poisson). Signals run 2023-01 to 2024-12.",
            "caution": "A signal is a prompt to look closer, not evidence of a defect. In a backtest, 15 of 38 recall events "
                       "had a prior signal versus a 14% base rate."}


# ---- registry ------------------------------------------------------------------------------------------
_COMMON = {
    "product_code": {"type": "string", "enum": sorted(CODES), "description": "FDA product code: " + ", ".join(f"{k}={d}" for k, d in CODES.items())},
    "manufacturer": {"type": "string", "description": "Parent company name or part of it, e.g. 'Insulet', 'Zimmer Biomet'"},
    "failure_mode": {"type": "string", "enum": sorted(MODES), "description": "Failure mode code from the codebook"},
    "date_from": {"type": "string", "description": "YYYY-MM-DD, report received on or after (data covers 2022-01-01 to 2024-12-31)"},
    "date_to": {"type": "string", "description": "YYYY-MM-DD, report received on or before"},
}


def _schema(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


TOOL_SPECS = [
    ("list_manufacturers", list_manufacturers, "List the companies with the most reports for a product code (optionally one failure mode and date range), with counts and shares. Use it to find exact company names or compare companies.",
     _schema({k: _COMMON[k] for k in ("product_code", "failure_mode", "date_from", "date_to")}, ["product_code"])),
    ("count_reports", count_reports, "Count adverse-event reports matching filters, split by event type (Malfunction, Injury, Death, Other).",
     _schema({k: _COMMON[k] for k in ("product_code", "manufacturer", "failure_mode", "date_from", "date_to")})),
    ("trend", trend, "Report counts over time (month, quarter or year) for the given filters, with the first-to-last change.",
     _schema({**{k: _COMMON[k] for k in ("product_code", "manufacturer", "failure_mode", "date_from", "date_to")},
              "granularity": {"type": "string", "enum": ["month", "quarter", "year"]}})),
    ("failure_modes", failure_modes, "Break the matching reports down by failure mode, with counts, shares and definitions.",
     _schema({k: _COMMON[k] for k in ("product_code", "manufacturer", "date_from", "date_to")})),
    ("search_reports", search_reports, "Find reports whose narrative is similar in meaning to a description. Returns report keys and excerpts; identical template texts are collapsed.",
     _schema({"query": {"type": "string", "description": "What to look for, in plain words"},
              **{k: _COMMON[k] for k in ("product_code", "manufacturer", "failure_mode", "date_from", "date_to")},
              "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}}, ["query"])),
    ("get_report", get_report, "Full details of one report: dates, company, device, FDA problem terms, failure mode, narrative and recalls linked within a year.",
     _schema({"mdr_report_key": {"type": "string", "description": "The report's MDR report key, e.g. '16005019'"}}, ["mdr_report_key"])),
    ("find_recalls", find_recalls, "List recall records (most recent first) by product code, company, start date range or words in the recall reason.",
     _schema({"product_code": _COMMON["product_code"], "manufacturer": _COMMON["manufacturer"],
              "date_from": {"type": "string", "description": "YYYY-MM-DD, recall started on or after (recalls cover all years, unlike reports)"},
              "date_to": {"type": "string", "description": "YYYY-MM-DD, recall started on or before"},
              "text": {"type": "string", "description": "Words to find in the recall reason or product description"}})),
    ("signal_check", signal_check, "Early-warning signals (months with unusually many reports) for a product code, optionally one company and failure mode.",
     _schema({k: _COMMON[k] for k in ("product_code", "manufacturer", "failure_mode")}, ["product_code"])),
]
TOOLS = {name: fn for name, fn, _, _ in TOOL_SPECS}
TOOL_DEFINITIONS = [{"name": n, "description": d, "input_schema": s} for n, _, d, s in TOOL_SPECS]
SCHEMAS = {n: s for n, _, _, s in TOOL_SPECS}


def run_tool(con, name: str, args: dict) -> tuple[str, bool]:
    """Execute a tool; returns (JSON text, is_error). Never raises: argument problems and unexpected failures
    come back as error results the model can read, and the database connection is reset after a failed query."""
    if name not in TOOLS:
        return json.dumps({"error": f"unknown tool {name!r}; tools: {sorted(TOOLS)}"}), True
    args = dict(args or {})
    allowed = set(SCHEMAS[name]["properties"])
    unknown = sorted(set(args) - allowed)
    if unknown:
        return json.dumps({"error": f"unknown argument(s) {unknown} for {name}; allowed: {sorted(allowed)}"}), True
    try:
        return json.dumps(TOOLS[name](con, args), default=str, ensure_ascii=False), False
    except ToolError as exc:
        con.rollback()
        return json.dumps({"error": str(exc)}), True
    except Exception as exc:  # noqa: BLE001 - a tool must never crash the investigation
        con.rollback()
        return json.dumps({"error": f"{name} failed ({type(exc).__name__}); check the arguments"}), True
