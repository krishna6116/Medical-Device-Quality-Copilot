"""Phase 8 data checks (scorecard dashboards/phase8_scorecard.json). Project environment; the app's own checks are tests/app/.

Run:  python -m dashboards.verify_phase8             CI: manifest, copied files, code scan, personal data, docs, planted bugs
      python -m dashboards.verify_phase8 --local     also snapshots vs separate SQL and two fresh exports -> dashboards/local_checks.json

Separate code from dashboards/export_snapshots.py (same author): rows are pulled with plain SELECTs and counted in Python.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP, APP = ROOT / "dashboards" / "snapshots", ROOT / "app"
KEYS = {"quarterly.csv": 3, "quarterly_modes.csv": 3, "makers.csv": 3, "signals.csv": 4, "recalls.csv": 1, "drift.csv": 2}
FORBIDDEN = re.compile(r"^\s*(import|from)\s+(anthropic|psycopg|sqlalchemy|mdqc)\b|sk-ant-|postgresql://|DATABASE_URL|ANTHROPIC_API_KEY", re.M)


def rows(p: Path) -> list[list[str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest_ok(snap: Path, root: Path = ROOT) -> list[str]:
    m, bad = json.loads((snap / "manifest.json").read_text(encoding="utf-8")), []
    files = {p.name for p in snap.iterdir() if p.name != "manifest.json"}
    if files != set(m["files"]):
        bad.append(f"files differ from manifest: {sorted(files ^ set(m['files']))}")
    for name, info in m["files"].items():
        p = snap / name
        if not p.exists() or sha(p) != info["sha256"]:
            bad.append(f"{name}: sha256 differs from manifest")
            continue
        if name.endswith(".csv"):
            r = rows(p)[1:]
            keys = [tuple(x[: KEYS[name]]) for x in r]
            if len(r) != info["rows"] or len(set(keys)) != len(keys) or keys != sorted(keys):
                bad.append(f"{name}: rows {len(r)} vs {info['rows']}, or key not unique and sorted")
    for s, h in m["sources"].items():
        if sha(root / s) != h:
            bad.append(f"stale: {s} changed since the snapshot was made")
    if hashlib.sha256("".join(v["sha256"] for v in m["files"].values()).encode()).hexdigest() != m["data_checksum"]:
        bad.append("data checksum does not match the files")
    return bad


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def hide(text: str) -> str:
    """The app hides phone-shaped numbers (own pattern: three digits, three digits, four digits)."""
    return re.sub(r"(?<!\d)(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b", "[phone number removed]", text)


def copied_ok(snap: Path) -> list[str]:
    bad = []
    d = load("results/phase7/drift_check.json")
    got = {(r[0], r[1]): r for r in rows(snap / "drift.csv")[1:]}
    for r in d["rows"]:
        g = got.get((r["code"], r["quarter"]))
        want = [r["code"], r["quarter"], str(r["reports"]), str(round(r["volume_change"], 4)), str(round(r["mode_mix"], 4)), str(round(r["vocabulary"], 4)), ";".join(r["flags"])]
        if g is None or g[:7] != want or not g[7].startswith(r["largest_mode_moves"][0][0] + " "):
            bad.append(f"drift {r['code']} {r['quarter']}")
    a = {x["id"]: x for x in json.loads((snap / "answers.json").read_text(encoding="utf-8"))}
    g6 = load("results/phase6/grades.json")["claude-haiku-5-5"]
    for q in load("config/phase6_eval_set.json")["questions"]:
        r, x = load(f"results/phase6/claude-haiku-5-5/{q['id']}.json"), a.get(f"P6-{q['id']}")
        if x is None or (x["question"], x["answer"], x["cost_usd"], x["steps"], x["model"], x["tools"]) != (hide(q["text"]), hide(r["answer"]), r["cost_usd"], r["steps"], r["model"], [t["name"] for t in r["tool_calls"]]) \
                or x["correct"] != (g6[q["id"]]["correct"] if g6[q["id"]]["graded"] else None):
            bad.append(f"answer P6-{q['id']}")
    m7 = {r["id"]: r["correct"] for r in load("results/phase7c/model_check.json")["rows"]}
    for q in load("config/phase7c_questions.json")["questions"]:
        r, x = load(f"results/phase7c/answers/{q['id']}.json"), a.get(f"P7c-{q['id']}")
        if x is None or (x["question"], x["answer"], x["cost_usd"], x["correct"]) != (hide(q["text"]), hide(r["answer"]), r["cost_usd"], m7[q["id"]]):
            bad.append(f"answer P7c-{q['id']}")
    if len(a) != 105:
        bad.append(f"{len(a)} answers, expected 105")
    res, s6 = json.loads((snap / "results.json").read_text(encoding="utf-8")), load("results/phase6/summary.json")
    h, r7 = s6["models"]["claude-haiku-5-5"], load("results/phase7/redteam_grades.json")
    want = {("phase6", "haiku_correct"): h["correct"], ("phase6", "haiku_cost_usd"): h["cost_usd"], ("phase6", "opus_correct"): s6["models"]["claude-opus-5-5"]["correct"],
            ("phase6", "difference"): s6["comparison"]["difference"], ("phase7", "scorecard"): load("results/phase7/verify_phase7.json")["scorecard"],
            ("phase7", "withheld"): sum(bool(x["withheld_for"]) for x in r7["rows"]), ("phase7", "g2_met"): r7["G2_met"],
            ("phase7b", "caught"): load("results/phase7b/test_grades.json")["caught"], ("phase7c", "correct"): load("results/phase7c/model_check.json")["correct"],
            ("phase7c", "checks"): load("results/phase7c/verify_phase7c.json")["passed"]}
    bad += [f"results {k}" for k, v in want.items() if res[k[0]][k[1]] != v]
    return bad


def code_ok(app: Path) -> list[str]:
    return [str(p.relative_to(app.parent)) for p in sorted(app.rglob("*.py")) if FORBIDDEN.search(p.read_text(encoding="utf-8"))]


def personal_ok(snap: Path) -> list[str]:
    email, phone = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), re.compile(r"(?<!\d)(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
    hits = []
    for p in snap.iterdir():
        t = p.read_text(encoding="utf-8")
        hits += [f"{p.name}: {m.group()}" for m in list(email.finditer(t)) + list(phone.finditer(t)) if "evil.example" not in m.group()]
    return hits


def db_ok() -> list[str]:
    """Snapshots built from the database = separate queries counted in Python."""
    import os

    import psycopg
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    bad = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        rep = con.execute("""SELECT r.product_code, r.date_received, r.event_type, m.parent_company, f.mode FROM core_all.fact_report r, core_all.dim_manufacturer m,
            analytics_all.report_failure_mode f WHERE r.manufacturer_id = m.manufacturer_id AND f.mdr_report_key = r.mdr_report_key""").fetchall()
        qtr = lambda d: f"{d.year}Q{(d.month + 2) // 3}"  # noqa: E731
        for name, cnt in (("quarterly.csv", Counter((c, qtr(d), e) for c, d, e, _, _ in rep)), ("quarterly_modes.csv", Counter((c, qtr(d), f) for c, d, _, _, f in rep)),
                          ("makers.csv", Counter((c, str(d.year), m) for c, d, _, m, _ in rep))):
            snap = {tuple(r[:3]): int(r[3]) for r in rows(SNAP / name)[1:]}
            if snap != dict(cnt):
                bad.append(f"{name}: {len(set(snap.items()) ^ set(cnt.items()))} cells differ")
        sig = {(a, b, c, d): (str(e), x) for a, b, c, d, e, x in con.execute("SELECT product_code, parent_company, mode, month, count, expected FROM analytics_all.signal_month").fetchall()}
        snap = {tuple(r[:4]): (r[4], float(r[5])) for r in rows(SNAP / "signals.csv")[1:]}
        if snap != sig:
            bad.append("signals.csv differs")
        rc = {}
        for a, b, c, d, e, f, g, h in con.execute("""SELECT c.product_res_number, c.res_event_number, c.product_code, m.parent_company, c.event_date_initiated, c.recall_status,
                coalesce(c.root_cause, ''), coalesce(c.reason_for_recall, '') FROM core_all.fact_recall c, core_all.dim_manufacturer m WHERE c.manufacturer_id = m.manufacturer_id""").fetchall():
            rc[a] = [a, b or "", c, d, str(e), f or "", " ".join(g.split()), " ".join(h.split())[:300]]
        snap = {r[0]: r for r in rows(SNAP / "recalls.csv")[1:]}
        diff = [k for k in rc if snap.get(k) != rc[k]]
        if diff or len(snap) != len(rc):
            bad.append(f"recalls.csv: {len(diff)} rows differ")
    return bad


def export_twice_ok() -> list[str]:
    before = {p.name: sha(p) for p in SNAP.iterdir()}
    bad = []
    for i in (1, 2):
        subprocess.run([sys.executable, "-m", "dashboards.export_snapshots"], cwd=ROOT, check=True, capture_output=True)
        now = {p.name: sha(p) for p in SNAP.iterdir()}
        if now != before:
            bad.append(f"export {i} differs from the committed snapshots: {sorted(k for k in now if now[k] != before.get(k))}")
    return bad


def planted() -> dict:
    """Each planted bug must be caught."""
    out = {}
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        def copy():
            d = tmp / f"s{len(out)}"
            shutil.copytree(SNAP, d)
            return d
        d = copy()
        p = d / "quarterly.csv"
        r = rows(p)
        r[1][3] = str(int(r[1][3]) + 1)
        with p.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows(r)
        out["a changed number"] = bool(manifest_ok(d))
        d = copy()
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        m["data_checksum"] = "0" * 64
        (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        out["a wrong checksum"] = bool(manifest_ok(d))
        d = copy()
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        m["sources"]["results/phase6/summary.json"] = "1" * 64
        (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        out["a stale snapshot"] = any("stale" in x for x in manifest_ok(d))
        d = copy()
        a = json.loads((d / "answers.json").read_text(encoding="utf-8"))
        a[3]["answer"] = a[3]["answer"].replace("1", "7", 1)
        (d / "answers.json").write_text(json.dumps(a), encoding="utf-8")
        out["an edited recorded answer"] = bool(copied_ok(d))
        app = tmp / "app"
        shutil.copytree(APP, app)
        (app / "views" / "home.py").write_text("import anthropic\n" + (app / "views" / "home.py").read_text(encoding="utf-8"), encoding="utf-8")
        out["an API import"] = bool(code_ok(app))
        d = copy()
        (d / "answers.json").write_text((d / "answers.json").read_text(encoding="utf-8").replace("Insulet", "call 617-555-0199 Insulet", 1), encoding="utf-8")
        out["a phone number in a snapshot"] = bool(personal_ok(d))
    return out


def main(local: bool) -> int:
    checks = []

    def check(cid, name, bad):
        checks.append({"id": cid, "check": name, "pass": not bad, "detail": bad[:6] if isinstance(bad, list) else bad})
        print(f"{'PASS' if not bad else 'FAIL'} {cid} {name}: {json.dumps(bad[:4] if isinstance(bad, list) else bad)[:300]}")

    check("A1.1", "snapshots match the manifest; sources not changed", manifest_ok(SNAP))
    check("A1.3", "copied snapshots equal their results files", copied_ok(SNAP))
    check("A2.1", "app has no API, database or key code", code_ok(APP))
    check("A2.4", "no contact details in snapshots", personal_ok(SNAP))
    docs = subprocess.run([sys.executable, "-m", "dashboards.report_phase8", "--check"], cwd=ROOT, capture_output=True, text=True)
    check("A3.3", "docs/APP.md is current", [] if docs.returncode == 0 else [docs.stdout.strip()])
    p = planted()
    check("A4.2", "planted bugs caught (data side; the page ones are in tests/app)", [k for k, v in p.items() if not v])
    if local:
        check("A1.2", "database snapshots equal separate SQL", db_ok())
        check("A3.1", "two fresh exports equal the committed snapshots", export_twice_ok())
        out = {"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "data_checksum": json.loads((SNAP / "manifest.json").read_text(encoding="utf-8"))["data_checksum"],
               "checks": checks, "planted": p}
        (ROOT / "dashboards" / "local_checks.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    ok = all(c["pass"] for c in checks)
    print(f"\n{sum(c['pass'] for c in checks)}/{len(checks)} checks pass")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true")
    sys.exit(main(ap.parse_args().local))
