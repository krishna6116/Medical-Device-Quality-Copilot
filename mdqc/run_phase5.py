"""Phase 5 scenarios: memory across sessions, edits, deletions, guardrails (free; scripted stand-in, no model).

Run:  python -m mdqc.run_phase5     -> results/phase5/scenarios.json (+ exports), database schema memory_scenarios

The scenarios (config/phase5_criteria.json) run in their own schema `memory_scenarios`, rebuilt on every run,
so they never touch the user's real investigations in schema `memory`. Every session goes through the real
agent loop: the investigation's memory block is loaded at session start, memory tools write through the
real API, and user actions (edit, delete) go through the same API the app and CLI use.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from mdqc import assistant
from mdqc import memory as mem
from mdqc.scripted import MODEL_NAME, StepClient
from mdqc.tools import make_runner

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "phase5"
S = "memory_scenarios"


def create(con, log, scenario, title, code, maker):
    inv = mem.create_investigation(con, title, code, maker, schema=S)
    log.append({"type": "create", "scenario": scenario, "investigation_id": inv, "title": title, "product_code": code, "manufacturer": maker})
    return inv


def session(con, log, scenario, inv, question, steps):
    """One session: start, load memory, run the scripted turn, record everything."""
    sid = mem.start_session(con, inv, schema=S)
    block = mem.memory_block(con, inv, S)
    rec = assistant.investigate(question, StepClient(steps), make_runner(con, inv, sid, S), model=MODEL_NAME, memory_block=block)
    mem.end_session(con, sid, S)
    log.append({"type": "session", "scenario": scenario, "investigation_id": inv, "session_id": sid, "question": question,
                "memory_block": block, "tool_calls": rec["tool_calls"], "answer": rec["answer"], "calls": rec["calls"]})
    return rec


def user(con, log, scenario, action, **kw):
    """A user action through the same API the app and CLI use."""
    fn = {"edit": mem.edit_item, "delete": mem.delete_item, "delete_investigation": mem.delete_investigation}[action]
    out = fn(con, **kw, schema=S) if action != "edit" else fn(con, kw["item_id"], kw.get("text"), kw.get("status"), None, "user", S)
    log.append({"type": "user", "scenario": scenario, "action": action, "args": kw, "result": out})
    return out


def saved(results):
    return [r for r in results if isinstance(r, dict) and r.get("saved")]


def confirmations(results):
    return " ".join(r["confirmation"] for r in saved(results)) or "Nothing was saved."


def main() -> dict:
    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    log, exports = [], {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        con.execute(f"DROP SCHEMA IF EXISTS {S} CASCADE")
        mem.ensure_schema(con, S)

        # ---- S_A: Insulet pods, three sessions, user deletes the hypothesis between sessions 2 and 3 ----
        a = create(con, log, "S_A", "Insulet pod adhesive failures", "LZG", "INSULET")
        session(con, log, "S_A", a, "Are Insulet pod adhesive failures rising? Save what we conclude.", [
            ("tools", [("trend", {"product_code": "LZG", "manufacturer": "Insulet", "failure_mode": "D_ADHESIVE_DISLODGED", "granularity": "year"})]),
            ("tools", [("remember", lambda r: {"kind": "ruled_out", "text": "Rising adhesive failures ruled out for 2022-2024: yearly reports "
                        + " -> ".join(f"{x['reports']:,}" for x in r[0]["series"]) + f" (change {r[0]['first_to_last_change'] * 100:.1f}%)."}),
                       ("remember", {"kind": "hypothesis", "text": "Dislodged pods may relate to wear time over 48 hours; check the narratives."}),
                       ("remember", {"kind": "open_question", "text": "Do cannula insertion failures rise in the same months as dislodged pods?"})]),
            ("answer", lambda r: "Adhesive failures are not rising. " + confirmations(r))])
        session(con, log, "S_A", a, "What have we ruled out so far?", [
            ("tools", [("recall", {})]),
            ("answer", lambda r: "From this investigation's memory: " + " ".join(
                line for line in r[0]["memory"].splitlines() if line.startswith("- ") and "Rising adhesive" in line))])
        hyp = next(t for e in log if e["type"] == "session" for t in e["tool_calls"]
                   if t["name"] == "remember" and json.loads(t["result"]).get("kind") == "hypothesis")
        user(con, log, "S_A", "delete", item_id=json.loads(hyp["result"])["item_id"])
        session(con, log, "S_A", a, "Remind me of our open hypotheses.", [
            ("tools", [("recall", {})]),
            ("answer", lambda r: "Hypotheses in memory: " + ("none." if "Hypotheses:" not in r[0]["memory"] else "see memory."))])

        # ---- S_B: Exactech knees: real evidence accepted, invented evidence and phone number refused, user edits ----
        b = create(con, log, "S_B", "Exactech knee insert wear", "JWH", "EXACTECH")
        key = con.execute("""SELECT r.mdr_report_key FROM core.fact_report r JOIN core.dim_manufacturer m USING (manufacturer_id)
            JOIN analytics.report_failure_mode f USING (mdr_report_key) WHERE r.product_code = 'JWH'
            AND m.parent_company = 'EXACTECH' AND f.mode = 'O_WEAR' ORDER BY r.mdr_report_key LIMIT 1""").fetchone()[0]
        session(con, log, "S_B", b, "Which Exactech knee recalls should we focus on? Save our decision.", [
            ("tools", [("find_recalls", {"product_code": "JWH", "manufacturer": "Exactech", "date_from": "2022-01-01"})]),
            ("tools", [("remember", lambda r: {"kind": "decision", "text": "Focus the review on the most recent Exactech JWH recall.",
                                               "evidence": [r[0]["recalls"][0]["recall_number"]]}),
                       ("remember", {"kind": "ruled_out", "text": "Packaging damage ruled out as the cause in the reviewed wear report.",
                                     "evidence": [f"MDR {key}"]}),
                       ("remember", {"kind": "note", "text": "Example report to compare against.", "evidence": ["MDR 99999999"]}),
                       ("remember", {"kind": "note", "text": "Ask the surgeon on 555-123-4567 about the revision."})]),
            ("answer", lambda r: confirmations(r) + f" Refused: {sum(1 for x in r if isinstance(x, dict) and 'error' in x)} save(s) (invented evidence or personal data).")])
        dec = next(json.loads(t["result"]) for e in log if e["type"] == "session" and e["scenario"] == "S_B"
                   for t in e["tool_calls"] if t["name"] == "remember" and not t["is_error"] and json.loads(t["result"])["kind"] == "decision")
        user(con, log, "S_B", "edit", item_id=dec["item_id"], text="Focus the review on the most recent Exactech JWH recall and its lot ranges.", status="confirmed")
        exports["S_B_json"] = mem.export_json(con, b, S)
        exports["S_B_md"] = mem.export_markdown(con, b, S)

        # ---- S_C: two investigations stay apart; cross-investigation forget refused; deleting one removes all of it ----
        c1 = create(con, log, "S_C", "Boston Scientific pacemaker battery", "LWP", "BOSTON SCIENTIFIC")
        c2 = create(con, log, "S_C", "Abbott pacemaker battery", "LWP", "ABBOTT")
        session(con, log, "S_C", c1, "Note the battery hypothesis for Boston Scientific.", [
            ("tools", [("remember", {"kind": "hypothesis", "text": "Boston Scientific battery reports may follow one device family."})]),
            ("answer", confirmations)])
        c1_item = json.loads(log[-1]["tool_calls"][0]["result"])["item_id"]
        session(con, log, "S_C", c2, "Note the Abbott question, then delete item " + str(c1_item) + ".", [
            ("tools", [("remember", {"kind": "open_question", "text": "Are Abbott battery reports concentrated in 2022?"}),
                       ("forget", {"item_id": c1_item})]),
            ("answer", lambda r: confirmations(r) + " " + next((x["error"] for x in r if isinstance(x, dict) and "error" in x), ""))])
        user(con, log, "S_C", "delete_investigation", inv=c1)
        session(con, log, "S_C", c2, "What is in this investigation's memory?", [
            ("tools", [("recall", {})]), ("answer", lambda r: r[0]["memory"])])

    for k, v in exports.items():
        if k.endswith("_md"):
            (OUT / "export_S_B.md").write_text(v, encoding="utf-8", newline="\n")
    out = {"schema": S, "model": MODEL_NAME, "log": log, "export_S_B": exports["S_B_json"]}
    (OUT / "scenarios.json").write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{sum(e['type'] == 'session' for e in log)} sessions, {sum(e['type'] == 'user' for e in log)} user actions -> {OUT}")
    for e in log:
        if e["type"] == "session":
            print(f"  {e['scenario']} inv {e['investigation_id']}: {e['question'][:60]} -> {e['answer'].splitlines()[-1][:150]}")
    return out


if __name__ == "__main__":
    main()
