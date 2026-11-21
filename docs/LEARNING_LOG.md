# Learning log

## 2026-11-21: Phase 0 setup and Phase 1 start (openFDA access check)

**Decided:** full version (11 phases, ~5-6 weeks), with a verification script per phase. Cost plan: free local tools while building; one capped Claude Opus 5.5 run for the final evaluation; the demo replays recorded answers.

**Built:** the repo (`.gitignore` that blocks data, `.env`, weights and caches; `.gitattributes` for LF; `requirements.txt`; pytest; CI skeleton), `CLAUDE.md` and `docs/PLAN.md` with the phase plan, an openFDA client and an access-check script.

**Concepts:**
- *MAUDE / MDR*: the FDA database of Medical Device Reports. Manufacturers must report deaths, serious injuries and malfunctions; hospitals and patients may. A report is a signal, not proof the device caused the event, and there is no count of devices in use, so report counts are not failure rates.
- *Product code*: FDA's 3-letter device category (FRN = infusion pump, LPH = uncemented hip prosthesis). It is the natural key for scoping a quality investigation.
- *API paging*: openFDA returns at most 1,000 records per request (999 without a key on the event endpoint, which we discovered by testing), and `skip` stops at 25,000; deeper pages use the `search_after` token in the response's Link header.
- *Rate limits*: without a key 1,000 requests/day per IP; with a free key 120,000/day.
- *Why check before building*: the plan assumes certain fields (narratives, problem codes, recall root causes) exist. Eleven small probes proved they do, and found surprises early (a recall with a 9.8 MB lot list; manufacturer contact names and phone numbers we must drop; a 19 GB bulk event file we will not download).

**Next:** pick the product codes and date window, show the user the expected download size, then fetch.
