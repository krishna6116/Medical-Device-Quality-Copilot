"""Build and execute notebooks/06_evaluation.ipynb (run from the repo root). Reads only committed results files:
no database and no API call."""
import nbformat as nbf
from nbclient import NotebookClient

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("# Phase 6: evaluating the assistant (the project's only paid run)\n\n"
       "Does the investigation assistant answer correctly, keep to facts from the data, stay safe and in scope, and use "
       "investigation memory well, and what does that cost? Full write-up: [`docs/EVALUATION.md`](../docs/EVALUATION.md).\n\n"
       "**Key ideas**\n"
       "- **Evaluation set:** 85 questions written and committed *before* any model answered, with correct ('gold') answers "
       "computed from the database. Fixing them in advance stops anyone tuning the test to the model.\n"
       "- **Grader:** fixed text rules per question type (the right number, the right company named first, a referral to a "
       "doctor...). Proven on two free stand-ins: one answering from the gold (must pass everything), one planted wrong (must fail everything).\n"
       "- **Paired comparison:** both models answer the same questions, so we compare them question by question.\n"
       "- **Made-up facts:** numbers or citations in an answer that are not in that question's tool results."),
    code("import json\nfrom pathlib import Path\nimport pandas as pd\n"
         "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
         "S = json.loads((ROOT / 'results/phase6/summary.json').read_text(encoding='utf-8'))\n"
         "pd.DataFrame({m: {'correct': f\"{r['correct']}/{r['of']}\", 'accuracy': f\"{100*r['accuracy']:.1f}%\",\n"
         "                  '95% interval': f\"{100*r['ci95'][0]:.1f}-{100*r['ci95'][1]:.1f}%\", 'cost $': r['cost_usd'],\n"
         "                  '$ per correct': r['usd_per_correct'], 'answers with made-up facts': r['answers_with_made_up_facts']}\n"
         "              for m, r in S['models'].items()}).T"),
    md("## 1. Accuracy by category"),
    code("pd.DataFrame({m: {c: f\"{v['correct']}/{v['of']}\" for c, v in r['categories'].items()} for m, r in S['models'].items()})"),
    md("## 2. Paired comparison and the pre-registered decision"),
    code("c = S.get('comparison')\nprint(json.dumps({k: v for k, v in c.items() if k != 'decision'}, indent=1) if c else 'pending')\n"
         "print('\\nDecision:', c['decision'] if c else 'pending')"),
    md("## 3. Every wrong answer, with the grader's reason\n\nThe rules are literal. Reading each miss shows whether the "
       "model was wrong or the rule was too strict; the grades stay as pre-registered either way."),
    code("for m, r in S['models'].items():\n    print(m)\n    for i, why in r['wrong'].items():\n        print('  ', i, '-', why)"),
    md("## 4. One recorded answer (Haiku, a safety question)"),
    code("r = json.loads((ROOT / 'results/phase6/claude-haiku-5-5/E62.json').read_text(encoding='utf-8'))\n"
         "print(r['question']); print('tools:', [t['name'] for t in r['tool_calls']]); print(); print(r['answer'])"),
    md("## 5. Controls and checks"),
    code("print(S['controls'])\nV = S.get('verification', {})\nprint('Scorecard', V.get('scorecard_score'))\n"
         "[(x['id'], x['check'], 'pass' if x['pass'] else 'FAIL') for x in V.get('checks', [])]"),
    md("## Why we did these tasks\n\n"
       "| Task | Why we did it | What we learned | What it changes next |\n|---|---|---|---|\n"
       "| Pre-registered 85 questions with gold answers from SQL | An AI project without an evaluation is a demo; fixing the test first stops tuning to it | Gold answers re-derived a second way (pandas) all agree | Phase 7 adds red-team and drift cases the same way |\n"
       "| Free gold and planted-wrong controls | A grader must be able to say both yes and no | 80/80 and 0/80 before any paid call; tests caught a rounding bug (26.5 -> 26) | Every future grader gets the same two controls |\n"
       "| One paid run per model, every call recorded | Re-rolling answers until they look good is cheating; recordings let anyone re-check for free | Spend tracked from the API's own token counts, including failed attempts | The demo and CI replay recordings at no cost |\n"
       "| Paired comparison with a fixed decision rule | To know whether the cheap model is good enough | See the decision above | The assistant model for Phases 7-9 |\n"
       "| Hand review of every wrong answer | Literal rules can mark a right answer wrong | Some misses were strict-rule cases (a 'care team' referral; 'did not rise') | Phase 7 guardrail checks use wider referral wording, fixed in advance |"),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": "notebooks"}}).execute()
nbf.write(nb, "notebooks/06_evaluation.ipynb")
print("notebook executed and written")
