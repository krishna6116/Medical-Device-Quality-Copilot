# Architecture

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

Total recorded API spend: $4.50.
