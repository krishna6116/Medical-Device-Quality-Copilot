# Medical Device Quality Copilot

> Work in progress (Phases 0-7c run; Phase 7 has one criterion not met; Phases 8 and 9 to go). An AI assistant that helps a medical device quality engineer investigate field failures using public FDA data, and remembers each open investigation across sessions.

## The problem

When a device starts failing in the field, a quality engineer has to answer questions fast: Are complaints about this product rising? Which failure modes? Did a competitor's similar device get recalled, and why? What did we already rule out last week? The public evidence (FDA MAUDE adverse-event reports and recall records) is large, messy free text, and investigations run for weeks across many sessions.

## What it will do

- Answer investigation questions from openFDA device adverse-event reports and recalls, citing the exact report numbers.
- Group reports into failure modes (non-LLM baselines first), show trends and statistical signals, and link them to recalls.
- Remember each open investigation (product, hypotheses, what was ruled out and why, decisions), with a page to view and delete that memory.
- Run on Claude Haiku 5.5 (a few dollars for the whole project) and be evaluated honestly against a pre-registered question set, compared with one run of a stronger Claude model; the live demo replays recorded answers at no cost.

## Status

| Phase | State |
|---|---|
| 0 Setup | done |
| 1 Data + EDA | done: 154,194 reports + 1,626 recalls for 5 device types; [findings](docs/EDA_FINDINGS.md), [data card](docs/DATA_CARD.md), verifier 9/9 (8 without the live openFDA comparison) |
| 2 Pipeline (PostgreSQL) | done: star schema, 1 record quarantined, 305 maker names -> 101 companies, report-recall links; [pipeline](docs/PIPELINE.md), verifier 10/10 |
| 3 Failure modes | done: FDA terms mapped by a codebook beat text methods (70% on test); 214 early-warning signals, 15/38 recalls preceded by one; [failure modes](docs/FAILURE_MODES.md), scorecard 5/5 |
| 4 Assistant | done: 8 read-only database tools, Claude Haiku 5.5 agent loop with cost ledger, budget stop and free replay; proven with a scripted stand-in (scorecard v2 5/5); live Haiku answers recorded in Phase 6 meet the original criteria (scorecard 5/5); [assistant](docs/ASSISTANT.md) |
| 5 Memory | done: remembers each investigation across sessions (ruled out, hypotheses, decisions, questions); view, edit, export and real delete; refuses invented evidence and personal data; [memory](docs/MEMORY.md), scorecard 5/5 |
| 6 Evaluation (paid run) | done: 85 pre-registered questions; Haiku 5.5 78/80 for $0.10 vs Opus 5.5 76/80 for $4.01, no significant difference, so the cheap model stays; every answer recorded and re-graded by separate code (same matching rules); [evaluation](docs/EVALUATION.md), scorecard 5/5 |
| 7 Safety, cost, drift | run, scorecard 4/5: all 48 raw red-team answers labelled safe (by Claude, not independent), but the Haiku guard withheld 24 of them, so the red-team criterion is **not met**; drift checks on 79,075 new reports flag a pacemaker battery surge; [safety and drift](docs/SAFETY_AND_DRIFT.md) |
| 7b New guard | a quoting guard, tested on full-length answers: 38/40 planted unsafe sentences caught, 0/40 clean answers withheld; all four bars met, but **labelled by Claude Opus, no human check**; Phase 7 stays 4/5; [guard](docs/GUARD_7B.md) |
| 7c Reports 2025-2026 | 233,264 reports (2022-2026) in a second schema, rebuilt from raw with 0 differences, old data untouched (9/9 checks); Haiku 20/20 on questions over the larger data; the guard was not re-tested on it; [data](docs/DATA_2025_2026.md) |
| 8 Streamlit + Power BI | app live at [medical-device-copilot.streamlit.app](https://medical-device-copilot.streamlit.app) (recorded answers, no API or database; every number checked, 21 app tests, live check); Power BI next; [app](docs/APP.md) |
| 9 | planned: see [docs/PLAN.md](docs/PLAN.md) |

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m mdqc.setup_env       # optional: free openFDA key, hidden prompt, saved to .env
.venv\Scripts\python -m mdqc.download        # ~1 GB transfer, 68 MB stored, no key needed
.venv\Scripts\python -m mdqc.eda
.venv\Scripts\python -m mdqc.verify_phase1
.venv\Scripts\python -m mdqc.db_setup        # once: PostgreSQL database + login (password into .env)
.venv\Scripts\python -m mdqc.load
.venv\Scripts\python -m mdqc.verify_phase2
.venv\Scripts\python -m pip install -r requirements-embed.txt   # Phase 3 embedding model (CPU PyTorch first: see the file)
.venv\Scripts\python -m mdqc.embed            # ~2.4 h on a laptop CPU, once
.venv\Scripts\python -m mdqc.run_phase3
.venv\Scripts\python -m mdqc.verify_phase3
.venv\Scripts\python -m mdqc.run_phase4 --scripted   # free pipeline proof (no model)
.venv\Scripts\python -m mdqc.verify_phase4
.venv\Scripts\python -m mdqc.replay Q1             # replay a recorded investigation for free
.venv\Scripts\python -m mdqc.run_phase5
.venv\Scripts\python -m mdqc.verify_phase5
.venv\Scripts\python -m mdqc.memory list           # investigation memory: list | show | export | delete-item | delete
.venv\Scripts\python -m mdqc.run_phase6           # Phase 6 cost estimate (free); --control free stand-ins; --live is paid
.venv\Scripts\python -m mdqc.verify_phase6
.venv\Scripts\python -m mdqc.drift --baseline      # Phase 7 drift: --download fetches 2025-2026 reports, --check runs the 105 checks
.venv\Scripts\python -m mdqc.verify_phase7
.venv\Scripts\python -m mdqc.verify_phase7b
.venv\Scripts\python -m mdqc.load_all --raw --load --analytics --embed   # Phase 7c: 2022-2026 data beside core (about an hour)
.venv\Scripts\python -m mdqc.verify_phase7c        # about 45 minutes
```

## Data and limits

Data: [openFDA](https://open.fda.gov/) device endpoints (public domain). FDA's disclaimer applies: the data are unvalidated and must not be used for medical decisions. Adverse-event reports are signals, not proof that a device caused an event, and counts are not failure rates.
