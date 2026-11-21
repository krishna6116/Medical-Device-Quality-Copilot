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
