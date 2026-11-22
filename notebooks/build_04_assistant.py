"""Build and execute notebooks/04_assistant.ipynb (run from the repo root; needs the local database)."""
import nbformat as nbf
from nbclient import NotebookClient

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("# Phase 4: the investigation assistant (pipeline proven, model run in Phase 6)\n\n"
       "The assistant answers a quality engineer's questions by calling fixed database tools. This phase proves "
       "everything around the model for free; the one paid model run is in Phase 6 "
       "([`docs/ASSISTANT.md`](../docs/ASSISTANT.md), generated).\n\n"
       "**Key ideas**\n"
       "- **Tool use:** the model does not see the database. It asks for a tool (e.g. `count_reports`), our code runs "
       "it, and the JSON result goes back to the model.\n"
       "- **Agent loop:** ask, run tools, send results back, repeat until the model answers.\n"
       "- **Grounding:** every number and citation in an answer must appear in a tool result.\n"
       "- **Cassette:** a recording of every model response and tool result, replayed for free in CI and the demo.\n"
       "- **Scripted stand-in:** a fixed list of tool calls plus a template answer (not a model), used to prove the pipeline."),
    code("import json, os, sys\nfrom pathlib import Path\nimport pandas as pd, psycopg\nfrom dotenv import load_dotenv\n"
         "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\nsys.path.insert(0, str(ROOT))\n"
         "load_dotenv(ROOT / '.env')\ncon = psycopg.connect(os.environ['DATABASE_URL'])\n"
         "from mdqc.tools import run_tool, TOOL_DEFINITIONS\nfrom mdqc import verify_phase4 as v4\n"
         "pd.DataFrame([(t['name'], t['description']) for t in TOOL_DEFINITIONS], columns=['tool', 'what it does'])"),
    md("## 1. A tool call, exactly as the model would make it\n\nThe model sends a name and arguments; it gets JSON back."),
    code("out, err = run_tool(con, 'failure_modes', {'product_code': 'JWH', 'manufacturer': 'exactech'})\n"
         "r = json.loads(out); print('error:', err, '| filters echoed back:', r['filters'])\n"
         "pd.DataFrame(r['modes'])[['failure_mode', 'reports', 'share']].head(5)"),
    code("print(run_tool(con, 'count_reports', {'product_code': 'FRN'}))  # a bad argument comes back as an error the model can fix"),
    md("## 2. The nine pre-registered questions, run by the scripted stand-in"),
    code("rows = []\nfor p in sorted((ROOT / 'results/phase4/scripted').glob('Q*.json')):\n"
         "    r = json.loads(p.read_text(encoding='utf-8'))\n"
         "    rows.append({'id': r['id'], 'kind': r['kind'], 'tools': ', '.join(t['name'] for t in r['tool_calls']), 'answer': r['answer'].split('\\n', 1)[1][:160]})\n"
         "pd.set_option('display.max_colwidth', 170); pd.DataFrame(rows)"),
    md("## 3. The grounding checker catches an invented number\n\nWe take a correct answer and change one number."),
    code("q1 = json.loads((ROOT / 'results/phase4/scripted/Q1.json').read_text(encoding='utf-8'))\nresults = [t['result'] for t in q1['tool_calls']]\n"
         "good = v4.grounding(q1['answer'], results)\nbad = v4.grounding(q1['answer'].replace('15,522', '15,523', 1) + ' See [MDR 99999999].', results)\n"
         "print('correct answer, numbers traced:', [n for n, ok in good['numbers'] if ok])\n"
         "print('planted answer, untraceable:', [n for n, ok in bad['numbers'] if not ok], [c[1] for c in bad['citations'] if not c[2]])"),
    md("## 4. Checks and scorecard"),
    code("V = json.loads((ROOT / 'results/phase4/verify_phase4.json').read_text(encoding='utf-8'))\nprint('Scorecard', V['scorecard_score'])\n"
         "con.close()\npd.DataFrame([(c['id'], c['check'], 'pass' if c['pass'] else 'FAIL') for c in V['checks']], columns=['id', 'check', 'result'])"),
    md("## Why we did these tasks\n\n"
       "| Task | Why we did it | What we learned | What it changes next |\n|---|---|---|---|\n"
       "| Fixed, read-only tools instead of free SQL | The model can only ask questions we have tested | Eight tools cover counts, trends, modes, search, reports, recalls and signals; all match independent SQL | Phase 5 adds memory tools the same way |\n"
       "| Our own agent loop with a ledger and budget stop | Cost must be known and capped around every call | The ledger matches an independent formula; budget, refusal and step limits work | Phase 6's paid run uses this loop unchanged |\n"
       "| Deferring the paid run to Phase 6 (post hoc) | The user wants one paid run for the whole project | A scripted stand-in proves the pipeline end to end for $0 | Phase 6 runs the nine questions live with the evaluation |\n"
       "| Grounding and safety checkers | Every number and citation must be traceable | They pass correct answers and catch planted invented numbers, keys and recalls | Phase 6 applies them to the model's answers |\n"
       "| Recording and replay | The demo and CI must cost nothing and never change | Every recording replays identically offline | Phase 8's app replays the Phase 6 recordings |"),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": "notebooks"}}).execute()
nbf.write(nb, "notebooks/04_assistant.ipynb")
print("notebook executed and written")
