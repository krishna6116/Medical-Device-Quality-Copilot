"""Phase 8 part 2: independent check of the Power BI report (criteria in dashboards/powerbi_scorecard.json).

Run:  python -m dashboards.verify_powerbi --list   writes dashboards/powerbi_exports.json (which visuals to export, and the values expected)
      python -m dashboards.verify_powerbi          checks C1-C5 and writes dashboards/powerbi_evidence.json

Method: the exported CSV files are re-read with pandas and compared with SQL written here against core_all / analytics_all
(not the powerbi views) and with the app's snapshot files. Battery device families are re-derived in Python from brand names.
Needs the local database and data/powerbi/ (git-ignored), so it runs locally, not in CI. Items whose report-side evidence does not
exist yet are reported as PENDING, never as passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "powerbi"
FIG = ROOT / "docs" / "figures" / "powerbi"
PBIP = Path(r"C:\Users\krish\Documents\MedicalDeviceCopilot.pbip")
PAGES = ["Overview", "Trends and failure modes", "Companies and recalls", "Battery investigation"]
NOTES = ["not failure rates", "still arriving"]
CAUSE = "cannot show that the recall caused"
FAMILIES = ["ACCOLADE", "PROPONENT", "ESSENTIO", "ALTRUA", "VITALIO", "INGENIO", "FORMIO", "ADVANTIO"]
RECALL_FAMILIES = {"ACCOLADE", "PROPONENT", "ESSENTIO", "ALTRUA"}


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / name, dtype=str, keep_default_na=False)


def sql_frames() -> dict:
    """Separate SQL on the base tables (written independently of powerbi_views.sql)."""
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    q = {
        "base": """SELECT fr.mdr_report_key::text AS key, fr.product_code, fr.date_received, fr.event_type, dm.parent_company, rf.mode, fr.brand_name
                   FROM core_all.fact_report fr, core_all.dim_manufacturer dm, analytics_all.report_failure_mode rf
                   WHERE fr.manufacturer_id = dm.manufacturer_id AND rf.mdr_report_key = fr.mdr_report_key""",
        "recalls": """SELECT fc.product_res_number AS recall_number, fc.res_event_number::text AS recall_event, fc.product_code, dm.parent_company AS company
                      FROM core_all.fact_recall fc, core_all.dim_manufacturer dm WHERE fc.manufacturer_id = dm.manufacturer_id""",
        "products": "SELECT product_code FROM core_all.dim_product_code",
    }
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        con.execute("SET TRANSACTION READ ONLY")
        out = {}
        for k, s in q.items():
            cur = con.execute(s)
            out[k] = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    b = out["base"]
    d = pd.to_datetime(b["date_received"])
    b["quarter"] = d.dt.year.astype(str) + "Q" + d.dt.quarter.astype(str)
    return out


def family_of(brand: str) -> str:
    words = re.sub(r"[^A-Z]+", " ", (brand or "").upper()).split()
    for w in words:
        if w in FAMILIES:
            return w
    return "OTHER"


def battery_expected(base: pd.DataFrame) -> pd.DataFrame:
    d = pd.to_datetime(base["date_received"])
    sel = base[(base["product_code"] == "LWP") & (base["mode"] == "C_BATTERY") & (base["parent_company"] == "BOSTON SCIENTIFIC")
               & (d >= "2025-01-01") & (d <= "2026-09-30")].copy()
    sel["period"] = (pd.to_datetime(sel["date_received"]) <= "2025-09-30").map({True: "2025Q1-2025Q3", False: "2025Q4-2026Q3"})
    sel["family"] = sel["brand_name"].map(family_of)
    return sel


def counts(df: pd.DataFrame, cols: list) -> dict:
    return {tuple(k) if isinstance(k, tuple) else (k,): int(v) for k, v in df.groupby(cols).size().items()}


def expected_exports(f: dict) -> dict:
    """The values each exported visual must show (all products, no slicer selection)."""
    b = f["base"]
    bq = b.groupby("quarter").size()
    bm = b.groupby("mode").size().sort_values(ascending=False)
    top = b.groupby("parent_company").size().sort_values(ascending=False).head(10)
    bat = battery_expected(b).groupby(["family", "period"]).size()
    return {
        "reports_by_quarter.csv": {"page": "Overview", "visual": "column chart, Reports by quarter", "key": ["quarter"], "values": {"Reports": {k: int(v) for k, v in bq.items()}}},
        "reports_by_failure_mode.csv": {"page": "Trends and failure modes", "visual": "bar chart, Reports by failure_mode", "key": ["failure_mode"], "values": {"Reports": {k: int(v) for k, v in bm.items()}}},
        "top_companies.csv": {"page": "Companies and recalls", "visual": "company table (top 10)", "key": ["company"],
                              "values": {"Reports": {k: int(v) for k, v in top.items()}, "Share of reports": {k: round(v / len(b), 6) for k, v in top.items()}}},
        "battery_families.csv": {"page": "Battery investigation", "visual": "stacked bar, Battery family reports by family and period", "key": ["family", "period"],
                                 "values": {"Battery family reports": {f"{a}|{p}": int(v) for (a, p), v in bat.items()}}},
    }


def number(s: str) -> float:
    s = str(s).strip().replace(",", "")
    return float(s[:-1]) / 100 if s.endswith("%") else float(s)


def check_exports(exp: dict) -> tuple[bool | None, dict]:
    folder = FIG / "exports"
    if not folder.exists() or not any(folder.glob("*.csv")):
        return None, {"status": "PENDING: no exports in docs/figures/powerbi/exports yet"}
    detail, compared, bad = {}, 0, []
    for name, spec in exp.items():
        p = folder / name
        if not p.exists():
            detail[name] = "missing"
            bad.append(name)
            continue
        df = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        cols = {c.strip().lower(): c for c in df.columns}
        try:
            keys = [cols[k.lower()] for k in spec["key"]]
        except KeyError:
            detail[name] = f"columns {list(df.columns)} lack {spec['key']}"
            bad.append(name)
            continue
        n = 0
        for measure, want in spec["values"].items():
            col = next((c for lc, c in cols.items() if lc == measure.lower() or lc.startswith(measure.lower())), None)
            if col is None:
                detail[name] = f"no column for {measure}"
                bad.append(name)
                break
            got = {"|".join(r[k].strip() for k in keys): number(r[col]) for _, r in df.iterrows() if r[col].strip()}
            for k, v in want.items():
                tol = 0.0005 if "Share" in measure else 0
                if k not in got or abs(got[k] - v) > tol:
                    bad.append(f"{name}:{k}:{measure} expected {v} got {got.get(k)}")
                n += 1
        compared += n
        detail.setdefault(name, f"{n} values compared")
    ok = compared >= 12 and not bad
    return ok, {"values_compared": compared, "problems": bad[:20], "files": detail}


def report_texts() -> tuple[list, list]:
    """Model files (data sources) and report files (pages, text boxes) of the .pbip project, as text."""
    base = PBIP.parent
    model = [p for d in base.glob(PBIP.stem + ".SemanticModel") for p in d.rglob("*") if p.is_file() and p.suffix in {".tmdl", ".bim", ".json", ".pq"}]
    report = [p for d in base.glob(PBIP.stem + ".Report") for p in d.rglob("*") if p.is_file() and p.suffix in {".json", ".pbir"}]
    return model, report


def main(list_only: bool) -> None:
    f = sql_frames()
    exp = expected_exports(f)
    if list_only:
        out = {k: {**v, "values": {m: dict(sorted(d.items())) for m, d in v["values"].items()}} for k, v in exp.items()}
        out = {"how": "In Power BI Desktop, on the named page, visual: More options (...), Export data, Summarized data, .csv. Save under docs/figures/powerbi/exports/ with this file name. No slicer selection (all products).",
               "exports": out}
        (ROOT / "dashboards" / "powerbi_exports.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print("wrote dashboards/powerbi_exports.json:", {k: sum(len(d) for d in v["values"].values()) for k, v in exp.items()})
        return

    items, b = {}, f["base"]

    # C1: files match the manifest; the report reads only those files
    man = json.loads((ROOT / "dashboards" / "powerbi_export_manifest.json").read_text(encoding="utf-8"))
    c1 = {name: (DATA / name).exists() and hashlib.sha256((DATA / name).read_bytes()).hexdigest() == m["sha256"]
          and len(read(name)) == m["rows"] for name, m in man.items()}
    model, _ = report_texts()
    if model:
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in model)
        c1["report sources are CSV files in data\\powerbi"] = "Csv.Document" in text and "data\\powerbi" in text.replace("/", "\\").replace("\\\\", "\\")
        c1["no database source in the model"] = not re.search(r"PostgreSQL\.Database|Sql\.Database|Odbc\.|Npgsql", text)
        c1["no password in the model"] = not re.search(r"(?i)password|pwd=", text)
        c1_ok = all(c1.values())
    else:
        c1["report model files"] = "PENDING: MedicalDeviceCopilot.SemanticModel not found"
        c1_ok = None
    items["C1"] = (c1_ok, c1)

    # C2: exported files equal separate SQL and the snapshots
    r = read("reports.csv")
    c2 = {}
    c2["one row per report, same report keys as SQL"] = r["mdr_report_key"].is_unique and set(r["mdr_report_key"]) == set(b["key"])
    for cols, scols in ((["product_code"], ["product_code"]), (["product_code", "quarter", "event_type"], ["product_code", "quarter", "event_type"]),
                        (["failure_mode"], ["mode"]), (["company"], ["parent_company"])):
        c2["counts by " + ", ".join(cols)] = counts(r, cols) == counts(b, scols)
    snap = pd.read_csv(ROOT / "dashboards" / "snapshots" / "quarterly.csv", dtype={"reports": int})
    c2["equals app snapshot quarterly.csv"] = counts(r, ["product_code", "quarter", "event_type"]) == {(p, q, e): n for p, q, e, n in snap.itertuples(index=False)}
    rc = read("recalls.csv")
    c2["recalls equal SQL (numbers, events, products, companies)"] = (sorted(map(tuple, rc[["recall_number", "recall_event", "product_code", "company"]].values.tolist()))
                                                                       == sorted(map(tuple, f["recalls"].astype(str).values.tolist())))
    c2["reasons are single-line and at most 300 characters"] = bool((rc["reason"].str.len() <= 300).all() and not rc["reason"].str.contains("\n").any())
    c2["products equal SQL"] = sorted(read("products.csv")["product_code"]) == sorted(f["products"]["product_code"])
    book = json.loads((ROOT / "config" / "failure_modes.json").read_text(encoding="utf-8"))
    c2["failure modes equal the codebook"] = sorted(read("failure_modes.csv")["failure_mode"]) == sorted(m for fam in book["families"].values() for m in fam["modes"])
    bf, be = read("battery_families.csv"), battery_expected(b)
    c2["battery families equal the Python re-derivation"] = dict(zip(bf["mdr_report_key"], zip(bf["period"], bf["family"]))) == dict(zip(be["key"], zip(be["period"], be["family"])))
    bs = pd.read_csv(ROOT / "dashboards" / "snapshots" / "battery_brands.csv", dtype={"reports": int})
    c2["equals app snapshot battery_brands.csv"] = counts(bf, ["period", "family"]) == {(p, a): n for p, a, n in bs.itertuples(index=False)}
    items["C2"] = (all(c2.values()), c2)

    # C3: values exported from the report
    items["C3"] = check_exports(exp)

    # C4 and C5: pages, colours, notes, PDF and PNGs
    _, report = report_texts()
    pdf, pngs = (FIG / "MedicalDeviceCopilot.pdf").exists(), [(FIG / f"page{i}.png").exists() for i in range(1, 5)]
    if report:
        rtext = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in report)
        names = re.findall(r'"displayName"\s*:\s*"([^"]+)"', rtext)
        theme = json.loads((ROOT / "dashboards" / "powerbi_theme.json").read_text(encoding="utf-8"))
        themes = [p for p in PBIP.parent.glob(PBIP.stem + ".Report/**/*.json") if '"dataColors"' in p.read_text(encoding="utf-8", errors="replace")]
        c4 = {"four pages with the planned names": [n for n in names if n in PAGES] and sorted(set(names) & set(PAGES)) == sorted(PAGES),
              "app colours (theme dataColors)": any(json.loads(p.read_text(encoding="utf-8")).get("dataColors", [])[:4] == theme["dataColors"][:4] for p in themes),
              "PDF committed": pdf, "PNG of every page": all(pngs)}
        pages = sorted(PBIP.parent.glob(PBIP.stem + ".Report/definition/pages/*/"))
        per_page = {}
        for d in pages:
            t = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in d.rglob("*.json"))
            m = re.search(r'"displayName"\s*:\s*"([^"]+)"', (d / "page.json").read_text(encoding="utf-8") if (d / "page.json").exists() else "")
            per_page[m.group(1) if m else d.name] = all(n in t for n in NOTES) and (CAUSE in t if m and m.group(1) == "Battery investigation" else True)
        c5 = {"pages found": len(per_page) >= 4, **{f"notes on {k}": v for k, v in per_page.items()}}
        items["C4"] = (all(bool(v) for v in c4.values()), c4)
        items["C5"] = (all(c5.values()), c5)
    else:
        items["C4"] = (None, {"status": "PENDING: MedicalDeviceCopilot.Report not found", "PDF": pdf, "PNGs": pngs})
        items["C5"] = (None, {"status": "PENDING: MedicalDeviceCopilot.Report not found"})

    score = sum(1 for ok, _ in items.values() if ok)
    out = {"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "score": f"{score}/5",
           "items": {k: {"result": "PASS" if ok else ("PENDING" if ok is None else "FAIL"), "checks": {c: (v if isinstance(v, (str, int)) and not isinstance(v, bool) else bool(v)) if not isinstance(v, (dict, list)) else v for c, v in d.items()}}
                     for k, (ok, d) in items.items()}}
    (ROOT / "dashboards" / "powerbi_evidence.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for k, v in out["items"].items():
        print(k, v["result"])
        for c, x in v["checks"].items():
            if x is not True:
                print("   ", c, ":", x)
    print("score", out["score"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    main(ap.parse_args().list)
