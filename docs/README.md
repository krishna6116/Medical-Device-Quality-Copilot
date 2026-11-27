# Documentation index

Start with the [README](../README.md) and the [case study](CASE_STUDY.md).

## Documents

- [APP.md](APP.md): The Streamlit app: pages, snapshots and checks
- [ARCHITECTURE.md](ARCHITECTURE.md): How the parts fit together, with a diagram
- [ASSISTANT.md](ASSISTANT.md): The tool-using assistant, its tools and live checks
- [CASE_STUDY.md](CASE_STUDY.md): The whole project as a short story with results
- [DATA_2025_2026.md](DATA_2025_2026.md): Adding 2025-2026 reports in a second schema
- [DATA_ARCHIVE.md](DATA_ARCHIVE.md): Where the downloaded data snapshot is archived and how to restore it
- [DATA_CARD.md](DATA_CARD.md): What the openFDA data contain and their limits
- [DECISIONS.md](DECISIONS.md): The main choices, why they were made, and evidence
- [EDA_FINDINGS.md](EDA_FINDINGS.md): First look at the reports and recalls data
- [EVALUATION.md](EVALUATION.md): Pre-registered evaluation of Haiku against Opus 5.5
- [FAILURE_MODES.md](FAILURE_MODES.md): Failure-mode methods compared, search and early-warning signals
- [GUARD_7B.md](GUARD_7B.md): The second safety guard and how it was tested
- [LEARNING_LOG.md](LEARNING_LOG.md): Dated diary of every working session and lesson
- [MEMORY.md](MEMORY.md): Investigation memory: design, guardrails and real deletion
- [OPENFDA_ACCESS.md](OPENFDA_ACCESS.md): How the openFDA API was checked before downloading
- [PHASE3_SPOT_CHECK.md](PHASE3_SPOT_CHECK.md): Second-pass spot check of the reference labels
- [PHASE9_CHECKLIST.md](PHASE9_CHECKLIST.md): Manual release steps for Phase 9 and their evidence
- [PIPELINE.md](PIPELINE.md): The PostgreSQL pipeline, validation rules and quarantine
- [PLAN.md](PLAN.md): The original ten-phase plan and project conventions
- [POWERBI_GUIDE.md](POWERBI_GUIDE.md): How the Power BI report was built and checked
- [RELEASE_NOTES.md](RELEASE_NOTES.md): What version 1.0.0 contains, generated from results
- [RESULTS.md](RESULTS.md): Every phase's result in one table with sources
- [SAFETY_AND_DRIFT.md](SAFETY_AND_DRIFT.md): Safety guard, red-team test, cost ledger and drift
- [openfda_access_check.json](openfda_access_check.json): Recorded result of the openFDA access check run

## Notebooks

- [01_eda.ipynb](../notebooks/01_eda.ipynb): Phase 1 exploration of reports and recalls, executed
- [02_pipeline.ipynb](../notebooks/02_pipeline.ipynb): Phase 2 pipeline walkthrough with load checks, executed
- [03_failure_modes.ipynb](../notebooks/03_failure_modes.ipynb): Phase 3 failure modes, search and signals, executed
- [04_assistant.ipynb](../notebooks/04_assistant.ipynb): Phase 4 assistant tools and a replayed investigation
- [05_memory.ipynb](../notebooks/05_memory.ipynb): Phase 5 investigation memory across sessions, replayed
- [06_evaluation.ipynb](../notebooks/06_evaluation.ipynb): Phase 6 evaluation results and the model choice
- [07_safety_drift.ipynb](../notebooks/07_safety_drift.ipynb): Phase 7 guard, red-team results and drift checks
- [07bc_guard_and_data.ipynb](../notebooks/07bc_guard_and_data.ipynb): Phases 7b and 7c: new guard and newer data

## Status

All phases 0-9 are done; see [results](RESULTS.md).
