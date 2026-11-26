# Results

All numbers below are rendered from the committed results files by `python -m writeup.report_phase9`; `python -m writeup.verify_phase9` recomputes them separately.

Report counts are not failure rates: there is no count of devices in use, and a report does not prove the device caused the event.

| Phase | Result |
|---|---|
| 0 Setup | Done: repository, CI on every push, pre-registration convention |
| 1 Data | Done: 154,194 adverse-event reports (2022-2024) and 1,626 recalls for 5 device types, equal to openFDA's own counts; [findings](EDA_FINDINGS.md) |
| 2 Pipeline | Done: PostgreSQL star schema, personal fields never stored, 305 maker names merged into 101 companies; [pipeline](PIPELINE.md) |
| 3 Failure modes | Done: FDA problem terms mapped by a codebook (70% on test) beat text methods (embeddings 32%); 214 early-warning signals, 15 of 38 recall events preceded by one (39% vs a 14% base rate); [failure modes](FAILURE_MODES.md) |
| 4 Assistant | Done: Claude Haiku 5.5 with read-only database tools, its own agent loop, cost ledger and budget stop; citations traceable 23/23; [assistant](ASSISTANT.md) |
| 5 Memory | Done: remembers each investigation across sessions (hypotheses, ruled out, decisions), with view, edit, export and real delete; [memory](MEMORY.md) |
| 6 Evaluation | Done: 85 pre-registered questions; Haiku 78/80 for $0.10 vs Opus 5.5 76/80 for $4.01 (McNemar p 0.625): the cheap model stays; [evaluation](EVALUATION.md) |
| 7 Safety and drift | Done, scorecard 4/5: the guard withheld 24 of 48 safe red-team answers, so that criterion is **not met**; drift checks on 79,075 new reports raised 5 flags in 105 checks, led by a pacemaker battery surge; [safety and drift](SAFETY_AND_DRIFT.md) |
| 7b New guard | Done: a quoting guard caught 38/40 planted unsafe sentences and withheld 0/40 clean answers, but the labels came from an AI with no human check; [guard](GUARD_7B.md) |
| 7c 2025-2026 data | Done: 233,264 reports (2022-2026) rebuilt from raw in a second schema, checks 9/9; Haiku 20/20 on questions over the larger data; [data](DATA_2025_2026.md) |
| 8 App and Power BI | Done: [live app](https://medical-device-copilot.streamlit.app) replaying recorded answers, and a Power BI report on exported files, 80 exported values checked (scorecard 5/5); [app](APP.md), [Power BI](POWERBI_GUIDE.md) |
| 9 Write-up | Done: this README, [case study](CASE_STUDY.md), [results](RESULTS.md), [architecture](ARCHITECTURE.md), [decisions](DECISIONS.md), all generated from the results files and checked |

## Assistant evaluation

| Model | Correct | Accuracy | Cost |
|---|---|---|---|
| Claude Haiku 5.5 | 78/80 | 97.5% | $0.10 |
| Claude Opus 5.5 | 76/80 | 95.0% | $4.01 |

McNemar p 0.625: no significant difference; the pre-registered rule keeps the cheaper model.

## Early warning

214 signals in 2023-2024; 15 of 38 recall events had a signal beforehand (39%), against a 14% base rate.

## Total spend

Recorded API spend across all paid runs: $4.50.
