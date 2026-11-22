"""Build and execute notebooks/05_memory.ipynb (run from the repo root; needs the local database).
Uses a throwaway schema (notebook_memory) so it never touches real investigations."""
import nbformat as nbf
from nbclient import NotebookClient

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("# Phase 5: investigation memory\n\n"
       "The assistant remembers what an investigation has established, so the next session starts where the last one "
       "stopped; the user can see, edit, export and delete all of it. Full write-up: [`docs/MEMORY.md`](../docs/MEMORY.md).\n\n"
       "**Key ideas**\n- **Memory item:** one saved conclusion: ruled out (with why), hypothesis, decision, open question or note.\n"
       "- **Memory block:** the text loaded into the assistant's instructions at the start of every session.\n"
       "- **Guardrails:** evidence must be real reports or recalls; no personal data; every save is confirmed.\n"
       "- **Real deletion:** the row is removed and the audit trail keeps no text.\n\n"
       "This notebook works in a throwaway schema (`notebook_memory`), so it never touches real investigations."),
    code("import json, os, sys\nfrom pathlib import Path\nimport psycopg\nfrom dotenv import load_dotenv\n"
         "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\nsys.path.insert(0, str(ROOT))\n"
         "load_dotenv(ROOT / '.env')\nfrom mdqc import memory as mem\nfrom mdqc.tools import make_runner\n"
         "con = psycopg.connect(os.environ['DATABASE_URL'])\nS = 'notebook_memory'\n"
         "con.execute(f'DROP SCHEMA IF EXISTS {S} CASCADE'); mem.ensure_schema(con, S)\n"
         "inv = mem.create_investigation(con, 'Insulet pod adhesive failures', 'LZG', 'INSULET', schema=S); inv"),
    md("## 1. Session 1 saves what was concluded\n\nThese are the same calls the assistant makes through its `remember` tool."),
    code("run = make_runner(con, inv, mem.start_session(con, inv, schema=S), S)\n"
         "for args in [{'kind': 'ruled_out', 'text': 'Rising adhesive failures ruled out for 2022-2024 (down 4.4%).'},\n"
         "             {'kind': 'hypothesis', 'text': 'Dislodged pods may relate to wear time over 48 hours.'}]:\n"
         "    print(json.loads(run('remember', args)[0])['confirmation'])"),
    md("## 2. Guardrails refuse bad saves"),
    code("for args in [{'kind': 'note', 'text': 'Compare with this report.', 'evidence': ['MDR 99999999']},\n"
         "             {'kind': 'note', 'text': 'Call the surgeon on 555-123-4567.'}]:\n    print(run('remember', args))"),
    md("## 3. Session 2 starts with the memory already loaded"),
    code("print(mem.memory_block(con, inv, S))"),
    md("## 4. The user deletes the hypothesis: it is gone everywhere"),
    code("hyp = [i for i in mem.get_items(con, inv, S) if i['kind'] == 'hypothesis'][0]\n"
         "print(mem.delete_item(con, hyp['item_id'], schema=S)['confirmation'])\nprint(mem.memory_block(con, inv, S))\n"
         "hits = [(t, c) for t, c in con.execute(\"SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = %s AND data_type IN ('text', 'jsonb')\", (S,)).fetchall()\n"
         "        if con.execute(f'SELECT count(*) FROM {S}.{t} WHERE \"{c}\"::text ILIKE %s', ('%wear time%',)).fetchone()[0]]\n"
         "print('columns still holding the deleted text:', hits)"),
    md("## 5. Export: everything stored, nothing hidden"),
    code("print(mem.export_markdown(con, inv, S))\ncon.execute(f'DROP SCHEMA {S} CASCADE'); con.commit(); con.close()"),
    md("## 6. Checks"),
    code("V = json.loads((ROOT / 'results/phase5/verify_phase5.json').read_text(encoding='utf-8'))\nprint('Scorecard', V['scorecard_score'])\n"
         "[(c['id'], c['check'], 'pass' if c['pass'] else 'FAIL') for c in V['checks']]"),
    md("## Why we did these tasks\n\n"
       "| Task | Why we did it | What we learned | What it changes next |\n|---|---|---|---|\n"
       "| Separate memory schema | Memory must survive data reloads and stay apart from FDA data | A data reload leaves memory untouched (tested) | Phase 8's memory page reads this schema |\n"
       "| Explicit memory tools with confirmations | The user must always know what was saved | Every save is echoed; one investigation cannot touch another | Phase 6 checks the real model confirms its saves |\n"
       "| Guardrails on evidence and personal data | Memory must not hold invented evidence or personal data | Invented report keys, phones and emails are refused before storing | Phase 7 adds wider guardrail tests |\n"
       "| Real deletion with a text-free audit trail | Deleting must leave no copy behind | A whole-text scan missed a partial copy; the scan now self-tests | Same pattern for any future store |\n"
       "| Independent replay of every memory action | To prove each session saw exactly the right memory | All 7 scenario sessions matched | Phase 6 adds multi-session questions for the real model |"),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": "notebooks"}}).execute()
nbf.write(nb, "notebooks/05_memory.ipynb")
print("notebook executed and written")
