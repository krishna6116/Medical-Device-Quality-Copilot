"""Numbers for the guided investigation, computed from the snapshots (shared by the Home and investigation pages)."""

from __future__ import annotations

import common as C

RECALL_FAMILIES = ("ACCOLADE", "PROPONENT", "ESSENTIO", "ALTRUA")  # the families the 2025 recall text names
BEFORE, AFTER = "2025Q1-2025Q3", "2025Q4-2026Q3"


def numbers() -> dict:
    b = C.csv("battery.csv")
    bs = {r.quarter: int(r.reports) for r in b.itertuples() if r.company == "BOSTON SCIENTIFIC"}
    ab = {r.quarter: int(r.reports) for r in b.itertuples() if r.company == "ABBOTT"}
    fam = C.csv("battery_brands.csv")
    share = {}
    for p in (BEFORE, AFTER):
        rows = fam[fam["period"] == p]
        total = int(rows["reports"].sum())
        named = int(rows[rows["family"].isin(RECALL_FAMILIES)]["reports"].sum())
        share[p] = (named, total)
    rc = C.csv("recalls.csv")
    accolade = rc[(rc["product"] == "LWP") & (rc["company"] == "BOSTON SCIENTIFIC") & (rc["started"] == "2025-08-20")]
    return {"bs_q3": bs["2025Q3"], "bs_q4": bs["2025Q4"], "bs_peak_q": max((q for q in bs if q <= C.ref()["last_complete_quarter"]), key=lambda q: bs[q]),
            "bs": bs, "ab_q3": ab["2025Q3"], "ab_q4": ab["2025Q4"], "jump": bs["2025Q4"] / bs["2025Q3"], "share": share,
            "recall_records": len(accolade), "recall_event": accolade["recall_event"].iloc[0], "recall_first": accolade["recall_number"].min(),
            "recall_reason": accolade.sort_values("recall_number")["reason"].iloc[0]}
