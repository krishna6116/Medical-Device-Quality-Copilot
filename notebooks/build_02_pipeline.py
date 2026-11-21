"""Build and execute notebooks/02_pipeline.ipynb.

Run from the repo root after `python -m mdqc.load`:  python notebooks/build_02_pipeline.py
The notebook queries the local PostgreSQL database (DATABASE_URL in .env) and reads results/phase2/.
"""
import nbformat as nbf
from nbclient import NotebookClient

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("# Phase 2: from raw files to a PostgreSQL star schema\n\n"
       "Phase 1 gave us raw JSON files. Phase 2 turns them into clean, typed tables that the assistant's tools can "
       "query. This notebook runs real SQL against the database so you can see how the tables fit together. "
       "The full write-up is [`docs/PIPELINE.md`](../docs/PIPELINE.md) (generated).\n\n"
       "**Key ideas**\n"
       "- **Star schema:** a *fact* table holds events (one row per report, one per recall); *dimension* tables "
       "hold the things events are about (product code, manufacturer, date). Lists inside a report (devices, "
       "problem terms, narratives) get child tables, so each item is stored and counted exactly once.\n"
       "- **Quarantine:** a record that breaks a rule is not silently dropped; it is kept with the rule it broke.\n"
       "- **Idempotent load:** running the load twice gives exactly the same tables.\n"
       "- **Pre-registered rules:** cleaning rules, the manufacturer map and link rules were committed before the "
       "first load, so they could not be tuned to the results."),
    code("import json, os\nfrom pathlib import Path\n\nimport pandas as pd\nimport psycopg\nfrom dotenv import load_dotenv\n\n"
         "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
         "load_dotenv(ROOT / '.env')\n"
         "con = psycopg.connect(os.environ['DATABASE_URL'])\n"
         "def sql(q, *args):\n"
         "    cur = con.execute(q, args)\n"
         "    return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])\n"
         "LS = json.loads((ROOT / 'results/phase2/load_summary.json').read_text(encoding='utf-8'))\n"
         "VER = json.loads((ROOT / 'results/phase2/verify_phase2.json').read_text(encoding='utf-8'))"),
    md("## 1. What got loaded, and what was quarantined"),
    code("sql(\"\"\"SELECT 'fact_report' t, count(*) FROM core.fact_report UNION ALL\n"
         "       SELECT 'report_text', count(*) FROM core.report_text UNION ALL\n"
         "       SELECT 'report_problem', count(*) FROM core.report_problem UNION ALL\n"
         "       SELECT 'fact_recall', count(*) FROM core.fact_recall UNION ALL\n"
         "       SELECT 'report_recall_link', count(*) FROM core.report_recall_link UNION ALL\n"
         "       SELECT 'quarantine', count(*) FROM core.quarantine\"\"\")"),
    code("sql('SELECT source, record_key, rule, detail FROM core.quarantine')"),
    md("The one quarantined report has no narrative text at all (rule R5). It is kept, with its reason, instead "
       "of disappearing."),
    md("## 2. One report, joined across the star\n\nA single report touches six tables. The query below follows "
       "one of them through the joins (the narrative is shortened)."),
    code("key = sql(\"SELECT min(mdr_report_key) k FROM core.fact_report WHERE product_code='MBH' AND event_type='Injury'\").k[0]\n"
         "sql(\"\"\"SELECT r.mdr_report_key, r.product_code, p.device_name, m.raw_name, m.parent_company,\n"
         "              r.date_received, r.event_type, r.brand_name, r.pma_pmn_number\n"
         "       FROM core.fact_report r JOIN core.dim_product_code p USING (product_code)\n"
         "       JOIN core.dim_manufacturer m USING (manufacturer_id) WHERE r.mdr_report_key = %s\"\"\", key).T"),
    code("display(sql('SELECT term FROM core.report_problem WHERE mdr_report_key = %s', key))\n"
         "sql('SELECT text_type, left(text, 300) AS text FROM core.report_text WHERE mdr_report_key = %s ORDER BY text_seq', key)"),
    md("## 3. Manufacturer names become parent companies\n\nFDA writes the same company many ways. The registered "
       "rules clean the names and merge known brands (St. Jude Medical into Abbott, Howmedica into Stryker, ...)."),
    code("sql(\"\"\"SELECT parent_company, count(*) AS spellings, string_agg(raw_name, ' | ' ORDER BY raw_name) AS examples\n"
         "       FROM core.dim_manufacturer GROUP BY 1 HAVING count(*) > 2 ORDER BY 2 DESC LIMIT 8\"\"\")"),
    code("sql(\"\"\"SELECT r.product_code, m.parent_company, extract(year FROM r.date_received)::int AS year, count(*)\n"
         "       FROM core.fact_report r JOIN core.dim_manufacturer m USING (manufacturer_id)\n"
         "       WHERE r.product_code = 'LWP' GROUP BY 1, 2, 3 HAVING count(*) > 100 ORDER BY 2, 3\"\"\")"),
    md("For pacemakers (LWP), Phase 1 showed St. Jude Medical and Abbott as two separate makers. After merging they "
       "are one parent, Abbott, which is how a quality engineer would think about it."),
    md("## 4. Linking reports to recalls\n\nTwo registered rules: **510(k)** (same clearance number and product code) "
       "and **firm_window** (same parent company and product code, report received 180 days before to 365 days "
       "after the recall started). A link is context, never proof."),
    code("sql(\"\"\"SELECT link_type, count(*) AS links, count(DISTINCT mdr_report_key) AS reports,\n"
         "              count(DISTINCT product_res_number) AS recalls,\n"
         "              percentile_disc(0.5) WITHIN GROUP (ORDER BY days_from_initiation) AS median_days\n"
         "       FROM core.report_recall_link GROUP BY 1\"\"\")"),
    code("sql(\"\"\"SELECT l.link_type, c.product_res_number, c.event_date_initiated, c.root_cause,\n"
         "              left(c.reason_for_recall, 120) AS reason, l.days_from_initiation\n"
         "       FROM core.report_recall_link l JOIN core.fact_recall c USING (product_res_number)\n"
         "       WHERE l.mdr_report_key = (SELECT mdr_report_key FROM core.report_recall_link\n"
         "                                 WHERE link_type = 'firm_window' ORDER BY mdr_report_key LIMIT 1)\n"
         "       ORDER BY abs(l.days_from_initiation) LIMIT 5\"\"\")"),
    md("## 5. Verification\n\n`python -m mdqc.verify_phase2` rebuilds every table from the raw files with separate "
       "code and compares every row and column, plants faults, reloads, and reproduces Phase 1's numbers:"),
    code("pd.DataFrame([(c['id'], c['check'], 'pass' if c['pass'] else 'FAIL') for c in VER['checks']],\n"
         "             columns=['id', 'check', 'result']).sort_values('id')"),
    code("con.close()"),
    md("## Why we did these tasks\n\n"
       "| Task | Why we did it | What we learned | What it changes next |\n|---|---|---|---|\n"
       "| Separate database and login | Projects must not share tables or passwords | An existing admin connection can create a least-privilege login once | Every later phase connects as mdqc_app |\n"
       "| Pre-registered rules before the first load | So cleaning could not be tuned to make numbers look good | The registered rules caught a real report with no narrative and repaired the 0013 recall date | Rule changes from now on are labelled post hoc |\n"
       "| Star schema with child tables | Counts must be right by construction (e.g. a term once per report) | Repeated FDA lists (devices, terms, texts) belong in their own tables | Phase 3 and the assistant's tools query clean, typed tables |\n"
       "| Dropped personal fields at load | Privacy by default; the assistant never needs them | Contact names and phones were in most reports | Nothing downstream can leak what was never stored |\n"
       "| Manufacturer parents | Trends per company need one name per company | Hundreds of spellings became about a hundred parents; a small misspelled tail remains | Phase 3 signals are computed per parent company |\n"
       "| Report-recall links | An investigator asks 'was there a recall for this?' | 510(k) links are broad in time; pacemakers can only link by firm and date | Phase 4 tools filter links by date and label their strength |\n"
       "| Independent verifier, planted faults, tamper test | A pipeline that cannot fail its check proves nothing | Every row matched; every planted fault and a single edited cell were caught | CI runs the same checks on a real PostgreSQL for every push |"),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": "notebooks"}}).execute()
nbf.write(nb, "notebooks/02_pipeline.ipynb")
print("notebook executed and written")
