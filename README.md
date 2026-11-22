# Medical Device Quality Copilot

> Work in progress (Phases 0-5 done; 4 to go). An AI assistant that helps a medical device quality engineer investigate field failures using public FDA data, and remembers each open investigation across sessions.

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
| 1 Data + EDA | done: 154,194 reports + 1,626 recalls for 5 device types; [findings](docs/EDA_FINDINGS.md), [data card](docs/DATA_CARD.md), verifier 8/8 |
| 2 Pipeline (PostgreSQL) | done: star schema, 1 record quarantined, 305 maker names -> 101 companies, report-recall links; [pipeline](docs/PIPELINE.md), verifier 10/10 |
| 3 Failure modes | done: FDA terms mapped by a codebook beat text methods (70% on test); 214 early-warning signals, 15/38 recalls preceded by one; [failure modes](docs/FAILURE_MODES.md), scorecard 5/5 |
| 4 Assistant | done: 8 read-only database tools, Claude Haiku 5.5 agent loop with cost ledger, budget stop and free replay; proven with a scripted stand-in, live answers in Phase 6; [assistant](docs/ASSISTANT.md), scorecard 5/5 |
| 5 Memory | done: remembers each investigation across sessions (ruled out, hypotheses, decisions, questions); view, edit, export and real delete; refuses invented evidence and personal data; [memory](docs/MEMORY.md), scorecard 5/5 |
| 6 Evaluation (paid run) | next |
| 7-9 | planned: see [docs/PLAN.md](docs/PLAN.md) |

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
```

## Data and limits

Data: [openFDA](https://open.fda.gov/) device endpoints (public domain). FDA's disclaimer applies: the data are unvalidated and must not be used for medical decisions. Adverse-event reports are signals, not proof that a device caused an event, and counts are not failure rates.
