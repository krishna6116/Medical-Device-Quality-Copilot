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
