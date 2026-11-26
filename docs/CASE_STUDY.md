# Case study: an AI copilot for medical device quality investigations

Report counts are not failure rates: there is no count of devices in use, and a report does not prove the device caused the event.

## The situation

A quality engineer at a device maker is told that complaints about a product are rising. They need to know whether that is real, which failure modes drive it, whether competitors' similar devices were recalled, and what the team already ruled out. The public record is the FDA's MAUDE database: 154,194 adverse-event reports for the 5 device types studied here (hip and knee implants, a pacemaker, an insulin pump) from 2022 to 2024, later 233,264 reports through 2026, plus 1,626 recalls.

## What was built

1. **A trustworthy data layer.** The download equals openFDA's own counts; the PostgreSQL pipeline drops personal fields, quarantines broken records and merges 305 maker names into 101 companies.
2. **Failure modes and early warning.** A codebook over FDA problem terms classifies reports (70% on a held-out test, 61% to 79%); text embeddings did worse (32%). A Poisson rule produced 214 signals; 15 of 38 recall events had one beforehand (39% vs 14% for any window).
3. **An assistant that cites.** Claude Haiku 5.5 answers only through read-only database tools, with a cost ledger and a budget stop. In the live test, citations traced back to tool results 23/23.
4. **Memory per investigation.** Hypotheses, ruled-out causes and decisions survive across sessions; the user can view, export and really delete them.
5. **Honest evaluation.** 85 questions were fixed before any paid run. Haiku scored 78/80 (97.5%) for $0.10; Opus 5.5 scored 76/80 (95.0%) for $4.01. With McNemar p 0.625, the cheaper model stays.
6. **Safety and drift.** A guard checks each answer; drift checks watch 79,075 newer reports.
7. **A public demo.** A Streamlit app replays recorded answers, and a Power BI report reads exported files; neither needs an API key or database.

## The finding

The drift checks flagged 5 of 105 checks, led by Boston Scientific pacemaker battery reports from late 2025. Splitting those reports by device family shows that the share from the families in a 2025 recall rose from 77.9% to 97.5%. The timing and the families line up with the recall; the data cannot show that the recall caused the reports.

## What did not work

- **Phase 7 scored 4/5.** The first guard withheld 24 of 48 safe red-team answers, so its criterion was not met. The result stays published as it was.
- **Phase 7b fixed the guard on paper:** a quoting guard caught 38/40 planted unsafe sentences and withheld 0/40 clean answers. But the labels came from an AI (Claude Opus 5.5) with no human check, so this is weaker evidence than it looks.

## Limitations

- Report counts are not failure rates (no denominator of devices in use).
- FDA data are unvalidated and reports do not prove a device caused an event.
- The latest quarter is incomplete because reports keep arriving.
- The failure-mode codebook agrees with hand labels about 70% of the time (61% to 79% on the test set), and those labels were made by Claude, not a domain expert.
- Phase 7 red-team criterion not met (guard withheld safe answers): 24 of 48 safe answers were withheld, so Phase 7 scored 4/5.
- Phase 7b labels came from an AI, with no human check (Claude Opus 5.5 labelled them; the user declined to label).
- The 7b guard was not re-tested on the 2025-2026 data, and the 78/80 accuracy was measured on 2022-2024 data only.
- The live app and the Power BI report are snapshots, not live data: they replay recorded answers and exported files.

## What I would do next

Have a quality engineer label a sample to replace the AI labels, re-test the guard on the 2025-2026 data, and add a denominator (devices sold) so trends become rates.
