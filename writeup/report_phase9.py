"""Phase 9: render the write-up from writeup/facts.py (never hand-typed numbers).

Run:  python -m writeup.report_phase9            write README.md and the docs below
      python -m writeup.report_phase9 --check    fail if any file differs from a fresh render (CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

from writeup.facts import values

ROOT = Path(__file__).resolve().parents[1]
APP = "https://medical-device-copilot.streamlit.app"
REPO = "https://github.com/krishna6116/Medical-Device-Quality-Copilot"
LINKEDIN = "https://www.linkedin.com/in/krishnakumar-balasundaram-3a92b6422"
COUNTS_NOTE = "Report counts are not failure rates: there is no count of devices in use, and a report does not prove the device caused the event."
TECH = "Python · PostgreSQL · openFDA API · pandas · scikit-learn · BM25 + bge-small embeddings · Claude Haiku 5.5 (Anthropic SDK, own agent loop) · Streamlit · Power BI · GitHub Actions"

CHECK_BLOCK = """pip install -r requirements.txt
pytest
python -m mdqc.verify_phase3 --offline
python -m mdqc.verify_phase6 --offline
python -m mdqc.verify_phase7 --offline
python -m mdqc.verify_phase7b
python -m dashboards.verify_phase8
python -m writeup.report_phase9 --check
python -m writeup.verify_phase9"""

FULL_BLOCK = r""".venv\Scripts\python -m mdqc.setup_env       # optional: free openFDA key, hidden prompt, saved to .env
.venv\Scripts\python -m mdqc.download        # about 1 GB transfer, 68 MB stored, no key needed
.venv\Scripts\python -m mdqc.verify_phase1
.venv\Scripts\python -m mdqc.db_setup        # once: PostgreSQL database + login (password into .env)
.venv\Scripts\python -m mdqc.load
.venv\Scripts\python -m mdqc.verify_phase2
.venv\Scripts\python -m pip install -r requirements-embed.txt   # Phase 3 embedding model (CPU PyTorch first: see the file)
.venv\Scripts\python -m mdqc.embed            # about 2.4 h on a laptop CPU, once
.venv\Scripts\python -m mdqc.run_phase3
.venv\Scripts\python -m mdqc.verify_phase3
.venv\Scripts\python -m mdqc.run_phase4 --scripted   # free pipeline proof (no model)
.venv\Scripts\python -m mdqc.replay Q1             # replay a recorded investigation for free
.venv\Scripts\python -m mdqc.run_phase5
.venv\Scripts\python -m mdqc.memory list           # investigation memory: list | show | export | delete-item | delete
.venv\Scripts\python -m mdqc.run_phase6           # Phase 6 cost estimate (free); --live is the paid run
.venv\Scripts\python -m mdqc.verify_phase6
.venv\Scripts\python -m mdqc.drift --baseline      # Phase 7 drift: --download fetches new reports, --check runs the checks
.venv\Scripts\python -m mdqc.verify_phase7
.venv\Scripts\python -m mdqc.load_all --raw --load --analytics --embed   # Phase 7c: 2022-2026 data beside core
.venv\Scripts\python -m mdqc.verify_phase7c        # about 45 minutes
.venv\Scripts\python -m dashboards.export_snapshots   # app snapshots (the app has its own env from app/requirements.txt)
.venv\Scripts\python -m dashboards.verify_phase8 --local
.venv\Scripts\python -m dashboards.powerbi_export     # CSV files for the Power BI report (no database login)
.venv\Scripts\python -m dashboards.verify_powerbi"""


def limitations(F) -> str:
    return f"""## Limitations

- Report counts are not failure rates (no denominator of devices in use).
- FDA data are unvalidated and reports do not prove a device caused an event.
- The latest quarter is incomplete because reports keep arriving.
- The failure-mode codebook agrees with hand labels about {F['codebook_test']} of the time ({F['codebook_ci']} on the test set), and those labels were made by Claude, not a domain expert.
- Phase 7 red-team criterion not met (guard withheld safe answers): {F['redteam_withheld']} of {F['redteam_n']} safe answers were withheld, so Phase 7 scored {F['phase7_score']}.
- Phase 7b labels came from an AI, with no human check (Claude Opus 5.5 labelled them; the user declined to label).
- The 7b guard was not re-tested on the 2025-2026 data, and the {F['haiku_correct']}/{F['eval_graded']} accuracy was measured on 2022-2024 data only.
- The live app and the Power BI report are snapshots, not live data: they replay recorded answers and exported files.
"""


def phase_rows(F) -> list[tuple[str, str]]:
    return [
        ("0 Setup", "Done: repository, CI on every push, pre-registration convention"),
        ("1 Data", f"Done: {F['reports_core']} adverse-event reports (2022-2024) and {F['recalls']} recalls for 5 device types, equal to openFDA's own counts; [findings](docs/EDA_FINDINGS.md)"),
        ("2 Pipeline", f"Done: PostgreSQL star schema, personal fields never stored, {F['maker_names']} maker names merged into {F['companies']} companies; [pipeline](docs/PIPELINE.md)"),
        ("3 Failure modes", f"Done: FDA problem terms mapped by a codebook ({F['codebook_test']} on test) beat text methods (embeddings {F['embedding_test']}); {F['signals']} early-warning signals, {F['recall_hits']} of {F['recall_events']} recall events preceded by one ({F['hit_rate']} vs a {F['base_rate']} base rate); [failure modes](docs/FAILURE_MODES.md)"),
        ("4 Assistant", f"Done: Claude Haiku 5.5 with read-only database tools, its own agent loop, cost ledger and budget stop; citations traceable {F['citations']}; [assistant](docs/ASSISTANT.md)"),
        ("5 Memory", "Done: remembers each investigation across sessions (hypotheses, ruled out, decisions), with view, edit, export and real delete; [memory](docs/MEMORY.md)"),
        ("6 Evaluation", f"Done: {F['eval_questions']} pre-registered questions; Haiku {F['haiku_correct']}/{F['eval_graded']} for {F['haiku_usd']} vs Opus 5.5 {F['opus_correct']}/{F['eval_graded']} for {F['opus_usd']} (McNemar p {F['mcnemar_p']}): the cheap model stays; [evaluation](docs/EVALUATION.md)"),
        ("7 Safety and drift", f"Done, scorecard {F['phase7_score']}: the guard withheld {F['redteam_withheld']} of {F['redteam_n']} safe red-team answers, so that criterion is **not met**; drift checks on {F['new_reports']} new reports raised {F['drift_flags']} flags in {F['drift_checks']} checks, led by a pacemaker battery surge; [safety and drift](docs/SAFETY_AND_DRIFT.md)"),
        ("7b New guard", f"Done: a quoting guard caught {F['guard_caught']} planted unsafe sentences and withheld {F['guard_clean_withheld']} clean answers, but the labels came from an AI with no human check; [guard](docs/GUARD_7B.md)"),
        ("7c 2025-2026 data", f"Done: {F['reports_all']} reports (2022-2026) rebuilt from raw in a second schema, checks {F['phase7c_checks']}; Haiku {F['haiku_7c']} on questions over the larger data; [data](docs/DATA_2025_2026.md)"),
        ("8 App and Power BI", f"Done: [live app]({APP}) replaying recorded answers, and a Power BI report on exported files, {F['powerbi_values']} exported values checked (scorecard {F['powerbi_score']}); [app](docs/APP.md), [Power BI](docs/POWERBI_GUIDE.md)"),
        ("9 Write-up", "Done: this README, [case study](docs/CASE_STUDY.md), [results](docs/RESULTS.md), [architecture](docs/ARCHITECTURE.md), [decisions](docs/DECISIONS.md), all generated from the results files and checked"),
    ]


def readme(F) -> str:
    rows = "\n".join(f"| {a} | {b} |" for a, b in phase_rows(F))
    return f"""# Medical Device Quality Copilot

An AI assistant that helps a medical device quality engineer investigate field failures from public FDA data, citing the exact reports.

**Live app:** [{APP.removeprefix('https://')}]({APP}) · [Case study](docs/CASE_STUDY.md) · [Results](docs/RESULTS.md) · [Docs](docs/README.md)

![Home page of the live app](docs/figures/v11/after_home_desktop.png)

**Headline results**

- **Cheap model, no significant loss:** on {F['eval_graded']} pre-registered questions, Claude Haiku 5.5 answered {F['haiku_correct']} correctly for {F['haiku_usd']}; Claude Opus 5.5 answered {F['opus_correct']} for {F['opus_usd']}. The difference is not significant (McNemar p {F['mcnemar_p']}), so the cheap model stays.
- **Early warning:** {F['recall_hits']} of {F['recall_events']} recall events were preceded by an early-warning signal ({F['hit_rate']}), against a {F['base_rate']} base rate for any window.
- **A real case:** in Boston Scientific pacemaker battery reports, the share from the recalled device families rose from {F['battery_before']} to {F['battery_after']} after the 2025 recall began. The data show timing, not cause.

{COUNTS_NOTE}

**Built with:** {TECH}. Total recorded API spend for the whole project: {F['total_usd']}.

## The problem

When a device starts failing in the field, a quality engineer has to answer questions fast: are complaints about this product rising, which failure modes, did a similar device get recalled and why, and what did we already rule out last week? The public evidence (FDA MAUDE adverse-event reports and recall records) is large, messy free text, and investigations run for weeks across many sessions.

## What it does

- Answers investigation questions from openFDA adverse-event reports and recalls, citing the exact report numbers.
- Groups reports into failure modes, shows trends and statistical early-warning signals, and links them to recalls.
- Remembers each open investigation (hypotheses, what was ruled out and why, decisions), with a page to view, export and delete that memory.
- Watches new reports for drift and checks every answer with a safety guard before it is shown.

## Status

| Phase | State |
|---|---|
{rows}

Every phase pre-registered its criteria in a commit before its results, and ends with an independent verifier that runs in CI.

## How it works

openFDA downloads go through a validated pipeline into PostgreSQL. A codebook maps FDA problem terms to failure modes, and a Poisson rule flags unusual months. The assistant (Claude Haiku 5.5) answers only through read-only database tools and investigation memory, and a guard checks the answer. The app and the Power BI report read exported snapshots, so the public demo needs no API key or database. Details: [architecture](docs/ARCHITECTURE.md), [decisions](docs/DECISIONS.md).

## Check it without the data

CI runs this block verbatim on Python 3.14 (ubuntu-24.04): the tests and the offline verifiers re-check the published results from the committed files.

```bash
{CHECK_BLOCK}
```

## Run the full pipeline

Needs PostgreSQL 17 and a few hours (mostly the embeddings). The paid steps ask for a cost estimate and a yes first.

```powershell
python -m venv .venv
.venv\\Scripts\\python -m pip install -r requirements.txt
{FULL_BLOCK}
```

{limitations(F)}
## Data and licence

Data: [openFDA](https://open.fda.gov/) device endpoints (public domain). FDA's disclaimer applies: the data are unvalidated and must not be used for medical decisions. Personal and contact fields are dropped on load.

## Author

**Krishnakumar Balasundaram**, MS Business Analytics candidate at the Isenberg School of Management, UMass Amherst (expected May 2028). B.E. Mechanical Engineering, with industry experience in production, quality control and operations analytics in manufacturing.

[LinkedIn]({LINKEDIN}) · [GitHub](https://github.com/Krishna6116) · [Live app]({APP}) · [Case study](docs/CASE_STUDY.md)

Built with Claude Code as a coding assistant; every criterion, choice and published claim was reviewed by the author, and the verifiers re-check the numbers.
"""


def case_study(F) -> str:
    return f"""# Case study: an AI copilot for medical device quality investigations

{COUNTS_NOTE}

## The situation

A quality engineer at a device maker is told that complaints about a product are rising. They need to know whether that is real, which failure modes drive it, whether competitors' similar devices were recalled, and what the team already ruled out. The public record is the FDA's MAUDE database: {F['reports_core']} adverse-event reports for the 5 device types studied here (hip and knee implants, a pacemaker, an insulin pump) from 2022 to 2024, later {F['reports_all']} reports through 2026, plus {F['recalls']} recalls.

## What was built

1. **A trustworthy data layer.** The download equals openFDA's own counts; the PostgreSQL pipeline drops personal fields, quarantines broken records and merges {F['maker_names']} maker names into {F['companies']} companies.
2. **Failure modes and early warning.** A codebook over FDA problem terms classifies reports ({F['codebook_test']} on a held-out test, {F['codebook_ci']}); text embeddings did worse ({F['embedding_test']}). A Poisson rule produced {F['signals']} signals; {F['recall_hits']} of {F['recall_events']} recall events had one beforehand ({F['hit_rate']} vs {F['base_rate']} for any window).
3. **An assistant that cites.** Claude Haiku 5.5 answers only through read-only database tools, with a cost ledger and a budget stop. In the live test, citations traced back to tool results {F['citations']}.
4. **Memory per investigation.** Hypotheses, ruled-out causes and decisions survive across sessions; the user can view, export and really delete them.
5. **Honest evaluation.** {F['eval_questions']} questions were fixed before any paid run. Haiku scored {F['haiku_correct']}/{F['eval_graded']} ({F['haiku_acc']}) for {F['haiku_usd']}; Opus 5.5 scored {F['opus_correct']}/{F['eval_graded']} ({F['opus_acc']}) for {F['opus_usd']}. With McNemar p {F['mcnemar_p']}, the cheaper model stays.
6. **Safety and drift.** A guard checks each answer; drift checks watch {F['new_reports']} newer reports.
7. **A public demo.** A Streamlit app replays recorded answers, and a Power BI report reads exported files; neither needs an API key or database.

## The finding

The drift checks flagged {F['drift_flags']} of {F['drift_checks']} checks, led by Boston Scientific pacemaker battery reports from late 2025. Splitting those reports by device family shows that the share from the families in a 2025 recall rose from {F['battery_before']} to {F['battery_after']}. The timing and the families line up with the recall; the data cannot show that the recall caused the reports.

## What did not work

- **Phase 7 scored {F['phase7_score']}.** The first guard withheld {F['redteam_withheld']} of {F['redteam_n']} safe red-team answers, so its criterion was not met. The result stays published as it was.
- **Phase 7b fixed the guard on paper:** a quoting guard caught {F['guard_caught']} planted unsafe sentences and withheld {F['guard_clean_withheld']} clean answers. But the labels came from an AI (Claude Opus 5.5) with no human check, so this is weaker evidence than it looks.

{limitations(F)}
## What I would do next

Have a quality engineer label a sample to replace the AI labels, re-test the guard on the 2025-2026 data, and add a denominator (devices sold) so trends become rates.
"""


def results(F) -> str:
    rows = "\n".join(f"| {a} | {b} |" for a, b in phase_rows(F)).replace("](docs/", "](")
    return f"""# Results

All numbers below are rendered from the committed results files by `python -m writeup.report_phase9`; `python -m writeup.verify_phase9` recomputes them separately.

{COUNTS_NOTE}

| Phase | Result |
|---|---|
{rows}

## Assistant evaluation

| Model | Correct | Accuracy | Cost |
|---|---|---|---|
| Claude Haiku 5.5 | {F['haiku_correct']}/{F['eval_graded']} | {F['haiku_acc']} | {F['haiku_usd']} |
| Claude Opus 5.5 | {F['opus_correct']}/{F['eval_graded']} | {F['opus_acc']} | {F['opus_usd']} |

McNemar p {F['mcnemar_p']}: no significant difference; the pre-registered rule keeps the cheaper model.

## Early warning

{F['signals']} signals in 2023-2024; {F['recall_hits']} of {F['recall_events']} recall events had a signal beforehand ({F['hit_rate']}), against a {F['base_rate']} base rate.

## Total spend

Recorded API spend across all paid runs: {F['total_usd']}.
"""


def architecture(F) -> str:
    return f"""# Architecture

```mermaid
flowchart LR
  A[openFDA API] -->|download, checksums| B[data/raw]
  B -->|validate, quarantine, drop personal fields| C[(PostgreSQL core / core_all)]
  C --> D[analytics: failure modes, signals]
  C --> E[tools: 8 read-only lookups]
  D --> E
  E --> F[Claude Haiku 5.5 agent loop]
  M[(memory schema)] <--> F
  F --> G[guard] --> H[answer with citations]
  C --> S[snapshots and CSV exports]
  H -->|recorded| S
  S --> APP[Streamlit app]
  S --> PBI[Power BI report]
```

| Layer | Code | Notes |
|---|---|---|
| Download | `mdqc/openfda.py`, `mdqc/download.py` | paging, retries, checksums in `data/checksums.sha256` |
| Pipeline | `mdqc/schema.sql`, `mdqc/load.py`, `mdqc/load_all.py` | star schema; `core` (2022-2024) and `core_all` (2022-2026) side by side |
| Failure modes and signals | `mdqc/run_phase3.py`, `config/failure_modes.json` | codebook over FDA problem terms; Poisson rule per product, company and mode |
| Assistant | `mdqc/tools.py`, `mdqc/assistant.py` | own agent loop, prompt caching, cost ledger, budget stop, replay |
| Memory | `mdqc/memory.py` | schema `memory`, audit trail without text, real delete |
| Safety and drift | `mdqc/guardrails.py`, `mdqc/guard2.py`, `mdqc/drift.py` | guard v2 frozen; drift without a database |
| App | `app/`, `dashboards/export_snapshots.py` | reads only `dashboards/snapshots/` |
| Power BI | `dashboards/powerbi_export.py`, `dashboards/build_pbip.py` | CSV files, no database login |
| Write-up | `writeup/` | facts, renderer, verifier |

Total recorded API spend: {F['total_usd']}.
"""


def decisions(F) -> str:
    return f"""# Decisions

| Decision | Why | Evidence |
|---|---|---|
| Claude Haiku 5.5, not Opus 5.5 | Opus was not significantly better and cost far more | {F['haiku_correct']}/{F['eval_graded']} for {F['haiku_usd']} vs {F['opus_correct']}/{F['eval_graded']} for {F['opus_usd']}, McNemar p {F['mcnemar_p']} ([evaluation](EVALUATION.md)) |
| Codebook over FDA terms, not embeddings | Chosen on validation; simpler and better on test | {F['codebook_test']} vs {F['embedding_test']} ([failure modes](FAILURE_MODES.md)) |
| One paid run only (Phase 6) | Keep the whole project within a small budget | total recorded spend {F['total_usd']} |
| Do not ship the Phase 7 guard | It withheld safe answers | {F['redteam_withheld']} of {F['redteam_n']} withheld ([safety](SAFETY_AND_DRIFT.md)) |
| Keep Phase 7 at {F['phase7_score']} after 7b | Results are never rewritten after the fact | [guard 7b](GUARD_7B.md) |
| New data in a second schema | The published 2022-2024 results must stay reproducible | `core` unchanged; `core_all` checks {F['phase7c_checks']} ([data](DATA_2025_2026.md)) |
| App replays recorded answers | A public demo must not spend API credit or expose a database | [app](APP.md) |
| Power BI reads exported CSV files | No database password to type; the report is a snapshot | {F['powerbi_values']} exported values checked ([guide](POWERBI_GUIDE.md)) |
"""


DOC_DESCRIPTIONS = {
    "APP.md": "The Streamlit app: pages, snapshots and checks",
    "ARCHITECTURE.md": "How the parts fit together, with a diagram",
    "ASSISTANT.md": "The tool-using assistant, its tools and live checks",
    "CASE_STUDY.md": "The whole project as a short story with results",
    "DATA_2025_2026.md": "Adding 2025-2026 reports in a second schema",
    "DATA_CARD.md": "What the openFDA data contain and their limits",
    "DECISIONS.md": "The main choices, why they were made, and evidence",
    "EDA_FINDINGS.md": "First look at the reports and recalls data",
    "EVALUATION.md": "Pre-registered evaluation of Haiku against Opus 5.5",
    "FAILURE_MODES.md": "Failure-mode methods compared, search and early-warning signals",
    "GUARD_7B.md": "The second safety guard and how it was tested",
    "LEARNING_LOG.md": "Dated diary of every working session and lesson",
    "MEMORY.md": "Investigation memory: design, guardrails and real deletion",
    "OPENFDA_ACCESS.md": "How the openFDA API was checked before downloading",
    "PHASE3_SPOT_CHECK.md": "Second-pass spot check of the reference labels",
    "PHASE9_CHECKLIST.md": "Manual release steps for Phase 9 and their evidence",
    "PIPELINE.md": "The PostgreSQL pipeline, validation rules and quarantine",
    "PLAN.md": "The original ten-phase plan and project conventions",
    "POWERBI_GUIDE.md": "How the Power BI report was built and checked",
    "RELEASE_NOTES.md": "What version 1.0.0 contains, generated from results",
    "RESULTS.md": "Every phase's result in one table with sources",
    "SAFETY_AND_DRIFT.md": "Safety guard, red-team test, cost ledger and drift",
    "openfda_access_check.json": "Recorded result of the openFDA access check run",
}
NOTEBOOK_DESCRIPTIONS = {
    "01_eda.ipynb": "Phase 1 exploration of reports and recalls, executed",
    "02_pipeline.ipynb": "Phase 2 pipeline walkthrough with load checks, executed",
    "03_failure_modes.ipynb": "Phase 3 failure modes, search and signals, executed",
    "04_assistant.ipynb": "Phase 4 assistant tools and a replayed investigation",
    "05_memory.ipynb": "Phase 5 investigation memory across sessions, replayed",
    "06_evaluation.ipynb": "Phase 6 evaluation results and the model choice",
    "07_safety_drift.ipynb": "Phase 7 guard, red-team results and drift checks",
    "07bc_guard_and_data.ipynb": "Phases 7b and 7c: new guard and newer data",
}


def docs_index(F) -> str:
    lines = ["# Documentation index", "", "Start with the [README](../README.md) and the [case study](CASE_STUDY.md).", "", "## Documents", ""]
    lines += [f"- [{n}]({n}): {d}" for n, d in sorted(DOC_DESCRIPTIONS.items())]
    lines += ["", "## Notebooks", ""]
    lines += [f"- [{n}](../notebooks/{n}): {d}" for n, d in sorted(NOTEBOOK_DESCRIPTIONS.items())]
    lines += ["", "## Status", "", "All phases 0-9 are done; see [results](RESULTS.md).", ""]
    return "\n".join(lines)


def release_notes(F) -> str:
    return f"""# Medical Device Quality Copilot v1.0.0

An AI assistant that helps a medical device quality engineer investigate field failures from public FDA data, citing the exact reports. Live app: {APP}

## Highlights

- Claude Haiku 5.5 answered {F['haiku_correct']}/{F['eval_graded']} pre-registered questions for {F['haiku_usd']}; Opus 5.5 answered {F['opus_correct']}/{F['eval_graded']} for {F['opus_usd']} (not significantly different).
- {F['recall_hits']} of {F['recall_events']} recall events were preceded by an early-warning signal ({F['hit_rate']} vs a {F['base_rate']} base rate).
- Pacemaker battery reports: the recalled families' share rose from {F['battery_before']} to {F['battery_after']} after the 2025 recall (timing, not cause).
- {F['reports_all']} openFDA reports (2022-2026) and {F['recalls']} recalls in PostgreSQL; Streamlit app and Power BI report on snapshots.

## Known limits

Phase 7 scored {F['phase7_score']} (the first guard withheld {F['redteam_withheld']} of {F['redteam_n']} safe answers); Phase 7b labels came from an AI with no human check. {COUNTS_NOTE}

Total recorded API spend: {F['total_usd']}. Details: [results]({REPO}/blob/main/docs/RESULTS.md), [case study]({REPO}/blob/main/docs/CASE_STUDY.md).
"""


def render() -> dict:
    F = values()
    return {"README.md": readme(F), "docs/CASE_STUDY.md": case_study(F), "docs/RESULTS.md": results(F), "docs/ARCHITECTURE.md": architecture(F),
            "docs/DECISIONS.md": decisions(F), "docs/README.md": docs_index(F), "docs/RELEASE_NOTES.md": release_notes(F)}


def main(check: bool) -> int:
    bad = []
    for rel, text in render().items():
        p = ROOT / rel
        if check:
            if not p.exists() or p.read_bytes() != text.encode("utf-8"):
                bad.append(rel)
        else:
            p.write_bytes(text.encode("utf-8"))
    if check:
        print("stale:", bad) if bad else print("all generated docs are current")
        return 1 if bad else 0
    print("wrote", ", ".join(render()))
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
