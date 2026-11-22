"""Phase 4 tests with a fake model (free, no network): the agent loop, cost ledger, budget stop, replay,
grounding rules and tool argument checks. The committed cassettes are checked offline if present."""

import json
from pathlib import Path

import pytest
from anthropic.types import Message

from mdqc import assistant
from mdqc import verify_phase4 as v4
from mdqc.tools import TOOL_DEFINITIONS, ToolError, _code, _date

ROOT = Path(__file__).resolve().parents[1]


def msg(content, stop, usage=(1200, 300)):
    return Message.model_validate({"id": "msg_fake", "type": "message", "role": "assistant", "model": assistant.MODEL,
                                   "content": content, "stop_reason": stop, "stop_sequence": None,
                                   "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}})


class FakeClient:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def create(self, **kw):
        self.requests.append(kw)
        return self.responses.pop(0)


TOOL_RESULT = json.dumps({"filters": {"product_code": "LZG"}, "reports": 15522,
                          "by_event_type": [{"event_type": "Malfunction", "reports": 15273, "share": 0.984}]})


def fake_conversation():
    return [msg([{"type": "tool_use", "id": "tu_1", "name": "count_reports", "input": {"product_code": "LZG"}}], "tool_use"),
            msg([{"type": "text", "text": "There were 15,522 reports; 98.4% were malfunctions [MDR 16005019]."}], "end_turn")]


def test_loop_runs_tools_and_records_everything():
    client = FakeClient(fake_conversation())
    seen = []
    rec = assistant.investigate("How many?", client, lambda n, a: (seen.append((n, a)) or TOOL_RESULT, False))
    assert rec["stop"] == "answered" and rec["steps"] == 2 and seen == [("count_reports", {"product_code": "LZG"})]
    assert rec["answer"].startswith("There were 15,522")
    second = client.requests[1]["messages"]
    assert second[-1]["content"][0]["tool_use_id"] == "tu_1"  # tool result sent back with the right id
    assert client.requests[0]["tools"] == TOOL_DEFINITIONS and client.requests[0]["model"] == "claude-haiku-5-5"


def test_ledger_matches_independent_formula():
    usage = {"input_tokens": 1200, "output_tokens": 300, "cache_creation_input_tokens": 3000, "cache_read_input_tokens": 9000}
    assert assistant.Ledger.cost("claude-haiku-5-5", usage) == pytest.approx(v4.cost("claude-haiku-5-5", usage))
    long = dict(usage, input_tokens=120_000)
    assert assistant.Ledger.cost("claude-haiku-5-5", long) > 5 * assistant.Ledger.cost("claude-haiku-5-5", usage)


def test_budget_stop():
    loop = [msg([{"type": "tool_use", "id": f"t{i}", "name": "count_reports", "input": {}}], "tool_use",
                usage=(2_000_000, 0)) for i in range(5)]
    rec = assistant.investigate("x", FakeClient(loop), lambda n, a: (TOOL_RESULT, False), budget_usd=0.25)
    # 2M-token prompts use the >100K price ($0.50/M): one call already costs $1.00, so the loop stops after it
    assert rec["stop"] == "budget" and rec["steps"] == 1 and rec["cost_usd"] > 0.25


def test_replay_reproduces_the_run():
    rec = assistant.investigate("How many?", FakeClient(fake_conversation()), lambda n, a: (TOOL_RESULT, False))
    rec = json.loads(json.dumps(rec, default=str))
    recorded = iter([t["result"] for t in rec["tool_calls"]])
    again = assistant.investigate("How many?", assistant.ReplayClient(rec), lambda n, a: (next(recorded), False))
    assert again["answer"] == rec["answer"] and [t["input"] for t in again["tool_calls"]] == [t["input"] for t in rec["tool_calls"]]
    calls, answer = v4.replay(rec)
    assert answer == rec["answer"] and calls == [("count_reports", json.dumps({"product_code": "LZG"}, sort_keys=True))]


def test_grounding_rules():
    tools = [TOOL_RESULT, json.dumps({"results": [{"mdr_report_key": "16005019", "similarity": 0.82}]}),
             json.dumps({"recalls": [{"recall_number": "Z-2155-2024"}], "first_to_last_change": -0.044})]
    g = v4.grounding("15,522 reports, 98.4% malfunctions, down 4.4% [MDR 16005019] [Z-2155-2024]; 3 companies; in 2023-Q2.", tools)
    assert all(ok for _, _, ok in g["citations"]) and len(g["citations"]) == 2
    assert all(ok for _, ok in g["numbers"]) and [s for s, _ in g["numbers"]] == ["15,522", "98.4%", "4.4%"]
    bad = v4.grounding("About 16,000 reports, 97% malfunctions [MDR 12345678].", tools)
    assert not any(ok for _, ok in bad["numbers"]) and not bad["citations"][0][2]


def test_tool_argument_checks():
    with pytest.raises(ToolError):
        _code("FRN")
    assert _code("lzg") == "LZG" and _date("2030-01-01", "2022-01-01") == "2024-12-31"
    with pytest.raises(ToolError):
        _date("01/02/2023", "2022-01-01")


def test_tool_schemas_are_strict_objects():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert len(names) == len(set(names)) == 8
    assert all(t["input_schema"]["type"] == "object" and t["input_schema"]["additionalProperties"] is False for t in TOOL_DEFINITIONS)


def test_thinking_blocks_passed_back_unchanged():
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    first = msg([thinking, {"type": "tool_use", "id": "tu_9", "name": "count_reports", "input": {}}], "tool_use")
    client = FakeClient([first, msg([{"type": "text", "text": "done"}], "end_turn")])
    assistant.investigate("q", client, lambda n, a: (TOOL_RESULT, False))
    sent = client.requests[1]["messages"][1]["content"]
    assert sent[0].type == "thinking" and sent[0].signature == "sig-abc"  # same block object, untouched


@pytest.mark.parametrize("stop,expected", [("max_tokens", "max_tokens"), ("refusal", "refusal")])
def test_stop_reasons(stop, expected):
    rec = assistant.investigate("q", FakeClient([msg([{"type": "text", "text": "partial"}], stop)]), lambda n, a: (TOOL_RESULT, False))
    assert rec["stop"] == expected and rec["steps"] == 1


def test_steps_are_limited():
    loop = [msg([{"type": "tool_use", "id": f"t{i}", "name": "count_reports", "input": {}}], "tool_use", usage=(10, 10))
            for i in range(assistant.MAX_STEPS + 2)]
    rec = assistant.investigate("q", FakeClient(loop), lambda n, a: (TOOL_RESULT, False))
    assert rec["stop"] == "max_steps" and rec["steps"] == assistant.MAX_STEPS


def test_scripted_stand_in_is_labelled():
    from mdqc.scripted import HEADER, compose
    assert compose("Q9", []).startswith(HEADER) and "not a language model" in HEADER


@pytest.mark.skipif(not any((ROOT / "results" / "phase4" / "scripted").glob("Q*.json")), reason="no scripted recordings yet")
def test_committed_scripted_recordings_offline():
    assert v4.main_scripted(offline=True, evidence=None) == 0


def test_tool_input_validation_without_database():
    """Checks that run before any query (re-check 2026-11-22): unknown arguments, bad limits, recall dates,
    failure modes from another device family."""
    from mdqc.tools import _limit, _mode, run_tool

    class NoDB:  # any query would fail loudly
        def execute(self, *a, **k):
            raise AssertionError("no query expected")

        def rollback(self):
            pass

    out, err = run_tool(NoDB(), "count_reports", {"product_code": "LZG", "bogus": 1})
    assert err and "unknown argument" in out
    out, err = run_tool(NoDB(), "no_such_tool", {})
    assert err and "unknown tool" in out
    assert _limit("7") == 7 and _limit(99) == 10 and _limit(None) == 5
    with pytest.raises(ToolError):
        _limit("five")
    assert _date("2015-03-01", "1976-01-01", lo="1976-01-01", hi="2026-12-31") == "2015-03-01"  # recalls: not clamped to 2022
    assert _mode("c_battery", "LWP") == "C_BATTERY"
    with pytest.raises(ToolError):
        _mode("O_INFECTION", "LWP")


def test_tool_never_raises_on_unexpected_errors():
    from mdqc.tools import run_tool

    class BrokenDB:
        rolled_back = False

        def execute(self, *a, **k):
            raise RuntimeError("database went away")

        def rollback(self):
            BrokenDB.rolled_back = True

    out, err = run_tool(BrokenDB(), "signal_check", {"product_code": "LWP"})
    assert err and "failed (RuntimeError)" in out and BrokenDB.rolled_back
