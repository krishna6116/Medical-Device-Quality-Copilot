# Decisions

| Decision | Why | Evidence |
|---|---|---|
| Claude Haiku 5.5, not Opus 5.5 | Opus was not significantly better and cost far more | 78/80 for $0.10 vs 76/80 for $4.01, McNemar p 0.625 ([evaluation](EVALUATION.md)) |
| Codebook over FDA terms, not embeddings | Chosen on validation; simpler and better on test | 70% vs 32% ([failure modes](FAILURE_MODES.md)) |
| One paid run only (Phase 6) | Keep the whole project within a small budget | total recorded spend $4.50 |
| Do not ship the Phase 7 guard | It withheld safe answers | 24 of 48 withheld ([safety](SAFETY_AND_DRIFT.md)) |
| Keep Phase 7 at 4/5 after 7b | Results are never rewritten after the fact | [guard 7b](GUARD_7B.md) |
| New data in a second schema | The published 2022-2024 results must stay reproducible | `core` unchanged; `core_all` checks 9/9 ([data](DATA_2025_2026.md)) |
| App replays recorded answers | A public demo must not spend API credit or expose a database | [app](APP.md) |
| Power BI reads exported CSV files | No database password to type; the report is a snapshot | 80 exported values checked ([guide](POWERBI_GUIDE.md)) |
