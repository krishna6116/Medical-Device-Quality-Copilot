"""Download the pre-registered scope (config/scope.json) from openFDA.

Run:  python -m mdqc.download            (resumes: skips files already complete)
      python -m mdqc.download --force    (re-download everything)

What it writes (data/ is git-ignored except the checksum file):
  data/raw/events_<CODE>.jsonl.gz      one adverse-event report per line, as openFDA returned it
  data/raw/recalls_<CODE>.jsonl.gz     every recall for the code (code_info cut to 2,000 characters)
  data/raw/classification.jsonl.gz     the FDA classification record of each code
  data/checksums.sha256                SHA-256 of each raw file (committed: pins our copy)
  results/phase1/download_manifest.json  server totals vs downloaded counts (committed, no data)

Why the server total is queried right before each code: openFDA refreshes weekly, so the honest
comparison (criterion C1) is against the total at the moment of download, not at registration.
gzip files are written with mtime=0 and no file name so the same content always gives the same checksum.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from mdqc.openfda import OpenFDAClient, build_search

ROOT = Path(__file__).resolve().parents[1]
SCOPE = json.loads((ROOT / "config" / "scope.json").read_text(encoding="utf-8"))
RAW = ROOT / "data" / "raw"
CHECKSUMS = ROOT / "data" / "checksums.sha256"
MANIFEST = ROOT / "results" / "phase1" / "download_manifest.json"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_search(code: str) -> str:
    w = SCOPE["event_window"]
    return build_search(product_code=code, date_field=SCOPE["event_date_field"],
                        date_from=w["from"], date_to=w["to"])


def recall_search(code: str) -> str:
    return f"product_code:{code}"


def write_jsonl_gz(path: Path, records) -> dict:
    """Stream records to a deterministic .jsonl.gz; return counts and duplicate keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    n = 0
    with open(tmp, "wb") as fh, gzip.GzipFile(filename="", fileobj=fh, mode="wb", mtime=0, compresslevel=6) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8", newline="\n")
        for rec in records:
            text.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
        text.flush()
        text.detach()
    tmp.replace(path)
    return {"records": n}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def server_total(c: OpenFDAClient, endpoint: str, search: str) -> tuple[int, str]:
    data, _ = c.get(endpoint, search=search, limit=1)
    return data["meta"]["results"]["total"], data["meta"].get("last_updated", "")


def download_events(c: OpenFDAClient, code: str) -> dict:
    search = event_search(code)
    total, updated = server_total(c, "event", search)
    keys: list[str] = []
    t0 = time.monotonic()

    def records():
        for i, rec in enumerate(c.iter_records("event", search)):
            keys.append(rec.get("mdr_report_key"))
            if (i + 1) % 9990 == 0:
                print(f"  {code}: {i + 1:,}/{total:,} ({time.monotonic() - t0:.0f}s)", flush=True)
            yield rec

    path = RAW / f"events_{code}.jsonl.gz"
    info = write_jsonl_gz(path, records())
    distinct = len(set(keys))
    return {"file": path.name, "search": search, "server_total_before": total,
            "server_last_updated": updated, "downloaded": info["records"],
            "distinct_mdr_report_key": distinct, "duplicates": info["records"] - distinct,
            "seconds": round(time.monotonic() - t0, 1), "finished_utc": now()}


def download_recalls(c: OpenFDAClient, code: str) -> dict:
    search = recall_search(code)
    total, updated = server_total(c, "recall", search)
    path = RAW / f"recalls_{code}.jsonl.gz"
    info = write_jsonl_gz(path, c.iter_records("recall", search))
    return {"file": path.name, "search": search, "server_total_before": total,
            "server_last_updated": updated, "downloaded": info["records"], "finished_utc": now()}


def download_classification(c: OpenFDAClient, codes: list[str]) -> dict:
    recs = []
    for code in codes:
        data, _ = c.get("classification", search=f"product_code:{code}", limit=10)
        recs.extend(data["results"])
    path = RAW / "classification.jsonl.gz"
    info = write_jsonl_gz(path, recs)
    return {"file": path.name, "downloaded": info["records"], "finished_utc": now()}


def main(force: bool = False) -> dict:
    load_dotenv(ROOT / ".env")
    c = OpenFDAClient()
    codes = list(SCOPE["product_codes"])
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() and not force else {}
    manifest.setdefault("events", {})
    manifest.setdefault("recalls", {})
    manifest.update({"scope_registered_on": SCOPE["registered_on"], "api_key_used": bool(c.api_key),
                     "page_size": c.max_limit})

    def save():
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    for code in codes:
        done = manifest["events"].get(code)
        if done and (RAW / done["file"]).exists() and not force:
            print(f"events {code}: already downloaded ({done['downloaded']:,}), skipping")
            continue
        print(f"events {code}: downloading", flush=True)
        manifest["events"][code] = download_events(c, code)
        save()
        e = manifest["events"][code]
        print(f"events {code}: {e['downloaded']:,} records, server said {e['server_total_before']:,}, "
              f"duplicates {e['duplicates']}", flush=True)

    for code in codes:
        done = manifest["recalls"].get(code)
        if done and (RAW / done["file"]).exists() and not force:
            continue
        manifest["recalls"][code] = download_recalls(c, code)
        save()
        r = manifest["recalls"][code]
        print(f"recalls {code}: {r['downloaded']:,} (server {r['server_total_before']:,})", flush=True)

    manifest["classification"] = download_classification(c, codes)

    files = sorted(RAW.glob("*.jsonl.gz"))
    lines = [f"{sha256(p)}  data/raw/{p.name}" for p in files]
    CHECKSUMS.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    manifest["files"] = {p.name: {"bytes": p.stat().st_size} for p in files}
    manifest["completed_utc"] = now()
    save()
    total_mb = sum(p.stat().st_size for p in files) / 1e6
    print(f"done: {len(files)} files, {total_mb:.1f} MB compressed -> {CHECKSUMS}")
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="re-download everything")
    main(force=ap.parse_args().force)
