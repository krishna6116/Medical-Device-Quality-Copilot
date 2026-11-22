"""Replay recorded investigations for free (no API key, no network, no database).

Run:  python -m mdqc.replay            list the recorded questions
      python -m mdqc.replay Q5         show the question, the tools the model called, and its answer

The cassette holds every model response and tool result, so the replay is exactly what happened live.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASS = ROOT / "results" / "phase4" / "scripted"  # live recordings arrive in Phase 6


def show(qid: str) -> None:
    rec = json.loads((CASS / f"{qid}.json").read_text(encoding="utf-8"))
    print(f"{rec['id']} ({rec['kind']}): {rec['question']}\n")
    for t in rec["tool_calls"]:
        print(f"  tool {t['name']}({json.dumps(t['input'])}){'  -> error' if t['is_error'] else ''}")
    print(f"\n{rec['answer']}\n")
    print(f"[{rec['model']}, {rec['steps']} calls, ${rec['cost_usd']:.4f}, recorded {rec['recorded_utc']}]")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        show(sys.argv[1].upper())
    else:
        for p in sorted(CASS.glob("Q*.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            print(f"{r['id']}: {r['question']}")
