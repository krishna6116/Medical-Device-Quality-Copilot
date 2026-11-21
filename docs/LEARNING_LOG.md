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
