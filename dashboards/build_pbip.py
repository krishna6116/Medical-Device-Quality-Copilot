"""Phase 8 part 2: write the Power BI project's model and pages as files (PBIP: TMDL model + PBIR report).

Run with Power BI Desktop CLOSED:  python -m dashboards.build_pbip [--report-only]
Needs an existing project saved by Power BI Desktop at C:/Users/krish/Documents/MedicalDeviceCopilot.pbip (it provides the
base theme and file versions); this script replaces its tables, relationships, measures, custom theme and pages.
The model reads only the exported CSV files in data/powerbi (no database connection). Then open the .pbip and press Refresh.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIP = Path(r"C:\Users\krish\Documents\MedicalDeviceCopilot.pbip")
SM = PBIP.parent / (PBIP.stem + ".SemanticModel") / "definition"
RP = PBIP.parent / (PBIP.stem + ".Report")
DATA = ROOT / "data" / "powerbi"

NOTE = "Report counts are not failure rates. Reports after 2026Q3 are still arriving (the latest quarter is incomplete)."
CAUSE = ("A recall for the ACCOLADE family started on 2025-08-20. Timing and device families line up with the jump in battery reports; "
         "the data cannot show that the recall caused the reports.")

TABLES = {  # column: M type ("text" or "date")
    "products": {"product_code": "text", "device_name": "text", "family": "text", "product": "text"},
    "reports": {"mdr_report_key": "text", "product_code": "text", "date_received": "date", "quarter_start": "date", "quarter": "text",
                "event_type": "text", "company": "text", "failure_mode": "text", "incomplete_period": "text"},
    "failure_modes": {"failure_mode": "text", "definition": "text"},
    "recalls": {"recall_number": "text", "recall_event": "text", "product_code": "text", "company": "text", "started": "date",
                "status": "text", "root_cause": "text", "reason": "text"},
    "battery_families": {"mdr_report_key": "text", "quarter": "text", "period": "text", "family": "text"},
}
MEASURES = {
    "reports": [("Reports", "COUNTROWS ( reports )", "#,0"),
                ("Deaths", 'CALCULATE ( [Reports], reports[event_type] = "Death" )', "#,0"),
                ("Battery reports", 'CALCULATE ( [Reports], reports[failure_mode] = "C_BATTERY" )', "#,0"),
                ("Share of reports", "DIVIDE ( [Reports], CALCULATE ( [Reports], ALL ( reports[company] ) ) )", "0.0%;-0.0%;0.0%")],
    "recalls": [("Recall records", "COUNTROWS ( recalls )", "#,0"),
                ("Recall events", "DISTINCTCOUNT ( recalls[recall_event] )", "#,0")],
    "battery_families": [("Battery family reports", "COUNTROWS ( battery_families )", "#,0"),
                         ("Share in recall families", 'DIVIDE ( CALCULATE ( COUNTROWS ( battery_families ), battery_families[family] IN { "ACCOLADE", "PROPONENT", "ESSENTIO", "ALTRUA" } ), COUNTROWS ( battery_families ) )', "0.0%;-0.0%;0.0%")],
}
RELATIONSHIPS = [("reports", "product_code", "products", "product_code"), ("recalls", "product_code", "products", "product_code"),
                 ("reports", "failure_mode", "failure_modes", "failure_mode")]


def q(name: str) -> str:
    return f"'{name}'" if not name.replace("_", "").isalnum() else name


def table_tmdl(name: str, cols: dict) -> str:
    path = str(DATA / f"{name}.csv")
    types = ", ".join(f'{{"{c}", type {t}}}' for c, t in cols.items())
    out = [f"table {name}", ""]
    for m, expr, fmt in MEASURES.get(name, []):
        out += [f"\tmeasure {q(m)} = {expr}", f"\t\tformatString: {fmt}", ""]
    for c, t in cols.items():
        out += [f"\tcolumn {c}", f"\t\tdataType: {'dateTime' if t == 'date' else 'string'}"]
        if t == "date":
            out.append("\t\tformatString: yyyy-mm-dd")
        out += ["\t\tsummarizeBy: none", f"\t\tsourceColumn: {c}", "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    out += [f"\tpartition {name} = m", "\t\tmode: import", "\t\tsource =", "\t\t\t\tlet",
            f'\t\t\t\t    Source = Csv.Document(File.Contents("{path}"), [Delimiter=",", Columns={len(cols)}, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
            "\t\t\t\t    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
            f'\t\t\t\t    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-US")',
            "\t\t\t\tin", "\t\t\t\t    Typed", "", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def write_model() -> None:
    (SM / "tables").mkdir(exist_ok=True)
    for p in (SM / "tables").glob("*.tmdl"):
        p.unlink()
    for name, cols in TABLES.items():
        (SM / "tables" / f"{name}.tmdl").write_text(table_tmdl(name, cols), encoding="utf-8")
    rel = []
    for i, (ft, fc, tt, tc) in enumerate(RELATIONSHIPS):
        rel += [f"relationship rel_{ft}_{fc}_{i}", f"\tfromColumn: {ft}.{fc}", f"\ttoColumn: {tt}.{tc}", ""]
    (SM / "relationships.tmdl").write_text("\n".join(rel), encoding="utf-8")
    model = (SM / "model.tmdl").read_text(encoding="utf-8")
    model = model.replace("annotation __PBI_TimeIntelligenceEnabled = 1", "annotation __PBI_TimeIntelligenceEnabled = 0")
    model = "\n".join(l for l in model.splitlines() if not l.startswith("ref table")).rstrip() + "\n\n"
    model += "\n".join(f"ref table {t}" for t in TABLES) + "\n"
    (SM / "model.tmdl").write_text(model, encoding="utf-8")


# ---------- report (PBIR) ----------

def col(e, p):
    return {"Column": {"Expression": {"SourceRef": {"Entity": e}}, "Property": p}}


def meas(e, p):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": e}}, "Property": p}}


def proj(f):
    k = "Column" if "Column" in f else "Measure"
    e, p = f[k]["Expression"]["SourceRef"]["Entity"], f[k]["Property"]
    return {"field": f, "queryRef": f"{e}.{p}", "nativeQueryRef": p}


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def in_filter(name, e, p, values):
    return {"name": name, "field": col(e, p), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "t", "Entity": e, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": p}}],
                                                       "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values]}}}]}}


class Page:
    def __init__(self, pid, title):
        self.pid, self.title, self.visuals, self.filters = pid, title, [], []
        self.text(f"{title}", 24, 8, 1000, 52, size="20pt", bold=True)
        self.text(NOTE, 24, 668, 1232, 44, size="11pt", color="#5B6B7C")

    def add(self, vtype, x, y, w, h, roles=None, title=None, sort=None, filters=None, objects=None):
        v = {"visualType": vtype}
        if roles:
            v["query"] = {"queryState": {r: {"projections": [proj(f) for f in fs]} for r, fs in roles.items()}}
            if sort:
                f, d = sort
                v["query"]["sortDefinition"] = {"sort": [{"field": f, "direction": d}], "isDefaultSort": True}
        if objects:
            v["objects"] = objects
        if title:
            v["visualContainerObjects"] = {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{title}'")}}],
                                          "subTitle": [{"properties": {"show": lit("false")}}]}
        v["drillFilterOtherVisuals"] = True
        name = f"{self.pid}_v{len(self.visuals):02d}"
        vis = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json",
               "name": name, "position": {"x": x, "y": y, "z": len(self.visuals) * 1000, "height": h, "width": w, "tabOrder": len(self.visuals) * 1000},
               "visual": v}
        if filters:
            vis["filterConfig"] = {"filters": filters}
        self.visuals.append(vis)

    def text(self, s, x, y, w, h, size="12pt", bold=False, color="#16212E"):
        style = {"fontSize": size, "color": color}
        if bold:
            style["fontWeight"] = "bold"
        self.add("textbox", x, y, w, h, objects={"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": s, "textStyle": style}]}]}}]})

    def slicer(self):
        self.add("slicer", 24, 72, 240, 300, roles={"Values": [col("products", "product")]}, title="Product")


def pages() -> list:
    R, Q = meas("reports", "Reports"), col("reports", "quarter")
    p1 = Page("overview", "Overview")
    p1.slicer()
    for i, m in enumerate([R, meas("reports", "Deaths"), meas("recalls", "Recall records"), meas("recalls", "Recall events")]):
        p1.add("card", 284 + i * 244, 72, 232, 110, roles={"Values": [m]})
    p1.add("clusteredColumnChart", 284, 196, 972, 460, roles={"Category": [Q], "Y": [R]}, title="Reports by quarter", sort=(Q, "Ascending"))

    p2 = Page("trends", "Trends and failure modes")
    p2.slicer()
    p2.add("lineChart", 284, 72, 972, 270, roles={"Category": [Q], "Y": [R]}, title="Reports by quarter", sort=(Q, "Ascending"))
    fm = col("failure_modes", "failure_mode")
    p2.add("clusteredBarChart", 284, 354, 476, 302, roles={"Category": [fm], "Y": [R]}, title="Reports by failure mode", sort=(R, "Descending"))
    p2.add("tableEx", 772, 354, 484, 302, roles={"Values": [fm, R, col("failure_modes", "definition")]}, title="Failure modes", sort=(R, "Descending"))

    p3 = Page("companies", "Companies and recalls")
    p3.slicer()
    p3.add("tableEx", 284, 72, 500, 584, roles={"Values": [col("reports", "company"), R, meas("reports", "Share of reports")]},
           title="Companies by reports (top 10 in the export check)", sort=(R, "Descending"))
    st = col("recalls", "started")
    p3.add("tableEx", 796, 72, 460, 584, roles={"Values": [col("recalls", "recall_number"), col("recalls", "company"), st, col("recalls", "status"), col("recalls", "reason")]},
           title="Recalls, newest first", sort=(st, "Descending"))

    p4 = Page("battery", "Battery investigation")
    p4.filters = [in_filter("page_lwp", "reports", "product_code", ["LWP"])]
    p4.add("lineChart", 24, 72, 700, 300, roles={"Category": [Q], "Y": [meas("reports", "Battery reports")], "Series": [col("reports", "company")]},
           title="Pacemaker battery reports by quarter", sort=(Q, "Ascending"),
           filters=[in_filter("f_company", "reports", "company", ["BOSTON SCIENTIFIC", "ABBOTT"])])
    share = meas("battery_families", "Share in recall families")
    for i, period in enumerate(["2025Q1-2025Q3", "2025Q4-2026Q3"]):
        p4.add("card", 744 + i * 262, 72, 250, 176, roles={"Values": [share]}, title=f"Share in recall families, {period}",
               filters=[in_filter(f"f_period{i}", "battery_families", "period", [period])])
    p4.add("barChart", 24, 384, 700, 272, roles={"Category": [col("battery_families", "family")], "Y": [meas("battery_families", "Battery family reports")],
                                                  "Series": [col("battery_families", "period")]},
           title="Boston Scientific battery reports by device family and period", sort=(meas("battery_families", "Battery family reports"), "Descending"))
    p4.text(CAUSE, 744, 264, 512, 200, size="13pt")
    return [p1, p2, p3, p4]


def write_report() -> None:
    d = RP / "definition"
    shutil.rmtree(d / "pages")
    (d / "pages").mkdir()
    ps = pages()
    for p in ps:
        pd_ = d / "pages" / p.pid
        (pd_ / "visuals").mkdir(parents=True)
        page = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
                "name": p.pid, "displayName": p.title, "displayOption": "FitToPage", "height": 720, "width": 1280}
        if p.filters:
            page["filterConfig"] = {"filters": p.filters}
        (pd_ / "page.json").write_text(json.dumps(page, indent=2), encoding="utf-8")
        for v in p.visuals:
            (pd_ / "visuals" / v["name"]).mkdir()
            (pd_ / "visuals" / v["name"] / "visual.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
    (d / "pages" / "pages.json").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [p.pid for p in ps], "activePageName": ps[0].pid}, indent=2), encoding="utf-8")
    # custom theme = the app colours
    reg = RP / "StaticResources" / "RegisteredResources"
    reg.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "dashboards" / "powerbi_theme.json", reg / "MedicalDeviceCopilot.json")
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    rep["themeCollection"]["customTheme"] = {"name": "MedicalDeviceCopilot.json", "reportVersionAtImport": rep["themeCollection"]["baseTheme"]["reportVersionAtImport"],
                                             "type": "RegisteredResources"}
    rep["resourcePackages"] = [r for r in rep["resourcePackages"] if r["type"] != "RegisteredResources"] + [
        {"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": "MedicalDeviceCopilot.json", "path": "MedicalDeviceCopilot.json", "type": "CustomTheme"}]}]
    (d / "report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import sys
    if "--report-only" not in sys.argv:
        write_model()
    write_report()
    print("wrote model (5 tables, 3 relationships, 8 measures) and 4 pages to", PBIP.parent)
