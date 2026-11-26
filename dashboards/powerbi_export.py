"""Phase 8 part 2: export the powerbi views to CSV files for Power BI (no database login needed by the report).

Run:  python -m dashboards.powerbi_export    -> data/powerbi/*.csv (git-ignored) and dashboards/powerbi_export_manifest.json
Files are sorted by their key and written with the same CSV dialect every time, so two exports are byte-identical.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "powerbi"
VIEWS = {"products": "product_code", "reports": "mdr_report_key", "failure_modes": "failure_mode", "recalls": "recall_number", "battery_families": "mdr_report_key"}


def main() -> dict:
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    man = {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        con.execute("SET TRANSACTION READ ONLY")
        for view, key in VIEWS.items():
            cur = con.execute(f"SELECT * FROM powerbi.{view} ORDER BY {key}")
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow([c.name for c in cur.description])
            n = 0
            for row in cur:
                w.writerow(["" if v is None else str(v) for v in row])
                n += 1
            p = OUT / f"{view}.csv"
            p.write_text(buf.getvalue(), encoding="utf-8", newline="")
            man[p.name] = {"rows": n, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "key": key}
    (ROOT / "dashboards" / "powerbi_export_manifest.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8", newline="\n")
    print({k: v["rows"] for k, v in man.items()}, f"{sum((OUT / k).stat().st_size for k in man) / 1e6:.1f} MB")
    return man


if __name__ == "__main__":
    main()
