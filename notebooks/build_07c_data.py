"""Build and execute notebooks/07bc_guard_and_data.ipynb (run from the repo root). Reads committed results only: no database, no API."""
import nbformat as nbf
from nbclient import NotebookClient

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell


def why(path):
    t = open(path, encoding="utf-8").read()
    return t[t.index("## Why we did these tasks"):]


cells = [
    md("# Phases 7b and 7c: a new guard, and reports from 2025-2026\n\nWrite-ups: [`docs/GUARD_7B.md`](../docs/GUARD_7B.md), [`docs/DATA_2025_2026.md`](../docs/DATA_2025_2026.md).\n\n"
       "**Key ideas**\n- **Paired test:** the same answer with and without one planted unsafe sentence.\n- **Fingerprint:** a number that changes if any row of a table changes.\n"
       "- **Scope:** the same fixed lookups over 2022-2024 (default) or 2022-2026."),
    code("import json\nfrom pathlib import Path\nimport pandas as pd\nROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
         "load = lambda p: json.loads((ROOT / 'results' / p).read_text(encoding='utf-8'))\nG = load('phase7b/test_grades.json')\nprint('7b labels by Claude Opus, no human check; passes:', G['passes'])\n"
         "pd.Series({k: G[k] for k in ('caught', 'missed', 'clean_withheld', 'new_withheld', 'plants_labelled_unsafe')})"),
    md(why("docs/GUARD_7B.md").replace("## Why", "## 7b: why")),
    md("## 7c: independent checks"),
    code("V = load('phase7c/verify_phase7c.json')\nprint(V['passed'])\npd.DataFrame([(c['id'], c['check'], c['pass']) for c in V['checks']], columns=['id', 'check', 'pass'])"),
    md("## 7c: Haiku on 2022-2026"),
    code("M = load('phase7c/model_check.json')\nprint(M['correct'], 'bar', M['bar'], '$', M['usd'])\npd.DataFrame(M['rows'])[['id', 'category', 'correct', 'steps', 'usd']]"),
    md(why("docs/DATA_2025_2026.md").replace("## Why", "## 7c: why")),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": "notebooks"}}).execute()
nbf.write(nb, "notebooks/07bc_guard_and_data.ipynb")
print("errors", sum(o.get("output_type") == "error" for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", [])))
