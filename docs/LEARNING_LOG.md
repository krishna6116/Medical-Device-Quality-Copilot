# Learning log

## 2026-11-21: Phase 0 setup and Phase 1 start (openFDA access check)

**Decided:** full version (10 phases, 0-9, ~5-6 weeks), laid out like the predictive maintenance project and reusing its patterns: pre-registered criteria and a verification script in CI for every phase, PostgreSQL pipeline, failure-mode grouping with a non-LLM baseline, safety + cost + drift monitoring, Streamlit + Power BI. Assistant model: Claude Haiku 5.5 (`claude-haiku-5-5`, $0.10 / $0.50 per million input/output tokens), used while building too; a few dollars for the whole project under a monthly Console cap. Data, pipeline and failure grouping stay free (PostgreSQL, BM25, a local CPU embedding model). Phase 6 compares Haiku with one run of a stronger Claude model; the demo and CI replay recorded answers.

**Scope today:** setup only (Phase 0). The openFDA access check was done as a quick look so the plan rests on facts; nothing was downloaded.

**Built:** the repo (`.gitignore` that blocks data, `.env`, weights and caches; `.gitattributes` for LF; `requirements.txt`; pytest; CI skeleton), `CLAUDE.md` and `docs/PLAN.md` with the phase plan, an openFDA client and an access-check script.

**Concepts:**
- *MAUDE / MDR*: the FDA database of Medical Device Reports. Manufacturers must report deaths, serious injuries and malfunctions; hospitals and patients may. A report is a signal, not proof the device caused the event, and there is no count of devices in use, so report counts are not failure rates.
- *Product code*: FDA's 3-letter device category (FRN = infusion pump, LPH = uncemented hip prosthesis). It is the natural key for scoping a quality investigation.
- *API paging*: openFDA returns at most 1,000 records per request (999 without a key on the event endpoint, which we discovered by testing), and `skip` stops at 25,000; deeper pages use the `search_after` token in the response's Link header.
- *Rate limits*: without a key 1,000 requests/day per IP; with a free key 120,000/day.
- *Why check before building*: the plan assumes certain fields (narratives, problem codes, recall root causes) exist. Eleven small probes proved they do, and found surprises early (a recall with a 9.8 MB lot list; manufacturer contact names and phone numbers we must drop; a 19 GB bulk event file we will not download).

**Next:** pick the product codes and date window, show the user the expected download size, then fetch.

## 2026-11-21 (later): Phase 1 data and exploratory analysis

**Decided:** scope = LPH hip, JWH + MBH knees, LWP pacemaker, LZG insulin pump; reports received 2022-2024 plus all recalls (154,194 reports, 1,626 recalls, ~1 GB transfer, 68 MB stored). Infusion pumps (FRN) were dropped after the count showed 1.1M reports, 888k of them in 2022 and nearly all from one manufacturer.

**Built:** pre-registration (`config/scope.json`, `config/phase1_criteria.json`, committed before downloading), downloader with retries and resume, EDA module, generated findings doc, data card, executed notebook, independent stdlib-only verifier, a small committed fixture so CI can run EDA + verifier without downloading.

**Concepts:**
- *Pre-registration:* write down what you will measure and what counts as success before seeing the data, and commit it, so the git history proves the order.
- *Completeness check:* compare what you downloaded with the source's own count for the same query, taken right before the download (the source changes weekly).
- *Reproducible checksums:* gzip stores a file name and a timestamp in its header, so identical content can give different checksums; writing both as empty fixes that.
- *Independent verification:* the same numbers computed twice by different code. Here it found a recall dated year '0013' that the two versions treated differently: a real data error, now handled by an explicit (post hoc) rule.
- *Reading MAUDE:* implant reports are mostly "injury" (another operation), pump reports mostly "malfunction"; the generic problem term dominates, so the failure mode must come from the narrative text; reports can arrive years late.

**Next:** Phase 2, the PostgreSQL pipeline (drop contact fields, normalise manufacturer names, repair or flag bad dates, link reports to recalls).

## 2026-11-21 (re-check): Phase 1 correction

**What happened:** a re-check compared our published numbers with openFDA's own server-side counts. Monthly volumes, event types and recall root causes matched exactly, but every problem-term count was about double: openFDA lists most problem terms twice inside one report, and both the analysis and the verifier counted list entries. Because they shared the same definition, they agreed with each other and the verifier passed.

**Fixed:** terms are now counted once per report in both programs (a test pins it), the findings doc carries a dated correction note, and the verifier gained criterion C8 (post hoc): published numbers must equal the server's own counts. Corrected example: the generic "no device problem identified" term is on 48% of hip reports, not 96%. No other number changed.

**Concept:** *independent* verification needs an independent source, not just independent code. Two programs written from the same (wrong) definition fail together; an outside reference (here the data owner's own counts) catches that.

**Same day, gaps closed:** the two plan items Phase 1 had not delivered are now done. (1) Q9, per-manufacturer monthly trends (post hoc, verified like every other number): code totals hide makers moving in opposite directions, e.g. one knee maker's reports rose 253% from 2022 to 2024 while the other two large makers stayed flat, and the October 2022 pacemaker peak came from St. Jude/Abbott, not the largest maker. (2) `python -m mdqc.setup_env`, an optional hidden-prompt writer for API keys. *Concept:* aggregation can hide structure (a form of Simpson's paradox in time series), so trends are read at the level where decisions are made: per manufacturer.

## 2026-11-21 (evening): Phase 2 PostgreSQL pipeline

**Decided:** a separate database `mdqc` with its own login `mdqc_app` (created once from the predictive maintenance project's admin connection; the new password lives only in this project's `.env`).

**Built:** pre-registered rules and criteria (committed before the first load), a star schema, a one-transaction loader with quarantine, manufacturer parent mapping, report-recall links, an independent verifier (cell-for-cell rebuild of 1.1M rows, privacy scan, idempotent reload, planted faults, Phase 1 numbers reproduced), DB tests (a single tampered cell is caught; link-window edges), a CI job with a real PostgreSQL, a generated pipeline doc and a notebook that runs SQL.

**Concepts:**
- *Star schema:* facts (events) in the middle, dimensions (what the events are about) around them; repeated lists in child tables so each item is counted once.
- *Quarantine, not deletion:* a bad record is kept with the rule it broke, so nothing disappears silently. The rules caught one real report with no narrative at all.
- *Idempotence:* the load rebuilds everything in one transaction, so running it twice gives identical tables (checked with fingerprints).
- *Least privilege:* the app login owns only its own database.
- *Entity resolution:* 305 spellings of manufacturers became 101 parent companies with written ownership rules (St. Jude -> Abbott, Howmedica -> Stryker, ...); a small misspelled tail is documented instead of quietly patched.
- *Link strength:* a shared 510(k) number links a report to recalls years apart, so the assistant must filter links by date and say how strong a link is.

**Next:** Phase 3, failure-mode grouping with non-LLM baselines and a per-manufacturer signal rule.

**Phase 2 re-check (same evening):** everything passed again (CI ran every database test, none skipped). Following the Phase 1 lesson, the database was also compared directly with openFDA's own server counts. Two apparent differences were explained, not data errors: recall status has no exact-count field on the server (my query asked for one), and one Boston Scientific report is the quarantined one. That comparison is now permanent criterion P11 (post hoc, `--network`), shown to fail on a planted change. Health checks found 3 insulin-pump narratives with a stray control character that is in FDA's own text; it is kept as received and will be normalised before search in Phase 3. *Concept:* when a check disagrees, first check the check (here the query), then the data.

## 2026-11-21 (night): Phase 3 failure modes, similar reports, early-warning signals

**Decided:** reference labels written by Claude from a codebook, spot-checked (the user delegated the review; 18/20 on a second full-text pass); embedding model bge-small-en-v1.5 on CPU; no paid model in this phase; a 5-item scorecard (no performance target) committed before any result.

**Result:** FDA's own coded problem terms, mapped through the codebook, beat every text method (70% test accuracy vs 60% for keyword rules and 32% for zero-shot embeddings). Embedding search was chosen on validation, but BM25 did as well on test. The alert rule flagged 214 company-mode-months; 15 of 38 recall events had a signal in the 6 months before, against a 14% base rate.

**Concepts:**
- *Codebook and reference labels:* write definitions first, then label, then run methods; commit each step so the order is provable.
- *Validation vs test:* choose on one half, score the other once. The FDA baseline won by a pre-registered tie-break (simpler wins) and then also won on test.
- *Negative results are results:* Phase 1 expected the narrative to be necessary; Phase 3 showed the coded terms already carry most of the signal. Reported, not tuned away.
- *Embeddings:* meaning-based numbers; great for "find reports like this", poor at matching a long, boilerplate-heavy narrative to a one-sentence definition.
- *Poisson signal:* is this month's count surprisingly high compared with the last year's average? A prompt to look, not proof.
- *Templates:* many reports share identical text, so similarity search needs duplicate collapsing.

**Next:** Phase 4, the assistant with tools on Claude Haiku 5.5.

## 2026-11-22: Phase 4 the investigation assistant (no paid call)

**Decided:** the user wants a single paid run for the whole project, in Phase 6. Phase 4's nine pre-registered questions move into that run (a post hoc amendment, committed before any run), and Phase 4 proves the pipeline for free.

**Built:** eight read-only database tools (the model never writes SQL), our own agent loop for Claude Haiku 5.5 with a cost ledger from the API's token counts and a hard budget stop, recordings ("cassettes") with offline replay, a scripted stand-in that drives the real loop and tools without a model, grounding and safety checkers, fake-model tests, and a verifier (scorecard v2 5/5).

**Concepts:**
- *Tool use:* the model asks for a named tool with arguments; our code runs it and returns JSON. The model only ever sees what the tools return.
- *Agent loop:* ask, run tools, send results back, repeat; we keep the loop in our own code so we can meter, cap and record every call.
- *Grounding:* every number and citation in an answer must appear in a tool result; the checker catches invented numbers, report keys and recall numbers.
- *Prompt caching:* the long, unchanging part of each request (rules + tool list) is cached, so repeat calls pay about 10% for it.
- *Cassettes and replay:* record once, replay forever for $0; CI and the demo never call the API.
- *Honest substitution:* when the paid run moved, the change was written down before any run, and the stand-in's answers say they are not from a model.

**Next:** Phase 5, investigation memory (remembering what was ruled out across sessions, with view and delete).

**Phase 4 re-check (same day):** a stress test with odd inputs (the kind a real model will sometimes send) found problems the well-formed scripted run could not: a malformed date or limit crashed a tool and left the database connection broken; a pacemaker question with a hip failure mode returned a silent 0; and recall searches before 2022 were silently moved into the report window, giving a wrong answer with no error. All fixed; tools now never raise, and a 15-input stress suite is part of the verifier. *Concept:* test the unhappy path. A tool used by a model must turn every bad input into a clear error the model can correct, and must never quietly answer a different question.

## 2026-11-22 (late): Phase 5 investigation memory ($0)

**Built:** a separate `memory` schema (investigations, sessions, memory items, and an audit trail that stores no text), an API and CLI to view, edit, export and delete memory, four memory tools for the assistant bound to the current investigation, memory loaded into the assistant's instructions at the start of every session, three multi-session scenarios run through the real loop with the scripted stand-in, and a verifier.

**Concepts:**
- *Session memory vs. chat history:* the model forgets between sessions; memory is a deliberate, small, structured record (ruled out, hypotheses, decisions, questions) loaded at the start of each session.
- *Explicit writes:* memory is written only through tools or the user, and every save is confirmed, so nothing is remembered behind the user's back.
- *Guardrails:* evidence must point to real reports or recalls (no invented citations) and personal contact details are refused before anything is stored.
- *Real deletion:* remove the row, keep the audit trail content-free, and prove it by scanning every column for the deleted text.
- *A check must be able to fail:* the first deletion scan searched only for whole texts and missed a planted partial copy; it now searches the start and end of each text and plants a copy to test itself on every run.

**Next:** Phase 6, the evaluation set and the single paid run (needs the Claude API key saved in `.env`).

## 2026-11-22 (night): full audit of Phases 0-5

**What was checked:** every verifier in full (with the live openFDA cross-checks), all 78 tests, all five notebooks re-executed from scratch, every generated document against its results, the database state, secrets and personal data across the whole git history, and each phase against the written plan.

**Result:** no wrong number and no failing check. The audit found documentation gaps, now closed: Phase 3's differences from the plan (sample split by report inside each code, no embedding clustering, MRR instead of recall@k, why no multiple-comparison correction, no paid labelling) were explained only in code, not in the doc; the plan's Phase 6 did not yet say it now carries Phase 4's nine live questions and the memory evaluation; the README's run instructions stopped at Phase 2.

**Concept:** a plan written before the work and criteria committed during it can drift apart; when they do, follow the committed criteria and say so in the public write-up, not only in the code.

## 2026-11-22 (night): Phase 6 evaluation, the project's only paid run ($4.11)

**Built:** an 85-question evaluation set with gold answers computed from the database, committed with its grading rules and a decision rule before any grader or model answer existed; a grader proven on two free stand-ins (answers from the gold must all pass, planted wrong answers must all fail); one recorded run per model (Haiku 5.5, then Opus 5.5, the user's choice after a cost estimate calibrated on Haiku's real token counts); an independent verifier and a generated report.

**Result:** Haiku 78/80, Opus 76/80; the difference is not significant, so Haiku stays (pre-registered rule). Haiku cost 40 times less ($0.10 vs $4.01).

**Concepts:**
- *Pre-registration:* fixing questions, answers and rules first means the result cannot be steered after seeing answers.
- *Positive and negative controls:* a grader that only ever says yes proves nothing; it must also catch planted mistakes.
- *Paired comparison:* both models answer the same questions, so we compare them question by question (McNemar test, paired bootstrap).
- *Literal graders have blind spots:* all six misses were correct answers the rules did not recognise (negations like 'did not rise', a 'care team' referral). The grades stay as pre-registered, and a labelled hand review explains each one.
- *Ceiling effects:* when the cheap model is already near 100%, a stronger model cannot show a meaningful gain on this set.

**Next:** Phase 7, safety guardrails, cost tracking and drift monitoring (write negation-aware checks and test them on planted negated answers).

## 2026-11-22 (late night): Phase 4's live part closed ($0)

**Done:** Phase 4's original criteria A1-A5 were run on Haiku's live answers to the nine Phase 4 questions (recorded in the Phase 6 paid run, so no new API call): original scorecard 5/5, and `docs/ASSISTANT.md` now shows the live answers instead of saying no model had answered.

**Found:** A1 first failed. The tool was right (6,152 Boston Scientific battery reports); the verifier's independent count ignored the tool's optional filters and counted all 21,753 reports. The free scripted runs never used those filters, so the gap only showed when the real model did. Fixed (post hoc) and proven with a planted wrong count.

**Concept:** test inputs from a script cover only the paths the script takes; a real model explores more of the tool's options, so a verifier must mirror every option the tool accepts, and should be tested with planted errors on each one.

