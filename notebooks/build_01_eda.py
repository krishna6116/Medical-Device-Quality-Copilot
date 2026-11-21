"""Build and execute notebooks/01_eda.ipynb.

Run from the repo root:  python notebooks/build_01_eda.py
The notebook only reads results/phase1/ and docs/, so run python -m mdqc.eda and
python -m mdqc.report_phase1 first.
"""
import nbformat as nbf
from nbclient import NotebookClient

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("# Phase 1: openFDA device data, exploratory analysis\n\n"
       "This notebook walks through the Phase 1 data: what we downloaded, whether it is complete, and what it "
       "looks like. Every number shown is read from `results/phase1/` (made by `python -m mdqc.eda`) and was "
       "recomputed independently by `python -m mdqc.verify_phase1`. The written findings are in "
       "[`docs/EDA_FINDINGS.md`](../docs/EDA_FINDINGS.md).\n\n"
       "**Key ideas**\n"
       "- **MAUDE report (MDR):** a manufacturer, hospital or patient tells the FDA a device *may* have been "
       "involved in a death, injury or malfunction. It is a signal, not a confirmed failure.\n"
       "- **Product code:** FDA's 3-letter device category. Our scope (pre-registered in `config/scope.json`): "
       "LPH hip, JWH and MBH knees, LWP pacemaker, LZG insulin pump; reports received 2022-2024.\n"
       "- **No denominator:** we never know how many devices are in use, so counts are not failure rates."),
    code("import json\nfrom pathlib import Path\n\nimport pandas as pd\nfrom IPython.display import Image, Markdown, display\n\n"
         "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
         "S = json.loads((ROOT / 'results/phase1/eda_summary.json').read_text(encoding='utf-8'))\n"
         "M = json.loads((ROOT / 'results/phase1/download_manifest.json').read_text(encoding='utf-8'))\n"
         "V = json.loads((ROOT / 'results/phase1/verify_phase1.json').read_text(encoding='utf-8'))\n"
         "codes, pc = S['codes'], S['per_code']"),
    md("## 1. Is the download complete?\n\n"
       "Before each product code was downloaded we asked the server how many reports match; afterwards we "
       "counted what we got. Equal numbers and zero duplicates mean nothing was lost or doubled while paging "
       "through results 999 at a time."),
    code("pd.DataFrame({c: {'server total': e['server_total_before'], 'downloaded': e['downloaded'],\n"
         "                  'duplicates': e['duplicates']} for c, e in M['events'].items()}).T"),
    code("pd.DataFrame([(c['id'], c['check'], 'pass' if c['pass'] else 'FAIL') for c in V['checks']],\n"
         "             columns=['id', 'check', 'result'])"),
    md("## 2. Volume over time (Q1)\n\nEach code has its own y-axis because volumes differ by 17x."),
    code("display(Image(filename=str(ROOT / 'docs/figures/phase1/monthly_reports.png'), width=800))\n"
         "pd.DataFrame({c: {'reports': pc[c]['reports'], 'median / month': pc[c]['q1_monthly_median'],\n"
         "                  'busiest month': pc[c]['q1_monthly_max_month'], 'busiest count': pc[c]['q1_monthly_max']}\n"
         "              for c in codes}).T"),
    md("## 3. What kind of events (Q2) and which problem terms (Q3)\n\nProblem terms are counted once per report (openFDA repeats terms inside a report; see the correction in the findings doc)."),
    code("display(Image(filename=str(ROOT / 'docs/figures/phase1/event_type_mix.png'), width=800))\n"
         "pd.DataFrame({c: pc[c]['q2_event_type'] for c in codes}).fillna(0).astype(int).T"),
    code("pd.DataFrame({c: [f'{p} ({k:,})' for p, k in pc[c]['q3_top_problems'][:5]] for c in codes},\n"
         "             index=[f'#{i}' for i in range(1, 6)])"),
    md("The most common term for four of the five codes says no device problem was identified. The real "
       "failure description lives in the narrative text, which is why Phase 3 works from the text."),
    md("## 4. Manufacturers (Q4) and narratives (Q5)"),
    code("pd.DataFrame({c: {'largest maker': pc[c]['q4_top_manufacturers'][0][0],\n"
         "                  'its share': f\"{pc[c]['q4_top_manufacturer_share']:.0%}\",\n"
         "                  'makers': pc[c]['q4_distinct_manufacturers'],\n"
         "                  'with narrative': f\"{pc[c]['q5_share_with_narrative']:.0%}\",\n"
         "                  'median narrative chars': pc[c]['q5_narrative_len_median']} for c in codes}).T"),
    md("## 5. Recalls (Q6), reporting lag (Q7), multi-device reports (Q8)"),
    code("display(Image(filename=str(ROOT / 'docs/figures/phase1/recalls_per_year.png'), width=800))\n"
         "pd.DataFrame({c: {'recall records': pc[c]['q6_recalls'], 'recall events': pc[c]['q6_recall_events_distinct'],\n"
         "                  'in 2022-2024': pc[c]['q6_recalls_in_window'],\n"
         "                  'invalid date': pc[c]['q6_recalls_invalid_initiation_date'],\n"
         "                  'median lag (days)': pc[c]['q7_lag_median_days'], 'p90 lag (days)': pc[c]['q7_lag_p90_days'],\n"
         "                  'multi-device reports': pc[c]['q8_multi_device_reports']} for c in codes}).T"),
    md("## 6. Manufacturer trends (Q9, added post hoc on the re-check)\n\n"
       "A code's total can stay flat while one maker rises and another falls, so we also look at the three "
       "largest manufacturers per code. Names are as reported (St. Jude Medical is part of Abbott since 2017; "
       "Phase 2 merges such names)."),
    code("display(Image(filename=str(ROOT / 'docs/figures/phase1/manufacturer_trends.png'), width=800))\n"
         "pd.DataFrame([{'code': c, 'manufacturer': m, **by} for c in codes\n"
         "              for m, by in pc[c]['q9_top3_by_year'].items()])"),
    md("## 7. Findings\n\nThe findings text is generated from the same results files:"),
    code("doc = (ROOT / 'docs/EDA_FINDINGS.md').read_text(encoding='utf-8')\n"
         "display(Markdown(doc.split('## What stands out')[1].split('## Checks (criteria')[0]))"),
    md("## Why we did these tasks\n\n"
       "| Task | Why we did it | What we learned | What it changes next |\n|---|---|---|---|\n"
       "| Pre-registered the scope before downloading | So the data could not be picked to flatter results | Infusion pumps alone would have been ~7x the download and dominated by one manufacturer | Every later phase uses exactly these 5 codes and this window |\n"
       "| Compared every count with the server's own total | To prove nothing was lost or doubled while paging | All counts matched exactly, zero duplicates | Phase 2 can treat the raw files as the single source |\n"
       "| Checksums on the raw files | To pin our copy (openFDA changes weekly) | gzip embeds a file name and time; writing neither makes checksums reproducible | Later phases check they read the same bytes |\n"
       "| Answered the pre-registered questions Q1-Q8 | To learn the data's shape before modelling | Problem codes are coarse, narratives are rich, one maker often dominates, implant reports arrive late | Phase 3 groups failure modes from text; trends per manufacturer; drift checks allow for lag |\n"
       "| Independent verifier | So a bug in the analysis cannot pass silently | It caught a recall dated year 0013 that the two implementations handled differently | Phase 2 adds date validation and repair rules for recall dates |\n"
       "| Cross-check against openFDA's own server counts | Two programs can share the same wrong definition | Problem terms are repeated inside reports; our counts were doubled until this check | Every later verifier also compares with an outside source |\n"
       "| Per-manufacturer trends (Q9, post hoc) | The plan asked for them; code totals can hide makers | Makers move in opposite directions inside one code (e.g. one knee maker +253% while others stay flat) | Phase 3 signals per manufacturer; Phase 2 merges brand names like St. Jude / Abbott |"),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": "notebooks"}}).execute()
nbf.write(nb, "notebooks/01_eda.ipynb")
print("notebook executed and written")
