# Medical Device Quality Copilot v1.0.0

An AI assistant that helps a medical device quality engineer investigate field failures from public FDA data, citing the exact reports. Live app: https://medical-device-copilot.streamlit.app

## Highlights

- Claude Haiku 5.5 answered 78/80 pre-registered questions for $0.10; Opus 5.5 answered 76/80 for $4.01 (not significantly different).
- 15 of 38 recall events were preceded by an early-warning signal (39% vs a 14% base rate).
- Pacemaker battery reports: the recalled families' share rose from 77.9% to 97.5% after the 2025 recall (timing, not cause).
- 233,264 openFDA reports (2022-2026) and 1,626 recalls in PostgreSQL; Streamlit app and Power BI report on snapshots.

## Known limits

Phase 7 scored 4/5 (the first guard withheld 24 of 48 safe answers); Phase 7b labels came from an AI with no human check. Report counts are not failure rates: there is no count of devices in use, and a report does not prove the device caused the event.

Total recorded API spend: $4.50. Details: [results](https://github.com/krishna6116/Medical-Device-Quality-Copilot/blob/main/docs/RESULTS.md), [case study](https://github.com/krishna6116/Medical-Device-Quality-Copilot/blob/main/docs/CASE_STUDY.md).
