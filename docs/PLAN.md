# Project plan: Medical Device Quality Copilot (full version)

**Goal.** An AI assistant for a quality engineer at a medical device company (think Stryker or Medtronic) who is investigating field failures. It answers questions from public FDA data (openFDA MAUDE adverse-event reports and device recalls) with citations to the exact reports, groups reports into failure modes, links them to recalls, and **remembers each open investigation across sessions** (product, hypotheses, what was ruled out and why, decisions, open questions). A separate page shows everything it remembers and lets the user delete any of it.

**Scope chosen:** full version (decided 2026-11-21): 10 phases (0-9), about 5-6 weeks. Built like the predictive maintenance project but reusing its patterns to stay efficient: each phase's success criteria are **pre-registered in a commit before its results exist**, and each phase has an **independent verification script that runs in CI**.

## Cost plan

| Stage | What runs | Cost |
|---|---|---|
| Building (all phases) | openFDA API (free), PostgreSQL (local), keyword search (BM25), a small local embedding model on CPU, optionally a local open model through Ollama (7-8B, 4-bit, fits 16 GB RAM without a GPU) | $0 |
| Final evaluation (Phase 6) | **One** capped run of Claude Opus 5.5 (`claude-opus-5-5`, official `anthropic` Python SDK) on the frozen evaluation set; a cheaper model only if the user chooses it | about $2-10; the user sets a spending cap in the Anthropic Console first; token estimate shown before the run |
| Live demo and CI | Replay the recorded answers (local-model run and the Claude run); no API key anywhere in the cloud | $0 |

Rules: no paid call during building; the only paid script refuses to run without an explicit `--confirm-spend` flag and a printed estimate; every paid answer is saved so it is never paid for twice; Phase 7 tracks the actual spend.

## Phases

Each phase lists what gets built, why, and what "done" means. "Verified" always means an independent script that recomputes the phase's claims a different way, runs in CI, and passes. "Pre-registered" means the criteria file is committed before the run it judges.

### Phase 0: Setup (done 2026-11-21)
- **Build:** repo, `.gitignore` (data, `.env`, weights, caches), `requirements.txt`, pytest, CI skeleton, `CLAUDE.md`, this plan, learning log, openFDA client.
- **Why:** a clean, reproducible base; secrets and data can never be committed by accident.
- **Done:** tests pass locally; committed.

### Phase 1: Data and exploratory analysis
- **Build:** openFDA access check (done: `docs/OPENFDA_ACCESS.md`, 11/11 probes). Pre-registered scope: 3-4 product codes a quality engineer at a large device maker would own (candidates: FRN infusion pump, LZG/QFG insulin pumps, LPH hip and JWH knee prostheses, DXY pacemaker) and a date window (e.g. reports received 2022-2024), with expected record counts from server-side `count` queries and the expected download size, **shown to the user before fetching**. Optional free openFDA key via a hidden-prompt `.env` writer. Raw JSONL.gz with checksums. EDA notebook + findings doc: monthly trends per product code and manufacturer, event-type mix, problem-code Pareto, narrative lengths, recall timeline, data card (what MAUDE is and is not).
- **Why:** the project's honesty depends on a fixed, justified slice of data chosen before looking at results; EDA tells us what the later phases must handle.
- **Done:** scope committed before download; downloaded counts match the server's counts; findings doc generated from results; verifier re-counts from the raw files.

### Phase 2: Pipeline into PostgreSQL with validation
- **Build:** star schema in PostgreSQL (fact: reports; dimensions: device/product code, manufacturer, date, problem term; plus narratives, recalls, and a report-recall link by product code + 510(k) number + date window); drop the dataset's personal contact fields; dedupe; validation rules with a quarantine table; idempotent, re-runnable loads (reusing the predictive maintenance pipeline patterns).
- **Why:** the assistant's tools and the dashboards query this database; numbers must be reproducible and clean.
- **Done:** every raw record accounted for (loaded or quarantined with a reason); verifier compares the database cell for cell with the raw files using different code; CI job loads a small pinned sample into a Postgres service.

### Phase 3: Failure-mode grouping with a non-LLM baseline
- **Build:** group report narratives into failure modes (e.g. occlusion alarm, battery, software, loosening/fracture). Non-LLM baselines first: FDA problem codes as weak labels, TF-IDF + clustering, and local-embedding clustering; a hand-labelled sample split by product code into validation and test. Optional local-LLM labelling compared against the baselines. Retrieval for later phases (BM25 vs local embeddings vs hybrid) chosen here on the same validation set. A pre-registered signal rule (e.g. control chart on monthly counts per failure mode) with an honest backtest: did signals come before recalls?
- **Why:** quality engineers think in failure modes; a non-LLM baseline shows whether an LLM adds anything (same honesty rule as "publish the winner even if it is not the deep model").
- **Done:** method chosen on validation (agreement/F1, recall@k, bootstrap intervals, Holm), confirmed on test; verifier re-scores from saved labels and rankings.

### Phase 4: Assistant with tools
- **Build:** a tool-using investigator: tools `search_reports`, `count_reports`, `trend`, `failure_modes`, `find_recalls`, `get_report`, `signal_check`, all reading PostgreSQL. Model-agnostic backend: local model through Ollama for building; Claude backend written but not called. Every answer cites report keys or recall numbers; numbers come from tools, never from the model's memory.
- **Why:** the product a recruiter sees; grounding keeps it honest.
- **Done:** scripted demo investigations run end to end locally; verifier checks that every number and citation in recorded answers appears in that answer's tool results.

### Phase 5: Investigation memory
- **Build:** a memory store (PostgreSQL schema `memory`) per investigation: product, hypotheses, ruled out (with the evidence), decisions, open questions, timeline. Written only by explicit memory tools, shown to the user when saved, loaded at the start of the next session. View / edit / delete / export; deletion really removes the item and anything derived from it.
- **Why:** real investigations run for weeks; the user must see and control what is remembered.
- **Done:** multi-session scenario tests (session 2 recalls what session 1 ruled out; a deleted item is never used again); verifier inspects the database after deletion.

### Phase 6: Evaluation set and grading
- **Build:** a pre-registered evaluation set (about 80 questions: counts and trends with gold answers computed by SQL, citation questions, failure-mode and report-recall questions, multi-session memory scenarios, deletion scenarios, refusal/safety cases) and a grader (correctness, citation precision, groundedness, memory recall, deletion honoured, refusal). Run with the local model; then the **one capped Claude Opus 5.5 run** (estimate shown, user's Console cap set first). Every answer recorded (cassettes).
- **Why:** an AI project without an evaluation is a demo; pre-registration stops tuning to the test; the paired comparison shows what a frontier model adds at a known cost.
- **Done:** criteria committed before the first scored run; spend within budget; comparison doc with intervals generated from results; verifier re-grades the recorded transcripts with independent code.

### Phase 7: Safety guardrails, cost tracking and drift monitoring
- **Build:** guardrails (no medical advice; "a report is not proof the device caused the event"; refuse questions about identifiable patients; prompt-injection test cases from report text), a cost ledger (tokens and dollars per call, budget stop), and monitoring of new FDA reports: a scheduled pull of the latest weeks, drift checks on volume, failure-mode mix and narrative vocabulary against the Phase 1 baseline, and a flag when the assistant's grounding rate drops (reusing the Phase 7 monitoring patterns from the predictive maintenance project).
- **Why:** what makes an AI tool safe to run in a regulated company after the demo.
- **Done:** pre-registered guardrail and drift criteria; red-team cases pass; drift checks run on real new data; verifier recomputes drift statistics and ledger totals independently.

### Phase 8: Streamlit app and Power BI report
- **Build:** Streamlit app: investigation workspace (replays recorded answers in the cloud; optional live local mode on the laptop), evidence views (trends, failure modes, reports, recalls), **memory page** (view and delete; the cloud demo uses a sandbox memory per visitor), About/limits page; snapshot CSVs for the cloud. Power BI report on a read-only PostgreSQL login (file kept outside the repo, exports as evidence). Deployed on Streamlit Community Cloud.
- **Why:** recruiters click a link (it must cost nothing and never break); Power BI is what many analytics and quality teams use.
- **Done:** pre-registered scorecard; live smoke check passes on the deployed URL; every displayed number checked against the snapshots and the database.

### Phase 9: README, case study and release
- **Build:** README (problem, demo link, results, how to run), case study, results/architecture/decisions docs generated from results files, resume bullets (kept outside the repo), final whole-project verification, release v1.0.0.
- **Why:** the project is only as useful as its explanation.
- **Done:** generated docs byte-identical on re-render; all verifiers pass in CI; tag + GitHub release (after the user approves creating the public repository and pushing).

## Conventions (same spirit as the predictive maintenance project, reusing its patterns)

- Pre-register criteria (commit them) before the run they judge; label anything decided afterwards as post hoc.
- Generate result docs from results files; never hand-type a number.
- Split by product code (never by report) for any validation/test; choose on validation, confirm on test; Holm correction for multiple comparisons.
- Honest reporting: say what failed; MAUDE counts are signals, not failure rates.
- No personal data in the repo (no email/phone; the dataset's contact fields are dropped).
- Batch fixes: check thoroughly once, then one commit, instead of many small fix-ups.
- Each phase ends with a "Why we did these tasks" table and a dated `docs/LEARNING_LOG.md` entry.
