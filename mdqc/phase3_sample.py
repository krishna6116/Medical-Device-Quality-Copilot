"""Draw the Phase 3 reference sample without looking at any text.

Run:  python -m mdqc.phase3_sample   -> config/phase3_sample.csv (committed before labelling)

Rule: for each product code, order its reports by md5(mdr_report_key || SALT) and take the first 40;
the first 20 are 'validation' (used to choose methods), the next 20 'test' (used once, at the end).
md5 order is a reproducible stand-in for a random draw: anyone can re-run it and get the same keys.
Why split by report here (the project usually splits by product code): every method is rule-based or
zero-shot, nothing is trained on the labels; the labels only pick among a few pre-registered settings.
Stratifying by code keeps every device family in both halves.
"""

import csv
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "phase3_sample.csv"
SALT = "mdqc-phase3-2026-11-21"
PER_CODE, VALIDATION = 40, 20


def draw(con, schema="core"):
    rows = []
    for (code,) in con.execute(f"SELECT product_code FROM {schema}.dim_product_code ORDER BY 1").fetchall():
        keys = [k for (k,) in con.execute(
            f"SELECT mdr_report_key FROM {schema}.fact_report WHERE product_code = %s "
            "ORDER BY md5(mdr_report_key || %s) LIMIT %s", (code, SALT, PER_CODE)).fetchall()]
        rows += [(k, code, "validation" if i < VALIDATION else "test") for i, k in enumerate(keys)]
    return rows


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        rows = draw(con)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["mdr_report_key", "product_code", "split"])
        w.writerows(rows)
    print(f"{len(rows)} reports -> {OUT}")
