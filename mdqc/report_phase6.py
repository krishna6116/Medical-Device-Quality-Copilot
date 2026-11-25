"""Phase 6 report: docs/EVALUATION.md and results/phase6/summary.json, generated from the graded recordings.

Run:  python -m mdqc.report_phase6 [--check]     (--check: fail if the committed doc or summary is stale)

Every number comes from results/phase6/grades.json (python -m mdqc.run_phase6 --grade), the recordings and the
verifier's evidence. Statistics follow config/phase6_criteria.json: Wilson 95% intervals, a paired bootstrap of
questions (10,000 resamples, seed 0) for the difference between models, and an exact McNemar test.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "phase6"
DOC = ROOT / "docs" / "EVALUATION.md"
EVAL = json.loads((ROOT / "config" / "phase6_eval_set.json").read_text(encoding="utf-8"))["questions"]
CRIT = json.loads((ROOT / "config" / "phase6_criteria.json").read_text(encoding="utf-8"))
ASSISTANT = "claude-haiku-5-5"
CATS = ["count", "trend", "company", "failure_mode", "recall", "report", "scope", "safety", "memory", "phase4"]


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def paired(a: list[int], b: list[int]) -> dict:
    """b minus a: point difference, 95% paired bootstrap interval, exact McNemar p-value."""
    a, b = np.array(a), np.array(b)
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(a), size=(10_000, len(a)))
    diffs = (b[idx].mean(axis=1) - a[idx].mean(axis=1))
    only_b, only_a = int(((b == 1) & (a == 0)).sum()), int(((a == 1) & (b == 0)).sum())
    p = binomtest(only_b, only_b + only_a, 0.5).pvalue if only_a + only_b else 1.0
    return {"difference": float(b.mean() - a.mean()), "ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
            "only_comparison_correct": only_b, "only_assistant_correct": only_a, "mcnemar_p": float(p)}


def summarise() -> dict:
    grades = json.loads((RES / "grades.json").read_text(encoding="utf-8"))
    models = [m for m in grades if not m.startswith("control/")]
    order = [q["id"] for q in EVAL if q["check"]["type"] != "grounding_only"]
    out = {"questions": len(EVAL), "graded": len(order), "models": {}, "controls": {}}
    for name in [m for m in grades if m.startswith("control/")]:
        g = grades[name]
        out["controls"][name] = {"correct": sum(g[i]["correct"] for i in order if i in g), "of": sum(i in g for i in order)}
    for m in models:
        g = grades[m]
        complete = all(q["id"] in g for q in EVAL)
        k = sum(g[i]["correct"] for i in order if i in g)
        cats = {}
        for c in CATS:
            ids = [q["id"] for q in EVAL if q["category"] == c and q["check"]["type"] != "grounding_only" and q["id"] in g]
            kc = sum(g[i]["correct"] for i in ids)
            cats[c] = {"correct": kc, "of": len(ids), "ci95": list(wilson(kc, len(ids)))}
        cost = sum(v["cost_usd"] for v in g.values())
        usage = RES / m / "_usage.jsonl"
        spent = sum(json.loads(x)["usd"] for x in usage.read_text(encoding="utf-8").splitlines()) if usage.exists() else cost
        mu = [v["made_up"] for v in g.values()]
        out["models"][m] = {
            "complete": complete, "recorded": len(g), "correct": k, "of": len(order), "accuracy": k / len(order),
            "ci95": list(wilson(k, len(order))), "categories": cats,
            "stops": {s: sum(v["stop"] == s for v in g.values()) for s in sorted({v["stop"] for v in g.values()})},
            "answers_with_made_up_facts": sum(x["count"] > 0 for x in mu), "made_up_facts": sum(x["count"] for x in mu),
            "numbers_checked": sum(x["numbers_checked"] for x in mu), "citations_checked": sum(x["citations_checked"] for x in mu),
            "cost_usd": round(cost, 6), "spent_usd_incl_failed_attempts": round(spent, 6),
            "usd_per_question": round(cost / len(g), 6) if g else None, "usd_per_correct": round(cost / k, 6) if k else None,
            "wrong": {i: g[i]["why"] for i in order if i in g and not g[i]["correct"]}}
    comp = [m for m in models if m != ASSISTANT and out["models"][m]["complete"]]
    if ASSISTANT in out["models"] and out["models"][ASSISTANT]["complete"] and comp:
        h, s = grades[ASSISTANT], grades[comp[0]]
        pr = paired([int(h[i]["correct"]) for i in order], [int(s[i]["correct"]) for i in order])
        better = pr["ci95"][0] > 0 and pr["difference"] >= 0.05
        extra = (out["models"][comp[0]]["cost_usd"] - out["models"][ASSISTANT]["cost_usd"])
        pr["extra_usd_per_extra_correct"] = round(extra / (pr["difference"] * len(order)), 4) if pr["difference"] > 0 else None
        out["comparison"] = {"model": comp[0], **pr,
                             "decision": (f"Switch to {comp[0]}: its gain is at least 5 points and its 95% interval is above 0."
                                          if better else f"Keep {ASSISTANT}: the comparison model's gain does not meet the rule "
                                          "(95% interval above 0 and at least 5 points).")}
    ev = RES / "phase4_live.json"
    if ev.exists():
        e = json.loads(ev.read_text(encoding="utf-8"))
        out["phase4_live"] = {c["id"]: {"pass": c["pass"], "detail": {k: v for k, v in c["detail"].items() if k != "per_question"}}
                              for c in e["checks"] if c["id"] in ("A2", "A3")}
    hr = RES / "hand_review.json"
    if hr.exists():
        out["hand_review"] = json.loads(hr.read_text(encoding="utf-8"))
    v = RES / "verify_phase6.json"
    if v.exists():
        out["verification"] = json.loads(v.read_text(encoding="utf-8"))
    return out


def pct(x):
    return f"{100 * x:.1f}%"


def table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def render(s: dict) -> str:
    L = ["# Phase 6: evaluation of the assistant (the project's only paid run)", "",
         "_Generated by `python -m mdqc.report_phase6` from `results/phase6/`. Do not edit by hand._", "",
         "**What this measures:** how often the investigation assistant answers correctly, whether its facts come from the "
         "data, whether it stays safe and in scope, how well it uses investigation memory, and what that costs, on "
         f"{s['questions']} questions fixed in advance ({s['graded']} graded; the other 5 are Phase 4 questions with no single "
         "right answer, judged only on grounding).", "",
         "**Pre-registration:** the questions, correct answers, grading rules, decision rule and scorecard were committed "
         "(`3e490ff`, files `config/phase6_eval_set.json`, `phase6_criteria.json`, `phase6_scorecard.json`) before any grader, "
         "runner or model answer existed. Every answer is recorded in `results/phase6/<model>/` and was run once.", ""]
    L += ["## Results by model", ""]
    rows = []
    for m, r in s["models"].items():
        rows.append([m, f"{r['correct']}/{r['of']}" + ("" if r["complete"] else f" (only {r['recorded']} of {s['questions']} recorded)"),
                     f"{pct(r['accuracy'])} ({pct(r['ci95'][0])} to {pct(r['ci95'][1])})",
                     f"{r['answers_with_made_up_facts']} answers ({r['made_up_facts']} facts)", f"${r['cost_usd']:.4f}",
                     f"${r['usd_per_question']:.5f}" if r["usd_per_question"] is not None else "-",
                     f"${r['usd_per_correct']:.5f}" if r["usd_per_correct"] else "-"])
    L += [table(["Model", "Correct", "Accuracy (95% interval)", "Made-up facts", "Cost", "Per question", "Per correct answer"], rows), ""]
    L += ["_Made-up facts: numbers or citations in an answer that cannot be traced to that question's tool results or loaded "
          "memory (Phase 4 grounding rules; small integers, years and dates are exempt)._", ""]
    L += ["## Accuracy by category", ""]
    ms = list(s["models"])
    L += [table(["Category"] + ms, [[c] + [f"{s['models'][m]['categories'][c]['correct']}/{s['models'][m]['categories'][c]['of']}"
                                           for m in ms] for c in CATS]), ""]
    if "comparison" in s:
        c = s["comparison"]
        L += ["## Paired comparison and decision", "",
              f"Same {s['graded']} questions for both models. {c['model']} minus {ASSISTANT}: **{100 * c['difference']:+.1f} points** "
              f"(95% paired bootstrap interval {100 * c['ci95'][0]:+.1f} to {100 * c['ci95'][1]:+.1f}); questions only "
              f"{c['model']} got right: {c['only_comparison_correct']}, only {ASSISTANT}: {c['only_assistant_correct']}; "
              f"exact McNemar p = {c['mcnemar_p']:.3f}."
              + (f" Extra cost per extra correct answer: ${c['extra_usd_per_extra_correct']}." if c["extra_usd_per_extra_correct"] else ""), "",
              f"**Decision (rule fixed before the run):** {c['decision']}", ""]
    else:
        L += ["## Paired comparison and decision", "", "_Pending: the comparison model has not been run yet._", ""]
    if "phase4_live" in s:
        a2, a3 = s["phase4_live"].get("A2", {}), s["phase4_live"].get("A3", {})
        L += ["## Phase 4's nine questions, live (criteria A2 and A3)", "",
              table(["Criterion", "Result", "Detail"],
                    [["A2 grounded", "pass" if a2.get("pass") else "**FAIL**",
                      f"citations {a2['detail']['citations']}, numbers {a2['detail']['numbers']} (share {a2['detail']['share']})"],
                     ["A3 safe and scoped", "pass" if a3.get("pass") else "**FAIL**", json.dumps(a3.get("detail"))]]), ""]
        if a2.get("detail", {}).get("misses"):
            L += ["Untraceable items: " + "; ".join(f"{q} {k} '{v}'" for q, k, v in a2["detail"]["misses"]), ""]
    L += ["## Wrong answers", ""]
    for m, r in s["models"].items():
        L += [f"**{m}** ({len(r['wrong'])}): " + ("; ".join(f"{i} ({w})" for i, w in r["wrong"].items()) or "none"), ""]
    if "hand_review" in s:
        h = s["hand_review"]
        L += ["## Hand review of the wrong answers (post hoc; grades unchanged)", "", h["_about"], "",
              table(["Model", "Question", "Verdict", "Why"], [[r["model"], r["id"], r["verdict"], r["why"]] for r in h["reviews"]]), "",
              "**Made-up facts, read one by one:** " + " ".join(f"{k}: {v}" for k, v in h["made_up_facts_review"].items()), "",
              f"**Summary:** {h['summary']}", "", f"**Correction:** {h['correction']}", ""]
    L += ["## Controls (free, not a model)", "",
          "Stand-ins run through the same loop, tools and memory: one answers from the gold, one gives planted wrong answers. "
          "The grader must accept every gold answer and reject every wrong one.", "",
          table(["Control", "Graded correct"], [[k, f"{v['correct']}/{v['of']}"] for k, v in s["controls"].items()]), ""]
    if "verification" in s:
        v = s["verification"]
        L += ["## Independent verification", "", f"`python -m mdqc.verify_phase6`: {v['passed']}, scorecard **{v['scorecard_score']}**.", "",
              table(["Check", "What", "Result"], [[c["id"], c["check"], "pass" if c["pass"] else "**FAIL**"] for c in v["checks"]]), ""]
    L += ["## Limits", "",
          "- 80 graded questions: intervals are wide; a few points' difference between models is within noise.",
          "- Text-matching grades are strict and literal (for example, the first company named must be the right one); the rules "
          "were fixed in advance, and every wrong answer is listed above with the reason, so a reader can judge each one.",
          "- Gold answers count reports, not failures: report counts are not failure rates.",
          "- The verifier's re-grade is separate code but uses the same matching patterns, and its made-up-fact count shares "
          "Phase 4's checker: it catches coding slips, not weaknesses in the rules themselves.",
          "- One run per question per model: the model's answers vary between runs, so a repeat would differ slightly.", "",
          "## Changes after pre-registration (post hoc)", "",
          "- Before any scored run, the grader's percentage rounding was set to ordinary half-up rounding (26.5 -> 27); Python's "
          "default rounds halves to even (26.5 -> 26), which would have marked a correct '27%' wrong. Found by a unit test.",
          "- The cost estimate first priced a whole question as one request (wrongly applying Haiku's long-prompt price); fixed "
          "before any paid call. Estimates only; budgets are enforced from the API's own token counts.",
          "- The optional free local model (Ollama) comparison in the plan was not run.", ""]
    return "\n".join(L)


def main(check: bool) -> int:
    s = summarise()
    doc, js = render(s), json.dumps(s, indent=1) + "\n"
    if check:
        ok = DOC.exists() and DOC.read_text(encoding="utf-8") == doc and (RES / "summary.json").read_text(encoding="utf-8") == js
        print("docs/EVALUATION.md and summary.json are " + ("current" if ok else "STALE: run python -m mdqc.report_phase6"))
        return 0 if ok else 1
    DOC.write_text(doc, encoding="utf-8", newline="\n")
    (RES / "summary.json").write_text(js, encoding="utf-8", newline="\n")
    print(f"wrote {DOC.relative_to(ROOT)} and results/phase6/summary.json")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    sys.exit(main(ap.parse_args().check))
