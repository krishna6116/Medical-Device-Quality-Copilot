# Data card: openFDA device adverse events and recalls (project scope)

Counts and statistics live in [EDA_FINDINGS.md](EDA_FINDINGS.md) (generated); this card explains what the data is and is not.

## Source

- **Adverse-event reports:** FDA MAUDE (Manufacturer and User Facility Device Experience), served by the openFDA endpoint `device/event`. One record = one Medical Device Report (MDR).
- **Recalls:** openFDA `device/recall` (one record per recalled product; one firm action, a "recall event", often covers several products).
- **Classification:** openFDA `device/classification` (product code -> device name, class, specialty).
- **Licence:** public domain (CC0). FDA's disclaimer applies: the data are unvalidated and must not be used for medical decisions.

## Scope (pre-registered, `config/scope.json`)

Five product codes: LPH (uncemented hip), JWH (cemented knee), MBH (uncemented knee), LWP (pacemaker), LZG (insulin pump). Reports **received by FDA** 2022-01-01 to 2024-12-31; all recalls for those codes, any year. Downloaded 2026-11-21 (openFDA data as of 2026-11-11), pinned by `data/checksums.sha256`. Infusion pumps (FRN) and large insulin-dosing codes were left out for size and single-manufacturer dominance (reasons in the scope file).

## Who reports, and why it matters

- **Manufacturers must report** deaths, serious injuries and malfunctions that could cause them; device user facilities (hospitals) must report deaths and serious injuries; patients and clinicians may report voluntarily.
- So large manufacturers appear more often partly because they sell more and have formal complaint systems, not only because their devices fail more.
- Reports are often filed weeks to years after the event (see the reporting-lag question), so the most recent months are always incomplete.

## What a report is not

- **Not a confirmed failure.** It says a device *may* have caused or contributed to an event. Many reports state no device problem was found.
- **Not a rate.** There is no count of devices in use, so report counts cannot be turned into failure rates or compared across companies as quality scores.
- **Not complete.** Under-reporting is known; duplicates and follow-up reports exist; some fields are blank or inconsistent (one recall has the initiation date '0013-11-26').
- **Not proof of cause.** Event type "Injury" for an implant usually means another operation was needed, whatever the reason.

## Fields we use and fields we drop

- **Use:** report key and number, dates (received, event), event type, FDA problem terms, narrative text (event description + manufacturer narrative), device brand / generic name / model / manufacturer / product code; recall dates, status, reason, root cause, firm, 510(k) numbers.
- **Never loaded (Phase 2):** every manufacturer contact field (names, phone numbers, addresses) and patient age, sex, weight, race and ethnicity; patient information is limited to FDA patient-problem terms. Verified by criterion P3 in `docs/PIPELINE.md`. Narratives are already redacted by FDA (`(b)(6)`), but they are still free text, and the assistant must never try to identify a person.
- **Truncated at download:** recall `code_info` (lot/serial lists, up to 9.8 MB for one record) is cut to 2,000 characters.

## Known quirks

- Manufacturer names are written several ways (site names, punctuation); Phase 2 normalises them.
- The most common FDA problem term in four of five codes is "Adverse Event Without Identified Device or Use Problem": the failure mode is in the narrative.
- A few narratives contain a stray control character (0x12) just before an FDA redaction marker, exactly as in FDA's text; the database keeps text as received and later phases normalise it before search.
- openFDA refreshes weekly; late reports keep arriving for past months. Our copy is a snapshot.
