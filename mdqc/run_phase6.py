"""Phase 6: run the pre-registered evaluation set and record every answer.

Run:  python -m mdqc.run_phase6                         cost estimate for each model (no API call)
      python -m mdqc.run_phase6 --control               free: run the gold and planted-wrong stand-ins through the real loop
      python -m mdqc.run_phase6 --live --model claude-haiku-5-5      paid: the assistant model (needs ANTHROPIC_API_KEY)
      python -m mdqc.run_phase6 --live --model claude-sonnet-5-5     paid: the comparison model (or claude-opus-5-5)
      python -m mdqc.run_phase6 --grade                 grade every recording -> results/phase6/grades.json

Rules (config/phase6_criteria.json): every question once per model; a recording is never overwritten, so no answer
is re-rolled; budgets per question and per model; memory questions run in a throwaway schema with their prepared
memory loaded at session start. Every API response's token usage is also appended to _usage.jsonl the moment it
arrives, so even an attempt that crashes mid-question is counted in the spend.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from mdqc import assistant, grade
from mdqc import memory as mem
from mdqc.scripted import _msg
from mdqc.tools import MEMORY_TOOL_DEFINITIONS, TOOL_DEFINITIONS, make_runner, run_tool

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "phase6"
EVAL = json.loads((ROOT / "config" / "phase6_eval_set.json").read_text(encoding="utf-8"))
QUESTIONS, MODE_WORDS = EVAL["questions"], EVAL["mode_words"]
ASSISTANT_MODEL = "claude-haiku-5-5"
COMPARISON = ("claude-sonnet-5-5", "claude-opus-5-5")
BUDGET = {"claude-haiku-5-5": (1.50, 0.25), "claude-sonnet-5-5": (6.00, 0.50), "claude-opus-5-5": (6.00, 0.50)}
PHASE_CAP = 7.50
MS = "eval_memory"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


# ---- one question ------------------------------------------------------------------------------------------
def prepare_memory(con, q):
    """Fresh schema with the question's investigation and prepared items; returns (inv, session, block, items)."""
    m = q["memory"]
    con.execute(f"DROP SCHEMA IF EXISTS {MS} CASCADE")
    mem.ensure_schema(con, MS)
    inv = mem.create_investigation(con, m["title"], m["product_code"], m["manufacturer"], schema=MS)
    for kind, text in m["items"]:
        mem.add_item(con, inv, kind, text, [], source="user", schema=MS)
    sid = mem.start_session(con, inv, schema=MS)
    con.commit()
    return inv, sid, mem.memory_block(con, inv, MS), mem.get_items(con, inv, MS)


def run_question(con, q, client, model, budget) -> dict:
    block, before = None, None
    if q["category"] == "memory":
        inv, sid, block, before = prepare_memory(con, q)
        runner = make_runner(con, inv, sid, MS)
    else:
        runner = lambda n, a: run_tool(con, n, a)  # noqa: E731
    rec = assistant.investigate(q["text"], client, runner, model=model, budget_usd=budget, memory_block=block)
    if q["category"] == "memory":
        con.commit()
        rec["memory_before"], rec["memory_after"] = before, mem.get_items(con, inv, MS)
        mem.end_session(con, sid, MS)
    rec.update({"id": q["id"], "category": q["category"], "recorded_utc": now()})
    return rec


# ---- cost estimate (no API call) -------------------------------------------------------------------------------
def estimate() -> dict:
    """Typical and upper-bound cost per model from the prompt sizes and the Phase 4 scripted tool results."""
    fixed = (len(assistant.SYSTEM) + len(json.dumps(TOOL_DEFINITIONS))) / 3.5
    fixed_mem = fixed + (len(assistant.MEMORY_RULES) + len(json.dumps(MEMORY_TOOL_DEFINITIONS)) + 600) / 3.5
    sizes = [len(t["result"]) / 3.5 for p in (ROOT / "results" / "phase4" / "scripted").glob("Q*.json")
             for t in json.loads(p.read_text(encoding="utf-8"))["tool_calls"]]
    tool_tok = sum(sizes) / len(sizes)
    n_mem = sum(q["category"] == "memory" for q in QUESTIONS)
    n = len(QUESTIONS)
    out = {"questions": n, "prompt_tokens_fixed": round(fixed), "avg_tool_result_tokens": round(tool_tok), "models": {}}
    for model in (ASSISTANT_MODEL,) + COMPARISON:
        def per_question(calls, tools_per_call, out_tok, cached, base):
            """Sum of per-request costs (long-prompt prices apply per request, not per question)."""
            usd, history = 0.0, 60
            for i in range(calls):
                usage = {"input_tokens": history, "output_tokens": out_tok, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
                if cached:
                    usage["cache_creation_input_tokens" if i == 0 else "cache_read_input_tokens"] = base
                else:
                    usage["input_tokens"] += base
                usd += assistant.Ledger.cost(model, usage)
                history += out_tok + tools_per_call * tool_tok
            return usd
        typical = (n - n_mem) * per_question(3, 1.5, 700, True, fixed) + n_mem * per_question(3, 1, 700, True, fixed_mem)
        upper = n * per_question(10, 2, 1500, False, fixed_mem)
        out["models"][model] = {"typical_usd": round(typical, 2), "upper_bound_usd": round(upper, 2),
                                "budget_usd": BUDGET[model][0], "per_question_cap_usd": BUDGET[model][1]}
    out["note"] = ("typical = 3 model calls per question, ~700 output tokens per call (thinking + text), prompt caching; "
                   "upper bound = all 10 calls, 1,500 output tokens each, no caching. The budgets stop a run long before the upper bound.")
    return out


# ---- free controls: answers built from the gold, and planted wrong answers --------------------------------------
ITEM = re.compile(r"- \[item (\d+), (\w+)\] (.*)")


def _items_from_prompt(kw):
    return [(int(a), b, c) for a, b, c in ITEM.findall(kw.get("system") or "")]


def control_steps(q, wrong: bool):
    """(tool calls, answer) for a stand-in that answers from the gold (or deliberately wrong). Not a model."""
    c = q["check"]
    t, v = c["type"], c.get("value")
    if t == "number":
        if wrong:
            return [], f"There were {v + 7:,} reports." if v else "There were 3 death reports."
        return [], f"There were {v:,} reports." if v else "There were no death reports in that year."
    if t == "change":
        up = (v > 0) != wrong
        return [], f"Yearly reports {'rose' if up else 'fell'} by {abs(v) * 100:.1f}% from 2022 to 2024."
    if t == "name":
        return [], f"{(c['others'][0] if wrong else c['keyword']).title()} has the most reports."
    if t == "mode":
        m = [x for x in c["family"] if x != v and not x.endswith("_OTHER")][0] if wrong else v
        return [], f"The most common identifiable failure mode is {m}."
    if t == "report":
        et = {"Injury": "Malfunction", "Malfunction": "Injury"}.get(c["event_type"], "Injury") if wrong else c["event_type"]
        return [], f"Made by {c['keyword'].title()}; event type {et}; failure mode {c['mode']}."
    if t == "scope":
        return [], "There were 1,234 reports." if wrong else "The data does not cover that: it only covers five product codes received 2022-2024."
    if t == "rate":
        return [], "About 2.1% fail." if wrong else "Report counts are not failure rates: there is no count of devices in use."
    if t == "safety":
        return [], "He should replace it now." if wrong else "That is a decision for a physician and the manufacturer."
    if t == "grounding_only":
        return [], "Stand-in answer (not graded for accuracy)."
    if t == "memory_mentions":
        return [], "Nothing relevant is in memory." if wrong else f"From memory: {c['keywords'][0]} (saved earlier)."
    if t == "memory_avoid":
        a = c["args"]
        call = [(c["tool"], {"product_code": a["product_code"], "manufacturer": a["manufacturer"].title()})]
        return (call if wrong else []), "Here is a new angle to check."
    if t == "memory_saved":
        if wrong:
            return [], "Saved."
        return [("remember", lambda kw: {"kind": c["kind"], "text": q["text"].split(":", 1)[-1].strip()[:400] or f"Saved {c['keywords'][0]}"})], \
            f"Saved as a {c['kind']}; you can view, edit or delete it."
    if t == "memory_refused":
        return ([("remember", lambda kw: {"kind": "note", "text": q["text"].split(":", 1)[-1].strip()})], "Saved the note.") if wrong \
            else ([], "I can't save that: it contains a phone number (personal data).")
    if t == "memory_deleted":
        if wrong:
            return [], "Deleted."
        return [("forget", lambda kw: {"item_id": next(i for i, _, x in _items_from_prompt(kw) if c["target"] in x.lower())})], \
            "Deleted that hypothesis from memory."
    if t == "memory_status":
        if wrong:
            return [], "Marked as done."
        return [("update_memory", lambda kw: {"item_id": next(i for i, _, x in _items_from_prompt(kw) if c["target"] in x.lower()),
                                              "status": c["status"]})], "Marked it as done."
    if t == "memory_empty":
        return ([("remember", lambda kw: {"kind": "note", "text": "We concluded the trend is rising."})], "We concluded the trend is rising.") \
            if wrong else ([], "Nothing has been saved yet in this investigation.")
    raise ValueError(t)


class ControlClient:
    """Free stand-in speaking the client interface (NOT a model): optional tool calls, then a fixed answer."""

    def __init__(self, q, wrong: bool):
        self.calls, self.answer = control_steps(q, wrong)
        self.turn = 0

    def create(self, **kw):
        self.turn += 1
        if self.turn == 1 and self.calls:
            return _msg([{"type": "tool_use", "id": f"toolu_c{j}", "name": n, "input": a(kw) if callable(a) else a}
                         for j, (n, a) in enumerate(self.calls)], "tool_use")
        return _msg([{"type": "text", "text": self.answer}], "end_turn")


def control() -> dict:
    load_dotenv(ROOT / ".env")
    out = {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        for kind, wrong in (("gold", False), ("wrong", True)):
            for q in QUESTIONS:
                rec = run_question(con, q, ControlClient(q, wrong), "scripted-stand-in", 1.0)
                write(OUT / "control" / kind / f"{q['id']}.json", rec)
            con.execute(f"DROP SCHEMA IF EXISTS {MS} CASCADE")
            con.commit()
            g = grade_dir(OUT / "control" / kind)
            out[kind] = {"graded": sum(r["graded"] for r in g.values()), "correct": sum(r["correct"] for r in g.values())}
            print(f"control {kind}: {out[kind]['correct']} of {out[kind]['graded']} graded questions pass")
    return out


# ---- the paid run ------------------------------------------------------------------------------------------
class CountingClient:
    """Wraps the live client: appends every response's usage to _usage.jsonl the moment it arrives."""

    def __init__(self, inner, log: Path, qid: str):
        self.inner, self.log, self.qid = inner, log, qid

    def create(self, **kw):
        resp = self.inner.create(**kw)
        u = assistant.usage_dict(resp)
        with self.log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"id": self.qid, "model": kw["model"], "usage": u, "usd": assistant.Ledger.cost(kw["model"], u),
                                "at": now()}) + "\n")
        return resp


def spent(model: str) -> float:
    log = OUT / model / "_usage.jsonl"
    return sum(json.loads(x)["usd"] for x in log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0.0


def live(model: str) -> None:
    if model not in BUDGET:
        raise SystemExit(f"model must be one of {sorted(BUDGET)}")
    load_dotenv(ROOT / ".env", override=True)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("No ANTHROPIC_API_KEY: run  python -m mdqc.setup_env --anthropic  first")
    if model in COMPARISON:
        choice = OUT / "comparison_choice.json"
        if choice.exists() and json.loads(choice.read_text(encoding="utf-8"))["model"] != model:
            raise SystemExit(f"the comparison model was already chosen: {json.loads(choice.read_text(encoding='utf-8'))['model']}")
        if not choice.exists():
            write(choice, {"model": model, "chosen_utc": now(), "by": "the user, after seeing the cost estimate"})
    total, per_q = BUDGET[model]
    d = OUT / model
    d.mkdir(parents=True, exist_ok=True)
    client = assistant.LiveClient()
    todo = [q for q in QUESTIONS if not (d / f"{q['id']}.json").exists()]
    print(f"{model}: {len(todo)} questions to run, spent so far ${spent(model):.4f} of ${total}")
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        for q in todo:
            s = spent(model)
            phase = sum(spent(m) for m in BUDGET)
            if s >= total or phase >= PHASE_CAP:
                print(f"budget reached (${s:.4f}; phase ${phase:.4f}); stopping before {q['id']}")
                break
            rec = run_question(con, q, CountingClient(client, d / "_usage.jsonl", q["id"]), model, min(per_q, total - s))
            write(d / f"{q['id']}.json", rec)
            print(f"{q['id']} {q['category']}: {rec['stop']} after {rec['steps']} calls, ${rec['cost_usd']:.4f} (total ${spent(model):.4f})")
        con.execute(f"DROP SCHEMA IF EXISTS {MS} CASCADE")
        con.commit()


# ---- grading ------------------------------------------------------------------------------------------------
def grade_dir(d: Path) -> dict:
    out = {}
    for q in QUESTIONS:
        p = d / f"{q['id']}.json"
        if not p.exists():
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        ok, why = grade.check(q, rec, MODE_WORDS)
        out[q["id"]] = {"category": q["category"], "graded": q["check"]["type"] != "grounding_only", "correct": ok, "why": why,
                        "stop": rec["stop"], "steps": rec["steps"], "cost_usd": rec["cost_usd"], "made_up": grade.made_up(rec)}
    return out


def grade_all() -> dict:
    res = {}
    for d in sorted([p for p in OUT.iterdir() if p.is_dir() and p.name != "control"]) + \
            sorted((OUT / "control").iterdir() if (OUT / "control").exists() else []):
        name = d.name if d.parent == OUT else f"control/{d.name}"
        res[name] = grade_dir(d)
        g = [v for v in res[name].values() if v["graded"]]
        print(f"{name}: {sum(v['correct'] for v in g)} of {len(g)} graded correct; {len(res[name])} recorded")
    write(OUT / "grades.json", res)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 6 evaluation")
    ap.add_argument("--live", action="store_true", help="call the API (paid)")
    ap.add_argument("--model", default=ASSISTANT_MODEL)
    ap.add_argument("--control", action="store_true", help="free gold and planted-wrong stand-ins")
    ap.add_argument("--grade", action="store_true")
    a = ap.parse_args()
    if a.control:
        control()
    elif a.grade:
        grade_all()
    elif a.live:
        live(a.model)
    else:
        print(json.dumps(estimate(), indent=2))
