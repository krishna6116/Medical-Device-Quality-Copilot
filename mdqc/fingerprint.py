"""Order-independent fingerprint of every table in the given schemas (read-only).

Run:  python -m mdqc.fingerprint out.json core analytics memory
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def fingerprints(con, schemas) -> dict:
    out = {}
    for s in schemas:
        for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY 1", (s,)).fetchall():
            n, h = con.execute(f'SELECT count(*), coalesce(sum((\'x\' || substr(md5(x::text), 1, 15))::bit(60)::bigint::numeric), 0) FROM "{s}"."{t}" x').fetchone()
            out[f"{s}.{t}"] = [n, str(h)]
    return out


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        f = fingerprints(c, sys.argv[2:])
    p = Path(sys.argv[1])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(f, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(len(f), "tables,", sum(v[0] for v in f.values()), "rows")
