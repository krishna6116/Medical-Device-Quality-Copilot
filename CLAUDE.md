# Medical Device Quality Copilot

Portfolio project: an AI assistant that helps a medical device quality engineer investigate field failures from public FDA data (openFDA MAUDE adverse-event reports + device recalls), cites the exact reports, and remembers each open investigation across sessions (product, hypotheses, ruled out, decisions) with a page to view and delete that memory. Full version (11 phases, ~5-6 weeks), chosen 2026-11-21. Detailed plan: `docs/PLAN.md`.

## Status (2026-11-21)

- Phase 0 (setup): done, committed locally. `.venv` on Python 3.14; `requirements.txt`; `pytest` (8 tests); CI skeleton `.github/workflows/ci.yml` (ubuntu-24.04, Python 3.14, unit tests only, no network).
- Phase 1 (data access + scope): started. Client `mdqc/openfda.py` (no-key limit 999, skip <= 25000, search_after paging, truncates `code_info`). Access check `python -m mdqc.check_openfda` -> `docs/openfda_access_check.json` (11/11), write-up `docs/OPENFDA_ACCESS.md`. Next: pre-register scope (product codes + date window, expected counts and download size shown to the user first), optional free openFDA key in `.env`.
- GitHub: no remote yet. Creating the public repository and pushing are the user's call; ask first. User's GitHub: Krishna6116; CLI at `C:\Program Files\GitHub CLI\gh.exe`.

## Phases

0 setup · 1 data access + scope · 2 pipeline (DuckDB, drop personal fields, report-recall links) · 3 EDA + signal detection (pre-registered rule, backtest vs recalls) · 4 retrieval (BM25 vs local embeddings vs hybrid, chosen on validation) · 5 tool-using assistant (local model via Ollama; Claude backend written, not called) · 6 investigation memory (SQLite; view/edit/delete/export; deletion is real) · 7 pre-registered evaluation set + local-model run · 8 one capped Claude Opus 5.5 evaluation run, recorded · 9 Streamlit app replaying recorded answers + memory page · 10 write-up + release.

## Cost plan

- Building: $0 (openFDA is free; BM25, a small CPU embedding model, optional Ollama 7-8B 4-bit model; laptop 16 GB RAM, Intel Core Ultra 5, no GPU).
- Phase 8 only: one run of `claude-opus-5-5` via the official `anthropic` SDK (cheaper model only if the user chooses), budget ~$0-10, user sets a Console spending cap first, estimate printed and `--confirm-spend` required. Every paid answer is saved and never re-bought.
- Demo + CI: replay recorded answers; no API keys in the cloud.

## Conventions

- Every phase ends with an independent verification script (recompute claims a different way) that runs in CI before the phase is called done.
- Pre-register criteria in a commit before the run they judge; label later changes post hoc.
- Choices on validation only, split by product code (never by report); test confirms; Holm for multiple comparisons; bootstrap intervals.
- Generate metric/result docs from results files; never hand-type numbers.
- Honest reporting: MAUDE counts are signals, not failure rates; reports do not prove causation; say what failed.
- Never commit `.env`, data files, databases, model weights, personal files or personal data (email, phone). Drop the dataset's manufacturer contact fields at ingest.
- No paid API call outside Phase 8.
- Batch changes: check thoroughly once, then one commit/PR, not many small fix-ups.
- Tests in `tests/` (pytest, `pythonpath = .`), no network in unit tests.
- Keep a dated entry in `docs/LEARNING_LOG.md` for each working session.
- The user is learning: explain the concept and the reason for each step, then do it.
- End every phase (notebook and summary to the user) with a "Why we did these tasks" table: task | why we did it | what we learned | what it changes next.
- Line endings: `.gitattributes` stores LF.
