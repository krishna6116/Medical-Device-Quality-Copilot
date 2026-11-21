# openFDA device data: access check (Phase 1 start)

Checked 2026-11-21 without an API key. Evidence: [`openfda_access_check.json`](openfda_access_check.json), written by `python -m mdqc.check_openfda` (11/11 probes pass). Numbers below come from that file or from the same session's probes.

## What openFDA is

openFDA is the FDA's public API over its own databases. Two of them matter here:

| Endpoint | What one record is | Records | Last updated |
|---|---|---|---|
| `https://api.fda.gov/device/event.json` | One **MAUDE** report (Medical Device Report, MDR): a manufacturer, hospital or patient tells the FDA a device may have caused or contributed to a death, injury or malfunction | 26,849,547 | 2026-11-11 |
| `https://api.fda.gov/device/recall.json` | One **recall** record for a product (reason, root cause, firm, dates, 510(k) numbers) | 59,705 | 2026-11-19 |
| `https://api.fda.gov/device/enforcement.json` | One weekly **enforcement report** entry (recall classification I/II/III) | 40,535 | 2026-11-11 |
| `https://api.fda.gov/device/classification.json` | One **product code** (3 letters, e.g. FRN = infusion pump) with device name and class | 7,103 | - |

Licence: openFDA data is public domain (CC0). Every response carries FDA's disclaimer that results are unvalidated and must not drive medical decisions; the assistant will repeat that limit.

## Limits (measured, then compared with the documentation)

| Rule | Observed | Documented |
|---|---|---|
| Records per request | `limit=1001` → 400 BAD_REQUEST | "largest allowed value for limit is 1000" |
| **Without a key, `/device/event` with `limit=1000`** | **403 API_KEY_MISSING; `limit=999` works** | not documented (observed rule; the client caps at 999 without a key) |
| Offset paging | `skip=25001` → 400 ("Skip value must 25000 or less") | same |
| Deep paging | `search_after` token from the HTTP `Link: rel="next"` header returns the next page (5 new report keys, no overlap) | same |
| Rate | not hit in this check (no rate headers are returned) | no key: 240/minute and **1,000 requests/day** per IP; free key: 240/minute and **120,000/day** |
| No matches | 404 NOT_FOUND "No matches found!" | client turns it into an empty result |

**What this means for us:** 1,000 requests/day x 999 records is ~1M records/day even without a key, which is more than our scope needs. A free key (registration with an email address at open.fda.gov, done by the user, stored only in `.env`) removes the 999 quirk and the daily ceiling. Recommended but not required.

## Search and counting work as planned

- Product code + date range: `search=device.device_report_product_code:FRN+AND+date_received:[20240101+TO+20241231]` → 57,731 infusion-pump reports received in 2024.
- Server-side counts (no download needed): `count=device.device_report_product_code.exact` → top codes in 2024: DZE dental implant 697,102; QBJ glucose monitor 347,117; QFG insulin pump (alternate controller) 273,190; OZP automated insulin dosing 129,592; BZD ventilator 68,263; FRN infusion pump 57,731.
- Note for code: curl/shell users must turn off URL globbing (`curl -g`) or the `[ ]` in date ranges breaks the request.

## Fields that exist

Adverse events (all present in 100/100 sampled FRN reports, every one with narrative text):
`mdr_report_key`, `report_number`, `date_received`, `date_of_event`, `event_type` (Malfunction / Injury / Death / Other), `product_problems` (FDA problem terms, e.g. "Device Alarm System", "Insufficient Flow or Under Infusion"), `patient.patient_problems`, `mdr_text[].text` + `text_type_code` ("Description of Event or Problem", "Additional Manufacturer Narrative"), `device[].brand_name`, `generic_name`, `manufacturer_d_name`, `model_number`, `lot_number`, `device_report_product_code`, `device.openfda.device_name`, `device_class`, `remedial_action`, `type_of_report`. Full list in the evidence file (`event_fields`).

Recalls: `product_code`, `event_date_initiated`, `event_date_posted`, `event_date_terminated`, `recall_status`, `reason_for_recall`, `root_cause_description` (e.g. Device Design, Process control, Software design), `action`, `recalling_firm`, `k_numbers`, `res_event_number`, `product_description`, `product_quantity`, `code_info`.

Narrative length (999 FRN reports): median 250 characters, 90th percentile 784, so one report is roughly one retrieval chunk.

## Surprises to handle in Phase 2

1. **Huge `code_info`**: one recall's lot/serial list was 9.8 MB of text (largest in the first 100 FRN recalls: 253,700 characters); 721 FRN recalls were 67 MB as raw JSON. The client truncates `code_info` to 2,000 characters.
2. **Personal fields**: reports carry manufacturer contact names and phone numbers (`manufacturer_contact_f_name`, `_l_name`, `_phone_number`, ...) and patient age/sex/weight. We drop contact fields at ingest and keep patient fields out of the assistant's index. Narratives are FDA-redacted (`(b)(6)`) but are still free text.
3. **Old reports in a product code**: a product-code search with no date returns reports back to 1997; always filter by `date_received`.
4. **Reports are not proof**: MAUDE has duplicates, under-reporting and reports that later turn out unrelated. Counts are signals, never failure rates (no denominator of devices in use).

## Bulk files (sizes only; nothing downloaded)

From `https://api.fda.gov/download.json` (zipped sizes):

| Dataset | Files | Zipped size | Records |
|---|---|---|---|
| device/event | 378 | **18,952 MB (~19 GB)** | 26.8M |
| device/recall | 1 | 277 MB | 59,705 |
| device/enforcement | 1 | 91 MB | 40,535 |
| device/classification | 1 | 3 MB | 7,103 |

Decision: **no bulk event download.** The API with product-code + date filters gets exactly the slice we need. Phase 1 will fix the scope and tell the user the expected download size before fetching.
