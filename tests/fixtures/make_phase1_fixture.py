"""Build the small committed fixture CI uses to exercise the Phase 1 EDA + verifier.

Run once after the full download:  python tests/fixtures/make_phase1_fixture.py
Takes the first 40 reports and first 10 recalls per product code from data/raw, blanks the
manufacturer contact fields (we never commit them), and writes tests/fixtures/phase1/raw/.
The data is public FDA data (public domain); about 1 MB in total.
"""

import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "raw"
DST = ROOT / "tests" / "fixtures" / "phase1" / "raw"
CODES = list(json.loads((ROOT / "config" / "scope.json").read_text(encoding="utf-8"))["product_codes"])
CONTACT_PREFIX = "manufacturer_contact_"


def take(src: Path, dst: Path, n: int) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    k = 0
    with gzip.open(src, "rt", encoding="utf-8") as fin, open(dst, "wb") as fh, \
            gzip.GzipFile(filename="", fileobj=fh, mode="wb", mtime=0) as gz:
        for line in fin:
            rec = json.loads(line)
            for key in list(rec):
                if key.startswith(CONTACT_PREFIX):
                    rec[key] = ""
            gz.write((json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            k += 1
            if k >= n:
                break
    return k


if __name__ == "__main__":
    for code in CODES:
        e = take(SRC / f"events_{code}.jsonl.gz", DST / f"events_{code}.jsonl.gz", 40)
        r = take(SRC / f"recalls_{code}.jsonl.gz", DST / f"recalls_{code}.jsonl.gz", 10)
        print(code, e, "reports,", r, "recalls")
