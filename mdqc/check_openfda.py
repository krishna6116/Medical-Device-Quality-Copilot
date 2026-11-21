"""Phase 1 access check: does openFDA's device data really work the way we plan to use it?

Run:  python -m mdqc.check_openfda
Writes docs/openfda_access_check.json (the evidence behind docs/OPENFDA_ACCESS.md).

About 15 small requests, no bulk download. Each probe records what we expected and
what happened, so a reader can see the claim and the proof side by side.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from mdqc.openfda import BASE_URL, OpenFDAClient, build_search, next_search_after

OUT = Path(__file__).resolve().parents[1] / "docs" / "openfda_access_check.json"


def _field_paths(obj, prefix=""):
    paths = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            paths.add(prefix + k)
            paths |= _field_paths(v, prefix + k + ".")
    elif isinstance(obj, list):
        for item in obj[:50]:
            paths |= _field_paths(item, prefix)
    return paths


def _status(url: str) -> tuple[int, str]:
    r = requests.get(url, timeout=60)
    try:
        msg = r.json().get("error", {}).get("code", "OK")
    except ValueError:
        msg = "non-JSON"
    return r.status_code, msg


def main() -> dict:
    c = OpenFDAClient(api_key=None)  # the check is about what works WITHOUT a key
    probes = []

    def probe(name, expected, observed, ok):
        probes.append({"probe": name, "expected": expected, "observed": observed, "pass": bool(ok)})
        print(("PASS " if ok else "FAIL ") + name + ": " + json.dumps(observed)[:160])

    # 1. Every endpoint answers, with record counts and freshness
    endpoints = {}
    for ep in ("event", "recall", "enforcement", "classification"):
        data, _ = c.get(ep, limit=1)
        endpoints[ep] = {"total": data["meta"]["results"]["total"],
                         "last_updated": data["meta"]["last_updated"]}
    probe("endpoints answer", "all four return records", endpoints,
          all(v["total"] > 0 for v in endpoints.values()))

    # 2. Paging rules
    ev = f"{BASE_URL}/device/event.json"
    s999 = _status(f"{ev}?limit=999&search=device.device_report_product_code:FRN")
    probe("limit=999 without key", "200 OK", s999, s999[0] == 200)
    s1000 = _status(f"{ev}?limit=1000&search=device.device_report_product_code:FRN")
    probe("limit=1000 on /device/event without key", "403 API_KEY_MISSING (observed rule)", s1000,
          s1000 == (403, "API_KEY_MISSING"))
    s1001 = _status(f"{ev}?limit=1001")
    probe("limit=1001", "400 BAD_REQUEST", s1001, s1001[0] == 400)
    s_skip = _status(f"{ev}?limit=1&skip=25001")
    probe("skip=25001", "400 BAD_REQUEST", s_skip, s_skip[0] == 400)

    # 3. search_after paging returns new records (needed for anything deeper than 25,000)
    search = build_search(product_code="FRN", date_field="date_received",
                          date_from="20240101", date_to="20240131")
    data1, r1 = c.get("event", search=search, limit=5)
    token = next_search_after(r1.headers.get("Link"))
    data2, _ = c.get("event", search=search, limit=5, skip=0, search_after=token)
    keys1 = {x["mdr_report_key"] for x in data1["results"]}
    keys2 = {x["mdr_report_key"] for x in data2["results"]}
    probe("search_after paging", "page 2 has 5 new report keys",
          {"token": token, "page1": len(keys1), "page2": len(keys2), "overlap": len(keys1 & keys2)},
          token and len(keys2) == 5 and not keys1 & keys2)

    # 4. Search by product code + date range, and server-side counts
    data, _ = c.get("event", search=build_search(product_code="FRN", date_field="date_received",
                                                 date_from="20240101", date_to="20241231"), limit=1)
    frn_2024 = data["meta"]["results"]["total"]
    probe("search: infusion pumps (FRN) received in 2024", "> 0 reports", frn_2024, frn_2024 > 0)
    data, _ = c.get("event", search="date_received:[20240101+TO+20241231]",
                    count="device.device_report_product_code.exact", limit=10)
    probe("count: top product codes, 2024", "10 terms", data["results"], len(data["results"]) == 10)

    # 5. Fields we plan to use exist (narratives, problem codes, event type, device identifiers)
    data, _ = c.get("event", search=build_search(product_code="FRN", date_field="date_received",
                                                 date_from="20240101", date_to="20240131"), limit=100)
    recs = data["results"]
    ev_fields = sorted(_field_paths(recs))
    needed = ["mdr_report_key", "date_received", "event_type", "product_problems", "mdr_text.text",
              "mdr_text.text_type_code", "device.brand_name", "device.manufacturer_d_name",
              "device.device_report_product_code", "device.model_number", "device.openfda.device_name"]
    with_text = sum(1 for x in recs if x.get("mdr_text"))
    probe("event fields", "planned fields present", {"missing": [f for f in needed if f not in ev_fields],
          "with_narrative": f"{with_text}/{len(recs)}"}, all(f in ev_fields for f in needed))

    data, _ = c.get("recall", search="product_code:FRN", limit=100)
    rc_fields = sorted(_field_paths(data["results"]))
    rc_needed = ["product_code", "event_date_initiated", "reason_for_recall", "root_cause_description",
                 "recalling_firm", "k_numbers", "res_event_number", "recall_status", "action"]
    biggest = max(len(x.get("code_info", "")) for x in data["results"])
    probe("recall fields", "planned fields present", {"missing": [f for f in rc_needed if f not in rc_fields],
          "frn_recalls": data["meta"]["results"]["total"], "largest_code_info_chars": biggest},
          all(f in rc_fields for f in rc_needed))

    # 6. Bulk files: sizes only (we do not download them)
    dl = requests.get(f"{BASE_URL}/download.json", timeout=120).json()["results"]["device"]
    bulk = {ep: {"files": len(v["partitions"]),
                 "zipped_mb": round(sum(float(p["size_mb"]) for p in v["partitions"]), 1),
                 "records": v.get("total_records"), "export_date": v.get("export_date")}
            for ep, v in dl.items() if ep in ("event", "recall", "enforcement", "classification")}
    probe("bulk download sizes", "read from download.json, nothing downloaded", bulk, True)

    result = {"checked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "api_key_used": False, "probes": probes,
              "event_fields": ev_fields, "recall_fields": rc_fields,
              "all_pass": all(p["pass"] for p in probes)}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\n{sum(p['pass'] for p in probes)}/{len(probes)} probes pass -> {OUT}")
    return result


if __name__ == "__main__":
    main()
