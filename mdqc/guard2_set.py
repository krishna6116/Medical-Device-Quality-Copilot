"""Phase 7b test set: which recorded answer each planted sentence goes into, and where (fixed, seed 11; no API, no database)."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANTS = ROOT / "config" / "phase7b_plants.json"
MODELS = ("claude-haiku-5-5", "claude-opus-5-5")


def insert(answer: str, sentence: str, rng: random.Random) -> str:
    """Put the sentence after a randomly chosen sentence end (never in the middle of a line's markup)."""
    ends = [m.end() for m in re.finditer(r"(?<=[a-z0-9)\]])\.(?=\s)", answer)]
    at = rng.choice(ends) if ends else len(answer)
    return answer[:at] + " " + sentence + answer[at:]


def pairs() -> list[dict]:
    """40 pairs: {"id", "label", "plant", "source", "clean", "planted"}."""
    rng = random.Random(11)
    plants = json.loads(PLANTS.read_text(encoding="utf-8"))["plants"]
    todo = [(lab, s) for lab, ss in plants.items() for s in ss]
    pool = [(m, f"E{i:02d}") for m in MODELS for i in range(1, 55)]
    chosen = rng.sample(pool, len(todo))
    out = []
    for n, ((lab, s), (m, q)) in enumerate(zip(todo, chosen), 1):
        rec = json.loads((ROOT / "results" / "phase6" / m / f"{q}.json").read_text(encoding="utf-8"))
        out.append({"id": f"P{n:02d}", "label": lab, "plant": s, "source": f"{m}/{q}", "question": rec["question"],
                    "clean": rec["answer"], "planted": insert(rec["answer"], s, rng)})
    return out


def user_planted() -> list[str]:
    """The 8 planted items the user also labels: 4 advice, 2 causal, 2 identifying."""
    rng = random.Random(11)
    ps = pairs()
    return sorted(i for lab, n in (("advice", 4), ("causal_claim", 2), ("identifies_person", 2))
                  for i in rng.sample([p["id"] for p in ps if p["label"] == lab], n))


if __name__ == "__main__":
    ps = pairs()
    print(len(ps), "pairs; distinct answers", len({p["source"] for p in ps}), "; user-labelled plants", user_planted())
    for p in ps[::9]:
        i = p["planted"].index(p["plant"])
        print(p["id"], p["source"], "...", p["planted"][max(0, i - 70):i + len(p["plant"]) + 40].replace("\n", " / "))
