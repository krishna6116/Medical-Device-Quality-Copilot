"""Run the pre-registered Phase 4 investigations on Claude Haiku 5.5 and record them.

Run:  python -m mdqc.run_phase4 --scripted show the pipeline working for free (scripted stand-in, not a model)
      python -m mdqc.run_phase4            show the plan and cost estimate only (no API call)
      python -m mdqc.run_phase4 --live     call the API (needs ANTHROPIC_API_KEY in .env; set a Console spending cap first)

Each question runs once. A question that already has a cassette in results/phase4/cassettes/ is skipped, so
nothing is ever paid for twice and no answer is re-rolled to look better. The whole run stops if spending
passes the $1.00 Phase 4 budget (each question is also capped at $0.25).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from mdqc import assistant
from mdqc.tools import TOOL_DEFINITIONS, run_tool

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "phase4"
CASS = OUT / "cassettes"
QUESTIONS = json.loads((ROOT / "config" / "phase4_questions.json").read_text(encoding="utf-8"))["questions"]
BUDGET_TOTAL, BUDGET_QUESTION = 1.00, 0.25


def estimate() -> dict:
    """Upper-bound estimate: every question uses all 10 calls with a growing history."""
    fixed = (len(assistant.SYSTEM) + len(json.dumps(TOOL_DEFINITIONS))) / 4  # ~4 characters per token
    per_call_in = fixed + 6000  # plus up to ~6k tokens of question, tool results and history
    calls = len(QUESTIONS) * assistant.MAX_STEPS
    usage = {"input_tokens": int(calls * per_call_in), "output_tokens": calls * 1500}
    return {"calls_max": calls, "input_tokens_max": usage["input_tokens"], "output_tokens_max": usage["output_tokens"],
            "usd_max": round(assistant.Ledger.cost(assistant.MODEL, usage), 3),
            "note": "upper bound; typical questions need 2-5 calls and prompt caching cuts repeated input to 10% of the price"}


def scripted() -> dict:
    """Free proof of the pipeline (amendment, config/phase4_amendment.json): the scripted stand-in drives the
    real loop and tools; recordings go to results/phase4/scripted/."""
    from mdqc.scripted import ScriptedClient, MODEL_NAME
    load_dotenv(ROOT / ".env")
    out = OUT / "scripted"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        for q in QUESTIONS:
            rec = assistant.investigate(q["text"], ScriptedClient(q["id"]), lambda n, a: run_tool(con, n, a), model=MODEL_NAME)
            rec.update({"id": q["id"], "kind": q["kind"], "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
            (out / f"{q['id']}.json").write_text(json.dumps(rec, indent=1, default=str, ensure_ascii=False) + "\n",
                                                 encoding="utf-8", newline="\n")
            rows.append({"id": q["id"], "kind": q["kind"], "stop": rec["stop"], "steps": rec["steps"],
                         "tools": [t["name"] for t in rec["tool_calls"]], "tool_errors": sum(t["is_error"] for t in rec["tool_calls"]),
                         "cost_usd": rec["cost_usd"]})
            print(f"{q['id']}: {rec['stop']}, tools {rows[-1]['tools']}, errors {rows[-1]['tool_errors']}")
    summary = {"mode": "scripted stand-in (not a model)", "live_estimate_for_phase6": estimate(), "questions": rows,
               "total_cost_usd": sum(r["cost_usd"] for r in rows)}
    (OUT / "scripted_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    return summary


def main(live: bool) -> dict:
    load_dotenv(ROOT / ".env")
    CASS.mkdir(parents=True, exist_ok=True)
    est = estimate()
    print(f"model {assistant.MODEL}; {len(QUESTIONS)} questions; upper-bound cost ${est['usd_max']} "
          f"(budget ${BUDGET_TOTAL}); {est['note']}")
    todo = [q for q in QUESTIONS if not (CASS / f"{q['id']}.json").exists()]
    print(f"to run: {[q['id'] for q in todo] or 'nothing (all recorded)'}")
    if not live:
        print("dry run: add --live to call the API")
        return est
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("No ANTHROPIC_API_KEY: run  python -m mdqc.setup_env --anthropic  first")
    client = assistant.LiveClient()
    spent = sum(json.loads(p.read_text(encoding="utf-8"))["cost_usd"] for p in CASS.glob("Q*.json"))
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        for q in todo:
            if spent >= BUDGET_TOTAL:
                print(f"budget reached (${spent:.4f}); stopping before {q['id']}")
                break
            rec = assistant.investigate(q["text"], client, lambda n, a: run_tool(con, n, a),
                                        budget_usd=min(BUDGET_QUESTION, BUDGET_TOTAL - spent))
            rec.update({"id": q["id"], "kind": q["kind"], "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
            (CASS / f"{q['id']}.json").write_text(json.dumps(rec, indent=1, default=str, ensure_ascii=False) + "\n",
                                                   encoding="utf-8", newline="\n")
            spent += rec["cost_usd"]
            print(f"{q['id']}: {rec['stop']} after {rec['steps']} calls, tools {[t['name'] for t in rec['tool_calls']]}, "
                  f"${rec['cost_usd']:.4f} (total ${spent:.4f})")
    summary = {"model": assistant.MODEL, "estimate": est, "questions": []}
    for p in sorted(CASS.glob("Q*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        summary["questions"].append({"id": r["id"], "kind": r["kind"], "stop": r["stop"], "steps": r["steps"],
                                     "tools": [t["name"] for t in r["tool_calls"]], "cost_usd": r["cost_usd"],
                                     "tokens_in": sum(x["usage"]["input_tokens"] + x["usage"]["cache_read_input_tokens"]
                                                      + x["usage"]["cache_creation_input_tokens"] for x in r["calls"]),
                                     "tokens_out": sum(x["usage"]["output_tokens"] for x in r["calls"])})
    summary["total_cost_usd"] = round(sum(q["cost_usd"] for q in summary["questions"]), 6)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"total ${summary['total_cost_usd']}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 4 investigations")
    ap.add_argument("--live", action="store_true", help="actually call the API (costs money; reserved for the Phase 6 paid run)")
    ap.add_argument("--scripted", action="store_true", help="free pipeline proof with the scripted stand-in")
    a = ap.parse_args()
    scripted() if a.scripted else main(a.live)
