"""Phase 7 drift monitoring of new FDA reports (no database, no API key, no model).

Run:  python -m mdqc.drift --baseline    thresholds and planted-shift detection from the 2022-2024 raw files
      python -m mdqc.drift --download    reports received from 2025-01-01 -> data/raw_new/ (git-ignored)
      python -m mdqc.drift --check       105 drift statistics for 2025Q1-2026Q3

Rules: config/phase7_criteria.json ("drift"), committed before this file and before the download.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from mdqc.failure_modes import family, m1
from mdqc.textprep import report_text

ROOT = Path(__file__).resolve().parents[1]
BASE, NEW, OUT = ROOT / "data" / "raw", ROOT / "data" / "raw_new", ROOT / "results" / "phase7"
CODES = ["LPH", "JWH", "MBH", "LWP", "LZG"]
WINDOW = ("20250101", "20261231")
TEST_QUARTERS = [f"2025Q{i}" for i in range(1, 5)] + [f"2026Q{i}" for i in range(1, 4)]
METRICS = ("volume", "mode_mix", "vocabulary")
WORD = re.compile(r"[a-z]{3,}")


def read(folder: Path, code: str) -> dict:
    """quarter -> {"n": reports, "mode": Counter, "doc": Counter of reports containing each word}"""
    out: dict = defaultdict(lambda: {"n": 0, "mode": Counter(), "doc": Counter()})
    with gzip.open(folder / f"events_{code}.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            d = r["date_received"]
            q = out[f"{d[:4]}Q{(int(d[4:6]) - 1) // 3 + 1}"]
            patient = sorted({x for p in r.get("patient", []) for x in (p.get("patient_problems") or [])})
            text = report_text([(i, p.get("text_type_code"), p.get("text") or "") for i, p in enumerate(r.get("mdr_text", []))])
            q["n"] += 1
            q["mode"][m1(family(code), sorted(set(r.get("product_problems") or [])), patient)] += 1
            q["doc"].update(set(WORD.findall(text.lower())))
    return dict(out)


def total(quarters: list[dict], key: str) -> Counter:
    return sum((q[key] for q in quarters), Counter())


def vocabulary(base: dict) -> list[str]:
    return [w for w, _ in total([base[q] for q in sorted(base)], "doc").most_common(1000)]


def tv(a: Counter, b: Counter) -> float:
    ka, kb = sum(a.values()), sum(b.values())
    return 0.5 * sum(abs(a[k] / ka - b[k] / kb) for k in set(a) | set(b))


def js(a: Counter, b: Counter, vocab: list[str]) -> float:
    p, q = (np.array([c[w] for w in vocab], float) + 0.5 for c in (a, b))
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2
    return float((p * np.log2(p / m)).sum() / 2 + (q * np.log2(q / m)).sum() / 2)


def statistics(cur: dict, prev: list[dict], vocab: list[str]) -> dict:
    change = cur["n"] / float(np.mean([p["n"] for p in prev])) - 1
    return {"volume": abs(change), "volume_change": change, "mode_mix": tv(cur["mode"], total(prev, "mode")),
            "vocabulary": js(cur["doc"], total(prev, "doc"), vocab)}


def baseline() -> dict:
    cases = []  # (code, quarter, current, previous four, vocabulary)
    for code in CODES:
        b = read(BASE, code)
        v, qs = vocabulary(b), sorted(b)
        assert len(qs) == 12, (code, qs)
        cases += [(code, qs[i], b[qs[i]], [b[x] for x in qs[i - 4:i]], v) for i in range(4, 12)]
    stats = [{"code": c, "quarter": q, **statistics(cur, prev, v)} for c, q, cur, prev, v in cases]
    thr = {m: sorted(s[m] for s in stats)[-2] for m in METRICS}
    planted = {}
    for factor in (1.2, 1.4, 1.6):
        hit = sum(abs(cur["n"] * factor / np.mean([p["n"] for p in prev]) - 1) > thr["volume"] for _, _, cur, prev, _ in cases)
        planted[f"volume x{factor}"] = f"{hit}/{len(cases)}"
    for points in (10, 20, 35):
        hit = 0
        for _, _, cur, prev, _ in cases:
            ref, n = total(prev, "mode"), sum(cur["mode"].values())
            rare = min(sorted(ref), key=lambda k: ref[k])
            share = Counter({k: x / n * (1 - points / 100) for k, x in cur["mode"].items()})
            share[rare] += points / 100
            hit += tv(share, ref) > thr["mode_mix"]
        planted[f"mode_mix {points} points to the rarest mode"] = f"{hit}/{len(cases)}"
    for pct in (10, 30, 60):
        hit = 0
        for _, _, cur, prev, v in cases:
            doc = Counter(cur["doc"])
            # a random pct of reports gets the word; those that already had it do not count twice
            doc[v[-1]] += round(pct / 100 * (cur["n"] - doc[v[-1]]))
            hit += js(doc, total(prev, "doc"), v) > thr["vocabulary"]
        planted[f"vocabulary: rare word added to {pct}% of reports"] = f"{hit}/{len(cases)}"
    share = {k: int(x.split("/")[0]) / len(cases) for k, x in planted.items()}
    return {"baseline_values": len(stats), "thresholds": thr, "baseline_flags": {m: sum(s[m] > thr[m] for s in stats) for m in METRICS},
            "planted_detection": planted,
            "required_detection_met": share["volume x1.6"] >= 0.8 and share["mode_mix 35 points to the rarest mode"] >= 0.8,
            "statistics": stats}


def download() -> dict:
    from dotenv import load_dotenv

    from mdqc.download import now, server_total, sha256, write_jsonl_gz
    from mdqc.openfda import OpenFDAClient, build_search

    load_dotenv(ROOT / ".env")
    c = OpenFDAClient()
    man: dict = {"window": WINDOW, "events": {}}
    for code in CODES:
        search = build_search(product_code=code, date_field="date_received", date_from=WINDOW[0], date_to=WINDOW[1])
        n, updated = server_total(c, "event", search)
        keys: list[str] = []

        def records():
            for rec in c.iter_records("event", search):
                keys.append(rec.get("mdr_report_key"))
                yield rec

        path = NEW / f"events_{code}.jsonl.gz"
        info = write_jsonl_gz(path, records())
        man["events"][code] = {"server_total": n, "server_last_updated": updated, "downloaded": info["records"],
                               "distinct_keys": len(set(keys)), "bytes": path.stat().st_size, "sha256": sha256(path), "finished_utc": now()}
        print(code, man["events"][code], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    save("drift_manifest.json", man)
    return man


def check() -> dict:
    thr = json.loads((OUT / "drift_baseline.json").read_text(encoding="utf-8"))["thresholds"]
    rows, partial = [], {}
    for code in CODES:
        base, new = read(BASE, code), read(NEW, code)
        v, allq = vocabulary(base), {**base, **new}
        qs = sorted(allq)
        for q in TEST_QUARTERS:
            i = qs.index(q)
            s = statistics(allq[q], [allq[x] for x in qs[i - 4:i]], v)
            ref = total([allq[x] for x in qs[i - 4:i]], "mode")
            cur, nc, nr = allq[q]["mode"], sum(allq[q]["mode"].values()), sum(ref.values())
            moves = sorted(((cur[k] / nc - ref[k] / nr, k) for k in set(cur) | set(ref)), key=lambda x: -abs(x[0]))[:3]
            rows.append({"code": code, "quarter": q, "reports": allq[q]["n"], "previous_four": qs[i - 4:i], **s,
                         "flags": [m for m in METRICS if s[m] > thr[m]], "largest_mode_moves": [[k, round(d, 4)] for d, k in moves]})
        partial[code] = {q: new[q]["n"] for q in sorted(new) if q not in TEST_QUARTERS}
    return {"thresholds": thr, "checks": len(rows) * len(METRICS), "flags": {m: sum(m in r["flags"] for r in rows) for m in METRICS},
            "not_tested_incomplete": partial, "rows": rows}


def save(name: str, obj) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 7 drift monitoring")
    g = ap.add_mutually_exclusive_group(required=True)
    for name in ("baseline", "download", "check"):
        g.add_argument(f"--{name}", action="store_true")
    a = ap.parse_args()
    if a.baseline:
        r = baseline()
        save("drift_baseline.json", r)
        print(json.dumps({k: v for k, v in r.items() if k != "statistics"}, indent=1))
    elif a.download:
        download()
    else:
        r = check()
        save("drift_check.json", r)
        print(json.dumps({k: v for k, v in r.items() if k != "rows"}, indent=1))
        for x in r["rows"]:
            print(x["code"], x["quarter"], x["reports"], f"{x['volume_change']:+.3f} {x['mode_mix']:.3f} {x['vocabulary']:.3f}",
                  x["flags"], x["largest_mode_moves"][0])
