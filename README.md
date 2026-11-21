# Medical Device Quality Copilot

> Work in progress (Phase 1 of 9). An AI assistant that helps a medical device quality engineer investigate field failures using public FDA data, and remembers each open investigation across sessions.

## The problem

When a device starts failing in the field, a quality engineer has to answer questions fast: Are complaints about this product rising? Which failure modes? Did a competitor's similar device get recalled, and why? What did we already rule out last week? The public evidence (FDA MAUDE adverse-event reports and recall records) is large, messy free text, and investigations run for weeks across many sessions.

## What it will do

- Answer investigation questions from openFDA device adverse-event reports and recalls, citing the exact report numbers.
- Group reports into failure modes (non-LLM baselines first), show trends and statistical signals, and link them to recalls.
- Remember each open investigation (product, hypotheses, what was ruled out and why, decisions), with a page to view and delete that memory.
- Be evaluated honestly against a pre-registered question set: a free local model vs one capped run of Claude.

## Status

| Phase | State |
|---|---|
| 0 Setup | done |
| 1 Data + EDA | in progress: [openFDA access check](docs/OPENFDA_ACCESS.md) |
| 2-9 | planned: see [docs/PLAN.md](docs/PLAN.md) |

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m mdqc.check_openfda
```

## Data and limits

Data: [openFDA](https://open.fda.gov/) device endpoints (public domain). FDA's disclaimer applies: the data are unvalidated and must not be used for medical decisions. Adverse-event reports are signals, not proof that a device caused an event, and counts are not failure rates.
