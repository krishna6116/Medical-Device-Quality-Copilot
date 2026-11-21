# Project plan: Medical Device Quality Copilot (full version)

**Goal.** An AI assistant for a quality engineer at a medical device company (think Stryker or Medtronic) who is investigating field failures. It answers questions from public FDA data (openFDA MAUDE adverse-event reports and device recalls) with citations to the exact reports, spots trends, and **remembers each open investigation across sessions** (product, hypotheses, what was ruled out and why, decisions, open questions). A separate page shows everything it remembers and lets the user delete any of it.

**Scope chosen:** full version (decided 2026-11-21): 11 phases (0-10), about 5-6 weeks, an independent verification script per phase that runs in CI.

## Cost plan

| Stage | What runs | Cost |
|---|---|---|
| Building (Phases 0-7, 9-10) | openFDA API (free), keyword search (BM25), a small local embedding model on CPU, optionally a local open model through Ollama (7-8B, 4-bit, fits 16 GB RAM without a GPU) | $0 |
| Final evaluation (Phase 8) | **One** capped run of Claude Opus 5.5 (`claude-opus-5-5`, official `anthropic` Python SDK) on the frozen evaluation set; cheaper model only if the user chooses it | budget ~$0-10; the user sets a spending cap in the Anthropic Console first; token estimate shown before the run |
| Live demo and CI | Replay the recorded answers from Phase 8 (and the local-model run); no API key anywhere in the cloud | $0 |

Rules: no paid call during building; the only paid script refuses to run without an explicit `--confirm-spend` flag and a printed estimate; every paid answer is saved so it is never paid for twice.

## Phases

Each phase lists what gets built, why, and what "done" means. "Verified" always means an independent script that recomputes the phase's claims a different way, runs in CI, and passes.

### Phase 0: Setup (done 2026-11-21)
- **Build:** repo, `.gitignore` (data, `.env`, weights, caches), `requirements.txt`, pytest, CI skeleton, `CLAUDE.md`, this plan, learning log.
- **Why:** a clean, reproducible base; secrets and data can never be committed by accident.
- **Done:** tests pass locally; committed.

### Phase 1: Data access and scope
- **Build:** openFDA client (`mdqc/openfda.py`) and access check (done: `docs/OPENFDA_ACCESS.md`, 11/11 probes). Then a pre-registered scope file: 3-4 product codes a quality engineer at a large device maker would own (candidates: FRN infusion pump, LZG/QFG insulin pumps, LPH hip and JWH knee prostheses, DXY pacemaker) and a date window (e.g. reports received 2022-2024), with expected record counts from server-side `count` queries and the expected download size, shown to the user before fetching. Optional free openFDA API key via a hidden-prompt `.env` writer. Data card (what MAUDE is and is not).
- **Why:** the whole project's honesty depends on a fixed, justified slice of data chosen before looking at results.
- **Done:** scope committed before download; raw JSONL.gz in `data/raw/` with checksums; record counts match the server's counts; verifier re-counts.

### Phase 2: Pipeline and database
- **Build:** ingest raw files into a local DuckDB database (tables: reports, devices, narratives, problems, recalls, and a report-recall link by product code + 510(k) number + date window); drop personal contact fields; dedupe; validation rules with a quarantine table; idempotent re-runs.
- **Why:** the assistant's tools query this database; numbers must be reproducible and clean.
- **Done:** every raw record accounted for (loaded or quarantined with a reason); verifier recomputes counts and spot values from the raw files with pandas; tests.

### Phase 3: Exploratory analysis and signal detection
- **Build:** notebook + doc: monthly report trends per product code and manufacturer, problem-code Pareto, event-type mix, recall timeline overlay. A pre-registered statistical signal rule (e.g. a Poisson control chart on monthly counts, or disproportionality of a problem code for one manufacturer vs the product code) and an honest backtest: did signals come before recalls?
- **Why:** this is what a quality engineer does first; it also gives the assistant real, checkable analysis tools and gives the evaluation gold answers.
- **Done:** findings doc generated from results files; signal rule fixed before the backtest; verifier recomputes trends and signals independently.

### Phase 4: Retrieval
- **Build:** chunked narratives; keyword search (BM25), a local embedding model on CPU (e.g. bge-small or MiniLM through sentence-transformers), and a hybrid. A labelled retrieval set (weak labels from FDA problem codes plus a small hand-labelled set), split by product code into validation and test.
- **Why:** answers must cite the right reports; retrieval quality is measured, not assumed.
- **Done:** method chosen on validation (recall@k, MRR, bootstrap intervals, Holm correction), confirmed on test; verifier re-scores from saved rankings.

### Phase 5: Assistant (tools + local model)
- **Build:** a tool-using investigator: tools `search_reports`, `count_reports`, `trend`, `find_recalls`, `get_report`, `signal_check`. Model-agnostic backend: local model through Ollama for building, Claude interface written but not called. Every answer cites report keys or recall numbers; numbers come from tools, never from the model's memory. Guardrails: no medical advice; "a report is not proof the device caused the event".
- **Why:** the product a recruiter sees; grounding keeps it honest.
- **Done:** scripted demo investigations run end to end locally; verifier checks that every number and citation in recorded answers appears in the tool results of that answer.

### Phase 6: Investigation memory
- **Build:** a memory store (SQLite) per investigation: product, hypotheses, ruled out (with the evidence), decisions, open questions, timeline. Written only by explicit memory tools, shown to the user when saved, loaded at the start of the next session. View / edit / delete / export API; deletion really removes the item (and anything derived from it).
- **Why:** real investigations run for weeks; the user must see and control what is remembered.
- **Done:** multi-session scenario tests (session 2 recalls what session 1 ruled out; a deleted item is never used again); verifier inspects the database after deletion.

### Phase 7: Evaluation set and local-model evaluation
- **Build:** a pre-registered evaluation set (about 80 questions: counts and trends with gold answers computed by SQL, citation questions, report-recall questions, multi-session memory scenarios, deletion scenarios, refusal/safety cases) and a scorer (correctness, citation precision, groundedness, memory recall, deletion honoured, refusal). Run with the local model; record every transcript.
- **Why:** an AI project without an evaluation is a demo; pre-registration stops us from tuning to the test.
- **Done:** criteria committed before the first scored run; results doc generated; verifier re-scores the recorded transcripts with independent code.

### Phase 8: Final paid evaluation (Claude, capped)
- **Build:** cost estimate (token counting) shown to the user; the user sets a Console spending cap; **one** run of Claude Opus 5.5 on the frozen evaluation set; all answers recorded (cassettes); same scorer; local vs Claude comparison with intervals; actual cost reported.
- **Why:** shows what a frontier model adds over a free local one, at a known, small cost.
- **Done:** spend within budget; recorded answers committed (no keys); comparison doc generated; verifier re-scores from cassettes.

### Phase 9: App
- **Build:** Streamlit app: investigation workspace (replays recorded answers in the cloud; optional live local mode on the laptop), evidence views (trends, reports, recalls), **memory page** (view and delete; the cloud demo uses a sandbox memory per visitor), About/limits page. Deployed on Streamlit Community Cloud.
- **Why:** recruiters click a link; it must cost nothing and never break.
- **Done:** pre-registered scorecard; live smoke check passes on the deployed URL; every displayed number checked against the results files.

### Phase 10: Write-up and release
- **Build:** README (problem, demo link, results, how to run), case study, results/architecture/decisions docs generated from results files, resume bullets (kept outside the repo), final whole-project verification, release v1.0.0.
- **Why:** the project is only as useful as its explanation.
- **Done:** generated docs byte-identical on re-render; all verifiers pass in CI; tag + GitHub release (after the user approves creating the public repository and pushing).

## Conventions (same spirit as the predictive maintenance project, lighter where possible)

- Pre-register criteria (commit them) before the run they judge; label anything decided afterwards as post hoc.
- Generate result docs from results files; never hand-type a number.
- Split by product code (never by report) for any validation/test; choose on validation, confirm on test; Holm correction for multiple comparisons.
- Honest reporting: say what failed; MAUDE counts are signals, not failure rates.
- No personal data in the repo (no email/phone; the dataset's contact fields are dropped).
- Batch fixes: check thoroughly once, then one commit, instead of many small fix-ups.
- Each phase ends with a "Why we did these tasks" table and a dated `docs/LEARNING_LOG.md` entry.
