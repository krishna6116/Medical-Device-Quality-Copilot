"""Build and execute notebooks/07_safety_drift.ipynb (run from the repo root). Reads committed results only: no database, no API."""
import nbformat as nbf
from nbclient import NotebookClient

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
doc = open("docs/SAFETY_AND_DRIFT.md", encoding="utf-8").read()
why = doc[doc.index("## Why we did these tasks"):]
cells = [
    md("# Phase 7: safety guardrails, cost and drift\n\nFull write-up: [`docs/SAFETY_AND_DRIFT.md`](../docs/SAFETY_AND_DRIFT.md). The red-team criterion (G2) is **not met**: the guard withheld too many safe answers.\n\n"
       "**Key ideas**\n- **Red-team:** questions written to make the assistant misbehave, plus ordinary questions to catch over-refusal.\n"
       "- **Prompt injection:** hostile instructions hidden in the data a tool returns.\n- **Held-out test:** examples a detector was never tuned on.\n"
       "- **Drift:** new data that no longer looks like the data the tool was built on."),
    code("import json\nfrom pathlib import Path\nimport pandas as pd\nROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
         "load = lambda p: json.loads((ROOT / 'results/phase7' / p).read_text(encoding='utf-8'))\nG = load('redteam_grades.json')\n"
         "print('G2 met:', G['G2_met'])\npd.DataFrame(G['categories']).T"),
    md("## 1. What the guard withheld\n\nEvery one of these answers had been labelled safe by hand (not independently)."),
    code("pd.DataFrame([(r['id'], r['category'], ', '.join(r['withheld_for'])) for r in G['rows'] if r['withheld_for']], columns=['case', 'category', 'withheld for'])"),
    md("## 2. The judge's two validation attempts"),
    code("pd.DataFrame([{'attempt': a, 'label': k, 'caught': f\"{x['caught']}/{x['bad']}\", 'false alarms': f\"{x['false_alarms']}/{x['good']}\", 'bar met': x['meets_bar']}\n"
         "              for a, f in (('first', 'judge/validation_summary.json'), ('second', 'judge/validation_v2_summary.json')) for k, x in load(f)['labels'].items()])"),
    md("## 3. Drift: every check (volume change, mode mix, vocabulary)"),
    code("D = load('drift_check.json')\nprint(D['thresholds'], D['flags'])\npd.DataFrame(D['rows'])[['code', 'quarter', 'reports', 'volume_change', 'mode_mix', 'vocabulary', 'flags']].round(3)"),
    md("## 4. What the drift checks can and cannot see (planted shifts)"),
    code("pd.Series(load('drift_baseline.json')['planted_detection'])"),
    md("## 5. Independent verification"),
    code("V = load('verify_phase7.json')\nprint('evidence', V['evidence_ok'], '| scorecard', V['scorecard'])\npd.DataFrame([(c['id'], c['met'], c['check']) for c in V['checks']], columns=['id', 'met', 'check'])"),
    md(why),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": "notebooks"}}).execute()
nbf.write(nb, "notebooks/07_safety_drift.ipynb")
print("errors", sum(o.get("output_type") == "error" for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", [])))
