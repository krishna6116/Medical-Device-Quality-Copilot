# Medical Device Quality Copilot

Portfolio project: an AI assistant that helps a medical device quality engineer investigate field failures from public FDA data (openFDA MAUDE adverse-event reports + device recalls), cites the exact reports, and remembers each open investigation across sessions (product, hypotheses, ruled out, decisions) with a page to view and delete that memory. Full version (10 phases, 0-9, ~5-6 weeks), chosen 2026-11-21; reuses the predictive maintenance project's patterns. Detailed plan: `docs/PLAN.md`.

## Status (2026-11-21)

- Phase 0 (setup): done, committed locally. `.venv` on Python 3.14; `requirements.txt`; `pytest` (8 tests); CI skeleton `.github/workflows/ci.yml` (ubuntu-24.04, Python 3.14, unit tests only, no network).
- Phase 1 (data + EDA): started. Client `mdqc/openfda.py` (no-key limit 999, skip <= 25000, search_after paging, truncates `code_info`). Access check `python -m mdqc.check_openfda` -> `docs/openfda_access_check.json` (11/11), write-up `docs/OPENFDA_ACCESS.md`. Next: pre-register scope (product codes + date window, expected counts and download size shown to the user first), optional free openFDA key in `.env`, then download + EDA.
- GitHub: no remote yet. Creating the public repository and pushing are the user's call; ask first. User's GitHub: Krishna6116; CLI at `C:\Program Files\GitHub CLI\gh.exe`.

## Phases

0 setup · 1 data + EDA (pre-registered scope, size shown before download) · 2 pipeline into PostgreSQL star schema with validation/quarantine (drop personal fields, report-recall links) · 3 failure-mode grouping with non-LLM baselines (problem codes, TF-IDF, local embeddings; retrieval choice; signal rule backtested vs recalls) · 4 tool-using assistant (local model via Ollama; Claude backend written, not called) · 5 investigation memory (PostgreSQL schema `memory`; view/edit/delete/export; deletion is real) · 6 pre-registered evaluation set + grading (local run, then the one capped Claude Opus 5.5 run, recorded) · 7 safety guardrails + cost ledger + drift monitoring on new FDA reports · 8 Streamlit app replaying recorded answers + memory page, Power BI report (read-only login) · 9 README / case study / release.

Every phase: success criteria pre-registered in a commit before its results; independent verification script in CI.

## Cost plan

- Building: $0 (openFDA is free; BM25, a small CPU embedding model, optional Ollama 7-8B 4-bit model; laptop 16 GB RAM, Intel Core Ultra 5, no GPU).
- Phase 6 only: one run of `claude-opus-5-5` via the official `anthropic` SDK (cheaper model only if the user chooses), budget about $2-10, user sets a Console spending cap first, estimate printed and `--confirm-spend` required. Every paid answer is saved and never re-bought.
- Demo + CI: replay recorded answers; no API keys in the cloud.

## Conventions

- Every phase ends with an independent verification script (recompute claims a different way) that runs in CI before the phase is called done.
- Pre-register criteria in a commit before the run they judge; label later changes post hoc.
- Choices on validation only, split by product code (never by report); test confirms; Holm for multiple comparisons; bootstrap intervals.
- Generate metric/result docs from results files; never hand-type numbers.
- Honest reporting: MAUDE counts are signals, not failure rates; reports do not prove causation; say what failed.
- Never commit `.env`, data files, databases, model weights, personal files or personal data (email, phone). Drop the dataset's manufacturer contact fields at ingest.
- No paid API call outside the Phase 6 evaluation run.
- Batch changes: check thoroughly once, then one commit/PR, not many small fix-ups.
- Tests in `tests/` (pytest, `pythonpath = .`), no network in unit tests.
- Keep a dated entry in `docs/LEARNING_LOG.md` for each working session.
- The user is learning: explain the concept and the reason for each step, then do it.
- End every phase (notebook and summary to the user) with a "Why we did these tasks" table: task | why we did it | what we learned | what it changes next.
- Line endings: `.gitattributes` stores LF.
