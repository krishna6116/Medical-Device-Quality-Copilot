"""Phase 7c: build core_all (2022-2026 reports, current recalls) and analytics_all. Never touches core or analytics.

Run:  python -m mdqc.load_all --raw          refresh recalls from openFDA and join the two report snapshots -> data/raw_all/
      python -m mdqc.load_all --load         data/raw_all -> schema core_all (the Phase 2 loader, later window end)
      python -m mdqc.load_all --analytics    failure modes (Phase 3 method M1) and signals -> schema analytics_all
      python -m mdqc.load_all --embed        vectors for the new reports -> data/processed/embeddings_all.npy (about an hour, resumes)
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OLD, NEW, ALL = ROOT / "data" / "raw", ROOT / "data" / "raw_new", ROOT / "data" / "raw_all"
OUT, PROC = ROOT / "results" / "phase7c", ROOT / "data" / "processed"
CODES = ["LPH", "JWH", "MBH", "LWP", "LZG"]
W_TO = date(2026, 12, 31)
MONTHS = [f"{y}-{m:02d}" for y in range(2022, 2027) for m in range(1, 13) if (y, m) <= (2026, 9)]
# The only companies the tools may resolve to are those in core_all; spelling variants stay as FDA wrote them.


def connect():
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    return psycopg.connect(os.environ["DATABASE_URL"])


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")


def lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for x in f:
            if x.strip():
                yield json.loads(x)


def raw() -> None:
    from dotenv import load_dotenv

    from mdqc.download import now, recall_search, server_total, sha256, write_jsonl_gz
    from mdqc.openfda import OpenFDAClient

    load_dotenv(ROOT / ".env")
    c, man = OpenFDAClient(), {"events": {}, "recalls": {}}
    for code in CODES:
        name = f"events_{code}.jsonl.gz"

        def both():
            yield from lines(OLD / name)
            yield from lines(NEW / name)
        info = write_jsonl_gz(ALL / name, both())
        man["events"][code] = {"old": sum(1 for _ in lines(OLD / name)), "new": sum(1 for _ in lines(NEW / name)), "joined": info["records"], "sha256": sha256(ALL / name)}
        n, updated = server_total(c, "recall", recall_search(code))
        path = ALL / f"recalls_{code}.jsonl.gz"
        got = write_jsonl_gz(path, c.iter_records("recall", recall_search(code)))
        man["recalls"][code] = {"server_total": n, "server_last_updated": updated, "downloaded": got["records"], "sha256": sha256(path), "finished_utc": now()}
        print(code, man["events"][code]["joined"], "reports;", got["records"], "recalls of", n, flush=True)
    write_jsonl_gz(ALL / "classification.jsonl.gz", lines(OLD / "classification.jsonl.gz"))
    save("raw_manifest.json", man)


def load() -> None:
    from mdqc import load as loader

    s = loader.load(ALL, "core_all", write_summary=False, window_to=W_TO, text_required_until=date(2024, 12, 31))
    save("load_summary.json", {k: s[k] for k in ("run_id", "schema", "counts", "raw_checksums")})


def signals(series: dict) -> list[tuple]:
    """Phase 3 rule: at least 5 reports and Poisson p < 0.001 against the previous 12 months (floor 0.5)."""
    from scipy.stats import poisson

    out = []
    for (code, parent, mode), cnt in sorted(series.items()):
        v = [cnt.get(m, 0) for m in MONTHS]
        for t in range(12, len(MONTHS)):
            lam = max(0.5, float(np.mean(v[t - 12:t])))
            p = float(poisson.sf(v[t] - 1, lam)) if v[t] > 0 else 1.0
            if v[t] >= 5 and p < 0.001:
                out.append((code, parent, mode, MONTHS[t], v[t], round(lam, 3), p))
    return out


def analytics() -> None:
    from mdqc.failure_modes import family, m1

    with connect() as con:
        rep = {k: (c, p, d) for k, c, p, d in con.execute("""SELECT r.mdr_report_key, r.product_code, m.parent_company, r.date_received
            FROM core_all.fact_report r JOIN core_all.dim_manufacturer m USING (manufacturer_id)""").fetchall()}
        dev, pat = defaultdict(list), defaultdict(list)
        for k, t in con.execute("SELECT mdr_report_key, term FROM core_all.report_problem").fetchall():
            dev[k].append(t)
        for k, t in con.execute("SELECT mdr_report_key, term FROM core_all.report_patient_problem").fetchall():
            pat[k].append(t)
        mode = {k: m1(family(c), dev[k], pat[k]) for k, (c, _, _) in rep.items()}
        series: dict = defaultdict(Counter)
        for k, (c, p, d) in rep.items():
            series[(c, p, mode[k])][d.strftime("%Y-%m")] += 1
        sig = signals(series)
        con.execute("DROP SCHEMA IF EXISTS analytics_all CASCADE")
        con.execute("CREATE SCHEMA analytics_all")
        con.execute("CREATE TABLE analytics_all.report_failure_mode (mdr_report_key text PRIMARY KEY, product_code text NOT NULL, mode text NOT NULL, method text NOT NULL)")
        with con.cursor().copy("COPY analytics_all.report_failure_mode FROM STDIN") as cp:
            for k in sorted(mode):
                cp.write_row((k, rep[k][0], mode[k], "M1"))
        con.execute("""CREATE TABLE analytics_all.signal_month (product_code text, parent_company text, mode text, month text, count integer,
                       expected double precision, p_value double precision, PRIMARY KEY (product_code, parent_company, mode, month))""")
        with con.cursor().copy("COPY analytics_all.signal_month FROM STDIN") as cp:
            for s in sig:
                cp.write_row(s)
        con.commit()
    save("analytics_summary.json", {"reports": len(mode), "signals": len(sig), "signals_2022_2024": sum(s[3] <= "2024-12" for s in sig),
                                    "signals_by_code": dict(Counter(s[0] for s in sig)), "modes": dict(sorted(Counter(mode.values()).items()))})
    print(len(mode), "modes;", len(sig), "signals")


def embed_new() -> None:
    from mdqc import embed
    from mdqc.textprep import load_texts

    old_keys = (PROC / "embeddings_bge_small_keys.txt").read_text(encoding="utf-8").split()
    have = set(old_keys)
    with connect() as con:
        keys = sorted(k for (k,) in con.execute("SELECT mdr_report_key FROM core_all.fact_report").fetchall() if k not in have)
        texts = load_texts(con, "core_all", keys)
    keys = [k for k in keys if texts.get(k)]  # reports whose narrative FDA has not published yet cannot be searched by text
    model = embed.load_model()
    print("model", embed.model_revision(model), len(keys), "new reports", flush=True)
    parts, t0, step = [], time.monotonic(), 5000
    for s in range(0, len(keys), step):
        part = PROC / f"emb_all_chunk_{s:06d}.npy"
        if not part.exists():
            np.save(part, embed.encode(model, [texts[k] for k in keys[s:s + step]]).astype(np.float16))
        parts.append(part)
        print(f"{min(s + step, len(keys)):,}/{len(keys):,} ({time.monotonic() - t0:.0f}s)", flush=True)
    emb = np.concatenate([np.load(PROC / "embeddings_bge_small.npy")] + [np.load(p) for p in parts])
    np.save(PROC / "embeddings_all.npy", emb)
    (PROC / "embeddings_all_keys.txt").write_text("\n".join(old_keys + keys) + "\n", encoding="utf-8")
    for p in parts:
        p.unlink()
    save("embed_summary.json", {"rows": int(emb.shape[0]), "dims": int(emb.shape[1]), "new": len(keys), "revision": embed.model_revision(model)})
    print("done", emb.shape, f"{time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 7c load")
    for n in ("raw", "load", "analytics", "embed"):
        ap.add_argument(f"--{n}", action="store_true")
    a = ap.parse_args()
    for flag, fn in ((a.raw, raw), (a.load, load), (a.analytics, analytics), (a.embed, embed_new)):
        if flag:
            fn()
