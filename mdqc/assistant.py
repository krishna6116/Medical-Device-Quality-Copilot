"""Phase 4 assistant: Claude Haiku 5.5 investigating with the project's tools.

How a turn works (the 'agent loop'): send the question and the tool list to the model; if it asks for a
tool, run it on the database and send the result back; repeat until it answers. We write this loop ourselves
(not the SDK's beta tool runner) because we need four things around every call: a cost ledger from the API's
own token counts, a hard budget stop, a recording of every exchange ('cassette') so answers can be replayed for
free in CI and the demo, and a fake model for tests.

Clients: LiveClient (real API; needs ANTHROPIC_API_KEY or an `ant auth login` profile), ReplayClient (plays a
cassette back, no network), and any object with messages.create(**kwargs) for tests.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 4000
EFFORT = "medium"
MAX_STEPS = 10

# USD per million tokens (first-party API, checked 2026-11-21). Haiku 5.5 doubles past 100K-token prompts.
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "long_input": 0.50, "long_output": 2.50, "long_from": 100_000},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
    "scripted-stand-in": {"input": 0.0, "output": 0.0},  # mdqc/scripted.py: not a model, costs nothing
}
CACHE_WRITE, CACHE_READ = 1.25, 0.10  # multiples of the input price (5-minute cache)

SYSTEM = """You are a medical device quality copilot. You help a quality engineer at a device manufacturer investigate field failures using public FDA data: MAUDE adverse-event reports received 2022-2024 and FDA recall records for five product codes (LPH uncemented hip, JWH cemented knee, MBH uncemented knee, LWP pacemaker, LZG insulin pump).

Rules:
1. Use the tools for every fact. Never state a number, date, company, report or recall from memory.
2. Every number you write must appear in a tool result (counts, shares, changes). Do not add, subtract or compute percentages yourself; tools return shares and changes. Quote shares as percentages (0.354 -> 35.4%).
3. Cite evidence: report keys as [MDR 16005019], recalls as [Z-2155-2024]. Only cite keys and recall numbers that appear in tool results.
4. Be honest about limits: a report says a device may have been involved, it is not proof of cause; report counts are not failure rates (no count of devices in use); larger companies report more; failure modes come from FDA problem terms mapped by a codebook (about 70% agreement with reference labels); a signal is a prompt to look closer, not evidence of a defect; recent months fill in late.
5. Never give medical advice or tell anyone whether to have a device removed, replaced or kept. For questions about a person's own device or treatment, say that is a decision for their physician and the manufacturer, and offer what the public data shows instead.
6. If the data cannot answer the question (other devices, dates outside 2022-2024), say so plainly.
7. Keep answers short: a direct answer first, then the key evidence as a few bullet points with citations."""

MEMORY_RULES = """This session belongs to an open investigation. Its memory (saved in earlier sessions) is shown below.
- Build on it: do not re-investigate what is ruled out unless the user asks; mention relevant saved items.
- Save with the remember tool only what the user agrees or asks to keep (a ruled-out cause with why, a hypothesis, a decision, an open question). Evidence may only cite report keys and recall numbers from tool results.
- After every save, tell the user exactly what was saved and that they can view, edit or delete it.
- Never save personal data. Use forget only when the user asks to delete something."""


@dataclass
class Ledger:
    """Cost from the API's own usage numbers. Every call is one row."""
    rows: list = field(default_factory=list)

    @staticmethod
    def cost(model: str, usage: dict) -> float:
        p = PRICES[model]
        prompt = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        long = "long_from" in p and prompt > p["long_from"]
        pin, pout = (p["long_input"], p["long_output"]) if long else (p["input"], p["output"])
        return (usage.get("input_tokens", 0) * pin + usage.get("cache_creation_input_tokens", 0) * pin * CACHE_WRITE
                + usage.get("cache_read_input_tokens", 0) * pin * CACHE_READ + usage.get("output_tokens", 0) * pout) / 1e6

    def add(self, model: str, usage: dict) -> float:
        c = self.cost(model, usage)
        self.rows.append({"model": model, **{k: usage.get(k, 0) for k in (
            "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}, "usd": c})
        return c

    @property
    def total(self) -> float:
        return sum(r["usd"] for r in self.rows)


def usage_dict(resp) -> dict:
    u = resp.usage
    return {k: int(getattr(u, k, 0) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}


class LiveClient:
    """The real API through the official SDK. Created only by scripts that say --live."""

    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic(max_retries=3)

    def create(self, **kw):
        return self.client.messages.create(**kw)


class ReplayClient:
    """Plays recorded responses back in order (no network, no cost)."""

    def __init__(self, cassette: dict):
        from anthropic.types import Message
        self.responses = [Message.model_validate(c["response"]) for c in cassette["calls"]]
        self.i = 0

    def create(self, **kw):
        if self.i >= len(self.responses):
            raise RuntimeError("cassette exhausted: the replay asked for more model calls than were recorded")
        r = self.responses[self.i]
        self.i += 1
        return r


def text_of(resp) -> str:
    return "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def investigate(question: str, client, tool_runner, model: str = MODEL, budget_usd: float = 0.25,
                history: list | None = None, memory_block: str | None = None, rules: str | None = None) -> dict:
    """Run one question through the loop. tool_runner(name, args) -> (json_text, is_error).
    Returns a record with the answer, every tool call and result, every raw response and the cost."""
    messages = list(history or []) + [{"role": "user", "content": question}]
    ledger, calls, tool_calls = Ledger(), [], []
    stop, answer = None, ""
    from mdqc.tools import MEMORY_TOOL_DEFINITIONS, TOOL_DEFINITIONS
    # Phase 5: with an open investigation, its memory is loaded into the system prompt and the memory tools are added
    system = SYSTEM if memory_block is None else "\n\n".join([SYSTEM, MEMORY_RULES, memory_block])
    if rules:  # Phase 7 safety rules; without them the prompt is exactly the Phase 4-6 one
        system += "\n\n" + rules
    tools = TOOL_DEFINITIONS if memory_block is None else TOOL_DEFINITIONS + MEMORY_TOOL_DEFINITIONS
    for step in range(MAX_STEPS):
        resp = client.create(model=model, max_tokens=MAX_TOKENS, system=system, tools=tools,
                             messages=messages, output_config={"effort": EFFORT}, cache_control={"type": "ephemeral"})
        usage = usage_dict(resp)
        ledger.add(model, usage)
        calls.append({"step": step, "stop_reason": resp.stop_reason, "usage": usage, "response": resp.to_dict()})
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})  # thinking blocks passed back unchanged
            results = []
            for b in resp.content:
                if getattr(b, "type", "") != "tool_use":
                    continue
                out, err = tool_runner(b.name, b.input)
                tool_calls.append({"step": step, "id": b.id, "name": b.name, "input": b.input, "result": out, "is_error": err})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, **({"is_error": True} if err else {})})
            messages.append({"role": "user", "content": results})
            if ledger.total > budget_usd:
                stop = "budget"
                break
            continue
        answer = text_of(resp)
        stop = {"end_turn": "answered", "max_tokens": "max_tokens", "refusal": "refusal"}.get(resp.stop_reason, resp.stop_reason)
        break
    else:
        stop = "max_steps"
    return {"question": question, "model": model, "memory_block": memory_block, "answer": answer, "stop": stop, "steps": len(calls),
            "tool_calls": tool_calls, "calls": calls, "cost_usd": round(ledger.total, 6), "ledger": ledger.rows}


# ---- grounding: what counts as a traceable number or citation (shared with the verifier's rules) --------
MDR_CITE = re.compile(r"\bMDR\s*#?\s*(\d{7,9})\b")
RECALL_CITE = re.compile(r"\bZ-\d{4}-\d{4}\b")
