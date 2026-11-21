"""Build and execute notebooks/03_failure_modes.ipynb.

Run from the repo root after `python -m mdqc.run_phase3`:  python notebooks/build_03_failure_modes.py
Needs the local database and data/processed/ embeddings (for the live similar-report demo).
"""
import nbformat as nbf
from nbclient import NotebookClient

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("# Phase 3: failure modes, similar reports, early warnings\n\n"
       "Question: can we tell *how* a device failed from a report, find reports like it, and spot a company's "
       "failure mode rising before a recall? Full write-up: [`docs/FAILURE_MODES.md`](../docs/FAILURE_MODES.md) (generated).\n\n"
       "**Key ideas**\n"
       "- **Codebook:** written definitions of each failure mode, fixed before labelling (`config/failure_modes.json`).\n"
       "- **Reference labels:** 200 reports labelled from the codebook (by Claude; 18/20 agreed on a second full-text pass).\n"
       "- **Validation vs test:** methods are compared and chosen on the validation half; the test half is scored once.\n"
       "- **Embedding:** a list of numbers that places a text by meaning; similar texts get similar numbers.\n"
       "- **Signal:** a month with far more reports than the previous year's average (Poisson rule), per company and mode."),
    code("import json, os, csv\nfrom pathlib import Path\nimport numpy as np, pandas as pd, psycopg\nimport matplotlib.pyplot as plt\n"
         "from dotenv import load_dotenv\nfrom IPython.display import Markdown, display\n\n"
         "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\nimport sys; sys.path.insert(0, str(ROOT))\nload_dotenv(ROOT / '.env')\n"
         "con = psycopg.connect(os.environ['DATABASE_URL'])\n"
         "R = lambda n: json.loads((ROOT / 'results/phase3' / n).read_text(encoding='utf-8'))\n"
         "SEL, RET, SIG, VER = R('selection.json'), R('retrieval.json'), R('signals.json'), R('verify_phase3.json')\n"
         "pred = pd.read_csv(ROOT / 'results/phase3/predictions_sample.csv', dtype=str)\n"
         "print('Scorecard:', VER['scorecard_score'])"),
    md("## 1. Five methods, chosen on validation, tested once"),
    code("pd.DataFrame({m: {'setting': SEL['chosen_settings'][m], 'validation': SEL['validation_accuracy'][m],\n"
         "                  'test': SEL['test'][m]['accuracy'], 'test 95% interval': SEL['test'][m]['accuracy_ci95'],\n"
         "                  **{f'test {f}': v for f, v in SEL['test'][m]['accuracy_by_family'].items()}}\n"
         "              for m in ['M1', 'M2', 'M3', 'M4', 'M5']}).T"),
    md("FDA's coded terms (M1) won: it tied the keyword rules on validation, won the tie-break as the simpler "
       "method, and was best on test. The expectation from Phase 1 (that the narrative would be needed) did not hold."),
    md("## 2. Where the chosen method goes wrong (test half)"),
    code("t = pred[pred.split == 'test']\nct = pd.crosstab(t.label, t.M1, rownames=['reference'], colnames=['M1 predicted'])\n"
         "ct.loc[:, ct.sum() > 0]"),
    md("## 3. Failure modes across all 154k reports"),
    code("q = '''SELECT product_code, mode, count(*) n FROM analytics.report_failure_mode GROUP BY 1, 2'''\n"
         "df = pd.DataFrame(con.execute(q).fetchall(), columns=['code', 'mode', 'n'])\n"
         "df['share'] = (df.n / df.groupby('code').n.transform('sum')).round(3)\n"
         "df.sort_values(['code', 'n'], ascending=[True, False]).groupby('code').head(4)"),
    md("## 4. Similar-report search, live\n\nOne insulin-pump report and its five nearest neighbours by embedding "
       "(cosine similarity). On the labelled test set, BM25 keyword search did slightly better (not significant). "
       "Note the similarities of 1.000: many manufacturer reports are word-for-word templates, so 'similar' often "
       "means 'identical wording'. Phase 4 should group identical texts and show the count instead of repeating them."),
    code("keys = (ROOT / 'data/processed/embeddings_bge_small_keys.txt').read_text().split()\n"
         "E = np.load(ROOT / 'data/processed/embeddings_bge_small.npy').astype(np.float32)\nrow = {k: i for i, k in enumerate(keys)}\n"
         "from mdqc.textprep import load_texts\nq = '16005019'\n"
         "same = [k for (k,) in con.execute(\"SELECT mdr_report_key FROM core.fact_report WHERE product_code='LZG'\").fetchall()]\n"
         "idx = np.array([row[k] for k in same]); sims = E[idx] @ E[row[q]]\n"
         "top = [same[i] for i in np.argsort(-sims)[1:6]]\nT = load_texts(con, 'core', [q] + top)\n"
         "modes = dict(con.execute('SELECT mdr_report_key, mode FROM analytics.report_failure_mode WHERE mdr_report_key = ANY(%s)', ([q] + top,)).fetchall())\n"
         "print('QUERY', q, modes[q], '|', T[q][:220])\n"
         "for k in top: print(f'{float(E[row[k]] @ E[row[q]]):.3f}', k, modes[k], '|', T[k][:160])"),
    md("## 5. Early-warning signals and the recall backtest"),
    code("print({k: SIG[k] for k in ['signals', 'signals_per_year', 'series_with_signal', 'series', 'recall_events', 'hits', 'hit_rate', 'base_rate']})\n"
         "pd.DataFrame(SIG['events'])[['event', 'code', 'parent', 'initiated', 'hit']].head(12)"),
    code("q = '''SELECT to_char(r.date_received, 'YYYY-MM') m, count(*) FROM core.fact_report r\n"
         "        JOIN core.dim_manufacturer d USING (manufacturer_id) JOIN analytics.report_failure_mode f USING (mdr_report_key)\n"
         "        WHERE r.product_code = 'JWH' AND d.parent_company = 'EXACTECH' AND f.mode = 'O_WEAR' GROUP BY 1 ORDER BY 1'''\n"
         "s = pd.DataFrame(con.execute(q).fetchall(), columns=['month', 'n']).set_index('month').n\n"
         "flag = [x['month'] for x in SIG['signal_list'] if x['code'] == 'JWH' and x['parent'] == 'EXACTECH' and x['mode'] == 'O_WEAR']\n"
         "fig, ax = plt.subplots(figsize=(9, 3)); ax.plot(range(len(s)), s.values, color='#2a78d6', lw=2)\n"
         "ax.scatter([list(s.index).index(m) for m in flag if m in s.index], [s[m] for m in flag if m in s.index], color='#eb6834', zorder=3, label='signal')\n"
         "ax.set_xticks(range(0, len(s), 6), s.index[::6]); ax.set_title('Exactech knee (JWH) reports per month, mode = wear', loc='left')\n"
         "ax.legend(frameon=False); ax.spines[['top', 'right']].set_visible(False); plt.show()"),
    md("A signal is a prompt to look, not evidence of a defect: reports also rise after recalls, lawsuits and "
       "retrospective reporting campaigns."),
    code("con.close()\npd.DataFrame([(c['id'], c['check'], 'pass' if c['pass'] else 'FAIL') for c in VER['checks']], columns=['id', 'check', 'result'])"),
    md("## Why we did these tasks\n\n"
       "| Task | Why we did it | What we learned | What it changes next |\n|---|---|---|---|\n"
       "| Codebook before labels, labels before methods | So neither the labels nor the methods could drift toward the other | Writing definitions first forces hard choices (cause vs symptom, priority order) | Phase 6 reuses the same labels to grade the assistant |\n"
       "| Five methods, chosen on validation, tested once | To learn whether anything beats FDA's own coded terms, without fooling ourselves | FDA terms mapped through the codebook won (70% on test); zero-shot embeddings failed | Phase 4's failure-mode tool uses the FDA-term mapping |\n"
       "| Local embedding model | Meaning-based search for free on a laptop | 154k reports embedded on CPU in about 2.4 hours; embedding and BM25 search are close | Phase 4 offers similar-report search at no cost |\n"
       "| Alert rule per company and mode, backtested | A quality engineer wants early warning, not hindsight | 15 of 38 recall events had a prior signal vs a 14% base rate | Phase 7 monitoring reuses the rule; the assistant presents signals as prompts, not proof |\n"
       "| Independent verifier and 5-item scorecard | Every number recomputed by separate code | Scorecard 5/5; the full-corpus labels reproduced exactly | Same pattern for the assistant's evaluation in Phase 6 |"),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
NotebookClient(nb, timeout=900, kernel_name="python3", resources={"metadata": {"path": "notebooks"}}).execute()
nbf.write(nb, "notebooks/03_failure_modes.ipynb")
print("notebook executed and written")
