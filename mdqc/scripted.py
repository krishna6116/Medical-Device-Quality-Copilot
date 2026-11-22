"""A scripted stand-in for the model (NOT a language model) used to prove the Phase 4 pipeline for free.

For each pre-registered question it issues a fixed list of tool calls through the real agent loop, against
the real database, then writes a template answer from the tool results. Its runs are recorded and checked
exactly like live model runs (tools re-run, grounding, replay), so when the paid Phase 6 run happens the only
new thing is the model. Answers are labelled as scripted everywhere they are shown.
"""

from __future__ import annotations

import json

from anthropic.types import Message

MODEL_NAME = "scripted-stand-in"

SCRIPTS = {
    "Q1": [("trend", {"product_code": "LZG", "manufacturer": "Insulet", "failure_mode": "D_ADHESIVE_DISLODGED", "granularity": "year"}),
           ("count_reports", {"product_code": "LZG", "manufacturer": "Insulet", "failure_mode": "D_ADHESIVE_DISLODGED"})],
    "Q2": [("failure_modes", {"product_code": "JWH", "manufacturer": "Exactech"}),
           ("find_recalls", {"product_code": "JWH", "manufacturer": "Exactech", "date_from": "2022-01-01"})],
    "Q3": [("list_manufacturers", {"product_code": "LWP", "failure_mode": "C_BATTERY"}),
           ("signal_check", {"product_code": "LWP", "failure_mode": "C_BATTERY"})],
    "Q4": [("search_reports", {"query": "the needle did not deploy when the pod was activated", "product_code": "LZG", "limit": 5}),
           ("failure_modes", {"product_code": "LZG"})],
    "Q5": [("get_report", {"mdr_report_key": "16005019"})],
    "Q6": [("find_recalls", {"product_code": "LPH", "manufacturer": "Zimmer Biomet", "date_from": "2023-01-01", "date_to": "2023-12-31"}),
           ("signal_check", {"product_code": "LPH", "manufacturer": "Zimmer Biomet"})],
    "Q7": [("count_reports", {"product_code": "MBH", "date_from": "2024-01-01", "date_to": "2024-12-31"}),
           ("failure_modes", {"product_code": "MBH", "date_from": "2024-01-01", "date_to": "2024-12-31"})],
    "Q8": [],
    "Q9": [],
}
HEADER = "[Scripted stand-in, not a language model: template answer built from the tool results below.]"


def n(x):
    return f"{x:,}"


def p(x):
    return f"{abs(x) * 100:.1f}%"


def compose(qid: str, results: list[dict]) -> str:
    r = results
    if qid == "Q1":
        s = r[0]["series"]
        trend = ", ".join(f"{x['period']}: {n(x['reports'])}" for x in s)
        mal = next((x for x in r[1]["by_event_type"] if x["event_type"] == "Malfunction"), None)
        ch = r[0].get("first_to_last_change", 0)
        return (f"{HEADER}\nInsulet reports with the failure mode 'adhesive / dislodged' by year: {trend} "
                f"({'down' if ch < 0 else 'up'} {p(ch)} from first to last year). {n(r[1]['reports'])} reports in total"
                + (f", {p(mal['share'])} malfunctions." if mal else ".") + " Report counts are not failure rates.")
    if qid == "Q2":
        modes = "; ".join(f"{m['failure_mode']} {n(m['reports'])} ({p(m['share'])})" for m in r[0]["modes"][:3])
        rec = ", ".join(f"[{x['recall_number']}] started {x['started']}" for x in r[1]["recalls"][:3])
        return (f"{HEADER}\nExactech JWH reports ({n(r[0]['reports'])}): top failure modes {modes}. Recalls from 2022: "
                f"{n(r[1]['recall_records'])} recall records in {n(r[1]['recall_events'])} recall events, e.g. {rec}.")
    if qid == "Q3":
        top = "; ".join(f"{m['manufacturer']} {n(m['reports'])} ({p(m['share'])})" for m in r[0]["manufacturers"][:3])
        sig = ", ".join(f"{x['manufacturer']} {x['month']} ({n(x['reports'])} reports)" for x in r[1]["signals"][:3])
        return (f"{HEADER}\nPacemaker battery-depletion reports by company: {top}. Early-warning signals: "
                f"{n(r[1]['signals_total'])}" + (f", most recent {sig}." if sig else ".") + " A signal is a prompt to look, not proof.")
    if qid == "Q4":
        hits = "; ".join(f"[MDR {x['mdr_report_key']}] similarity {x['similarity']}, {x['failure_mode']}" for x in r[0]["results"][:3])
        cann = next((m for m in r[1]["modes"] if m["failure_mode"] == "D_CANNULA_INSERTION"), None)
        return (f"{HEADER}\nMost similar reports: {hits}. Cannula/insertion failures are "
                + (f"{n(cann['reports'])} of {n(r[1]['reports'])} insulin pump reports ({p(cann['share'])})." if cann else "not found."))
    if qid == "Q5":
        x = r[0]
        rec = "; ".join(f"[{y['recall_number']}] {y['link']} link" for y in x["recalls_within_a_year"]) or "none within a year"
        return (f"{HEADER}\n[MDR {x['mdr_report_key']}] {x['device']} by {x['manufacturer']}, received {x['date_received']}, "
                f"{x['event_type']}, failure mode {x['failure_mode']}. Narrative: {x['narrative'][:200]} Linked recalls: {rec}.")
    if qid == "Q6":
        rec = "; ".join(f"[{x['recall_number']}] started {x['started']}" for x in r[0]["recalls"][:5]) or "none"
        sig = ", ".join(f"{x['month']} {x['failure_mode']}" for x in r[1]["signals"][:6]) or "none"
        return (f"{HEADER}\nZimmer Biomet LPH recalls started in 2023: {rec}. Signals for Zimmer Biomet LPH: {sig}. "
                "Compare the signal months with the recall start dates; a signal is a prompt to look, not proof.")
    if qid == "Q7":
        deaths = next((x["reports"] for x in r[0]["by_event_type"] if x["event_type"] == "Death"), 0)
        modes = "; ".join(f"{m['failure_mode']} {n(m['reports'])} ({p(m['share'])})" for m in r[1]["modes"][:3])
        return f"{HEADER}\nMBH reports received in 2024: {n(r[0]['reports'])}, of which deaths: {deaths}. Top failure modes: {modes}."
    if qid == "Q8":
        return (f"{HEADER}\nI can't advise on whether a specific person's pacemaker should be replaced; that is a decision for "
                "his cardiologist (physician) together with the manufacturer. I can show what the public FDA reports say "
                "about Boston Scientific pacemaker battery reports, which may help prepare questions for that conversation.")
    if qid == "Q9":
        return (f"{HEADER}\nThe project's data does not cover infusion pumps or Baxter: it only covers five product codes "
                "(LPH, JWH, MBH, LWP, LZG), so I cannot answer this from the data.")
    raise KeyError(qid)


def _msg(content, stop):
    return Message.model_validate({"id": "msg_scripted", "type": "message", "role": "assistant", "model": MODEL_NAME,
                                   "content": content, "stop_reason": stop, "stop_sequence": None,
                                   "usage": {"input_tokens": 0, "output_tokens": 0}})


class ScriptedClient:
    """Speaks the same interface as the real client: first asks for the scripted tools, then answers."""

    def __init__(self, qid: str):
        self.qid, self.turn = qid, 0

    def create(self, **kw):
        self.turn += 1
        calls = SCRIPTS[self.qid]
        if self.turn == 1 and calls:
            return _msg([{"type": "tool_use", "id": f"toolu_{self.qid}_{i}", "name": name, "input": args}
                         for i, (name, args) in enumerate(calls)], "tool_use")
        last = kw["messages"][-1]["content"] if calls else []
        results = [json.loads(b["content"]) for b in last] if calls else []
        return _msg([{"type": "text", "text": compose(self.qid, results)}], "end_turn")


class StepClient:
    """Multi-step scripted stand-in (Phase 5 scenarios). steps: a list of ("tools", [(name, args), ...]) or
    ("answer", fn). args may be a function of the tool results so far (e.g. cite a recall returned earlier);
    fn(results) builds the final text. Still NOT a model; answers carry the scripted header."""

    def __init__(self, steps):
        self.steps, self.i, self.results = steps, 0, []

    def create(self, **kw):
        if self.i > 0 and kw["messages"][-1]["role"] == "user" and isinstance(kw["messages"][-1]["content"], list):
            self.results += [json.loads(b["content"]) for b in kw["messages"][-1]["content"]]
        kind, payload = self.steps[self.i]
        self.i += 1
        if kind == "tools":
            calls = [(n, a(self.results) if callable(a) else a) for n, a in payload]
            return _msg([{"type": "tool_use", "id": f"toolu_s{self.i}_{j}", "name": n, "input": a}
                         for j, (n, a) in enumerate(calls)], "tool_use")
        return _msg([{"type": "text", "text": HEADER + "\n" + payload(self.results)}], "end_turn")
