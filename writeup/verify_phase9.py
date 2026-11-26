"""Phase 9: independent check of the write-up (criteria in writeup/phase9_scorecard.json).

Run:  python -m writeup.verify_phase9                code checks W1-W7 (code parts) and W9; writes writeup/phase9_results.json
      python -m writeup.verify_phase9 --network      also W3 external links and W8 HTTP; writes writeup/phase9_evidence.json
      python -m writeup.verify_phase9 --browser-check CHECKSUM   records the About-page checksum read in a browser (W8)

The published numbers are recomputed here from the results files with separate code; writeup.facts is never imported.
"""

from __future__ import annotations

import csv
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "writeup/phase9_spec.json").read_text(encoding="utf-8"))
RESULTS_DOCS = ["README.md", "docs/CASE_STUDY.md", "docs/RESULTS.md"]
STATUS_DOCS = ["README.md", "docs/README.md", "docs/CASE_STUDY.md", "docs/RESULTS.md", "docs/ARCHITECTURE.md", "docs/DECISIONS.md", "CLAUDE.md"]
GENERATED = ["README.md", "docs/CASE_STUDY.md", "docs/RESULTS.md", "docs/ARCHITECTURE.md", "docs/DECISIONS.md", "docs/README.md", "docs/RELEASE_NOTES.md"]


def rd(p: str) -> str:
    return (ROOT / p).read_text(encoding="utf-8")


def js(p: str):
    return json.loads(rd(p))


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [l for l in out.splitlines() if l]


# ---------- independent values ----------

def expected() -> dict:
    """Recompute every published number from the results files, as the strings the docs may show."""
    v = {}
    eda = js("results/phase1/eda_summary.json")
    v["reports_core"] = sum(c["reports"] for c in eda["per_code"].values())
    l7c = js("results/phase7c/load_summary.json")["counts"]
    v["recalls"], v["reports_all"] = l7c["fact_recall"], l7c["fact_report"]
    names = js("results/phase2/load_summary.json")["stats"]["manufacturer_names"]
    v["maker_names"], v["companies"] = names
    t = js("results/phase3/selection.json")["test"]
    v["codebook"], v["codebook_lo"], v["codebook_hi"], v["embedding"] = t["M1"]["accuracy"], *t["M1"]["accuracy_ci95"], t["M3"]["accuracy"]
    s = js("results/phase3/signals.json")
    events = s["events"]
    v["signals"] = len(s["signal_list"])
    v["recall_events"], v["recall_hits"] = len(events), sum(1 for e in events if e["hit"])
    v["hit_rate"], v["base_rate"] = v["recall_hits"] / v["recall_events"], s["windows_with_signal"] / s["windows"]
    s6 = js("results/phase6/summary.json")
    h, o = s6["models"]["claude-haiku-5-5"], s6["models"]["claude-opus-5-5"]
    v.update(questions=s6["questions"], graded=h["of"], haiku=h["correct"], opus=o["correct"], haiku_usd=h["cost_usd"], opus_usd=o["cost_usd"],
             p=s6["comparison"]["mcnemar_p"], citations=s6["phase4_live"]["A2"]["detail"]["citations"])
    v["phase7"] = js("results/phase7/verify_phase7.json")["scorecard"]
    rows = js("results/phase7/redteam_grades.json")["rows"]
    v["redteam_n"] = len(rows)
    v["redteam_withheld"] = sum(1 for r in rows if r.get("withheld_for"))
    dc = js("results/phase7/drift_check.json")
    v["drift_checks"], v["drift_flags"] = dc["checks"], sum(dc["flags"].values())
    v["new_reports"] = sum(e["downloaded"] for e in js("results/phase7/drift_manifest.json")["events"].values())
    g = js("results/phase7b/test_grades.json")
    v["guard_caught"], v["guard_clean"] = g["caught"], f"{len(g['clean_withheld'])}/40"
    v["phase7c"] = js("results/phase7c/verify_phase7c.json")["passed"]
    mc = js("results/phase7c/model_check.json")
    v["haiku_7c"] = f"{sum(1 for r in mc['rows'] if r['correct'])}/{len(mc['rows'])}"
    v["total_usd"] = h["cost_usd"] + o["cost_usd"] + js("results/phase7b/verify_phase7b.json")["spend_usd"]["phase7_total"] + mc["usd"]
    fam = {"ACCOLADE", "PROPONENT", "ESSENTIO", "ALTRUA"}
    agg = {}
    with open(ROOT / "dashboards/snapshots/battery_brands.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            a = agg.setdefault(r["period"], [0, 0])
            a[1] += int(r["reports"])
            a[0] += int(r["reports"]) if r["family"] in fam else 0
    v["battery_before"], v["battery_after"] = (agg[k][0] / agg[k][1] for k in ("2025Q1-2025Q3", "2025Q4-2026Q3"))
    pb = js("dashboards/powerbi_evidence.json")
    v["powerbi_score"], v["powerbi_values"] = pb["score"], pb["items"]["C3"]["checks"]["values_compared"]
    return v


def allowed_strings(v: dict) -> set:
    out = set()
    for k, x in v.items():
        if isinstance(x, str):
            out.add(x)
            out.update(x.split("/"))
        elif isinstance(x, float) and (k in {"codebook", "codebook_lo", "codebook_hi", "embedding", "hit_rate", "base_rate", "battery_before", "battery_after"}):
            out.update({f"{x * 100:.0f}%", f"{x * 100:.1f}%"})
        elif k.endswith("usd"):
            out.add(f"${x:.2f}")
        elif k == "p":
            out.add(f"{x:.3f}")
        else:
            out.update({str(x), f"{x:,}"})
    if isinstance(v["graded"], int):
        out.update({f"{v['haiku']}/{v['graded']}", f"{v['opus']}/{v['graded']}", f"{v['haiku'] / v['graded'] * 100:.1f}%", f"{v['opus'] / v['graded'] * 100:.1f}%"})
    return out


STRUCTURAL = [
    r"\b\d{4}-\d{2}-\d{2}\b", r"\b20[12]\dQ[1-4]\b", r"\b20[12]\d-\d{2}\b", r"\b(20(1[89]|2[0-7]))(?:-(20(1[89]|2[0-7])))?\b",
    r"\b[Pp]hases? \d(?:[bc])?(?:-\d)?\b", r"\b\d[bc]\b", r"\b[QWCGTEDM]\d{1,2}\b",
    r"\b(?:Haiku|Opus|Sonnet) \d\.\d\b", r"\bPython 3\.1[234]\b", r"\bPostgreSQL 17\b", r"\bv\d+\.\d+\.\d+\b", r"\bbge-small-en-v1\.5\b", r"\b384 dimensions\b",
    r"\b5 device\b", r"\b4 Power BI pages\b", r"^\s*\d+\. ", r"^\|\s*\d[bc]? ",
    r"\bMay 2028\b",  # post hoc (2026-11-26): the author's expected graduation year, outside the 2018-2027 year rule
]


def numbers_in(text: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"https?://\S+", " ", text)
    lines = []
    for line in text.splitlines():
        for pat in STRUCTURAL:
            line = re.sub(pat, " ", line, flags=re.M)
        lines.append(line)
    text = "\n".join(lines)
    return re.findall(r"(?<![\w.\-/$])\$?\d[\d,]*(?:\.\d+)?%?(?:/\d+)?(?![\w\-])", text)


# ---------- checks ----------

def w1(v):
    import writeup.report_phase9 as rp
    fresh = rp.render()
    stale = [p for p, t in fresh.items() if (ROOT / p).read_bytes() != t.encode("utf-8")]
    ok_set = allowed_strings(v)
    unexplained = {p: sorted({n for n in numbers_in(rd(p)) if n.rstrip(",") not in ok_set}) for p in RESULTS_DOCS}
    unexplained = {p: n for p, n in unexplained.items() if n}
    return not stale and not unexplained, {"stale_generated": stale, "unexplained_numbers": unexplained}


def w2():
    hits = {}
    for p in STATUS_DOCS:
        t = rd(p)
        found = [pat for pat in SPEC["stale_patterns"] if re.search(pat, t, flags=re.I)]
        if found:
            hits[p] = found
    readme = rd("README.md")
    status = readme[readme.index("## Status"):].split("\n## ")[0]
    rows = {m.group(1): m.group(2) for m in re.finditer(r"^\| (\d)[bc]? [^|]*\| ([^|]*)", status, flags=re.M)}
    readme_ok = all(str(i) in rows for i in range(10)) and all(r.strip().startswith("Done") for r in re.findall(r"^\| \d[bc]? [^|]*\| ([^|]*)", status, flags=re.M))
    index_ok = "All phases 0-9 are done" in rd("docs/README.md")
    cm = rd("CLAUDE.md")
    cm = cm[cm.index("## Status"):].split("\n## ")[0]
    claude = {}
    for i in range(10):
        lines = [l for l in cm.splitlines() if re.match(rf"- Phase {i}\b", l)]
        claude[i] = bool(lines) and all(re.search(r"\bdone\b", l[:200], flags=re.I) for l in lines)
    ok = not hits and readme_ok and index_ok and all(claude.values())
    return ok, {"stale_patterns": hits, "readme_table_all_done": readme_ok, "docs_index_done": index_ok, "claude_md_phases_done": {k: v for k, v in claude.items() if not v} or "all"}


LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def all_md():
    return [p for p in tracked() if p.endswith(".md")]


def w3_code():
    files = set(tracked())
    broken = []
    for p in all_md():
        for target in LINK.findall(rd(p)):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            rel = (Path(p).parent / target.split("#")[0]).as_posix()
            norm = Path(rel).as_posix()
            parts = []
            for seg in norm.split("/"):
                if seg == "..":
                    parts and parts.pop()
                elif seg not in ("", "."):
                    parts.append(seg)
            norm = "/".join(parts)
            if norm not in files and not any(f.startswith(norm + "/") for f in files):
                broken.append(f"{p}: {target}")
    return not broken, {"broken_relative_links": broken}


def w4(v):
    t = rd("README.md")
    top = t[:t.index("\n## ")]
    paras = [b.strip() for b in top.split("\n\n")[1:] if b.strip()]
    first = paras[0] if paras else ""
    app = (ROOT / "dashboards/app_url.txt").read_text(encoding="utf-8").strip()
    need = {
        "one-line problem (<= 200 chars)": "\n" not in first and len(first) <= 200,
        "live app URL": app in top,
        "assistant headline": all(s in top for s in (f"{v['haiku']}", f"{v['opus']}", f"${v['haiku_usd']:.2f}", f"${v['opus_usd']:.2f}")),
        "early-warning headline": all(s in top for s in (f"{v['recall_hits']} of {v['recall_events']}", f"{v['base_rate'] * 100:.0f}%")),
        "battery headline": all(s in top for s in (f"{v['battery_before'] * 100:.1f}%", f"{v['battery_after'] * 100:.1f}%")),
        "technology line": "Built with" in top,
        "image": "![" in top,
    }
    return all(need.values()), need


def w5():
    sentence = SPEC["counts"]["sentence"]
    out = {}
    for p in RESULTS_DOCS:
        t = rd(p)
        opening = t[:t.index("\n## ")] if "\n## " in t else t
        if sentence in opening.lower():
            out[p] = True
            continue
        bad = []
        for para in re.split(r"\n\s*\n", t):
            rows = para.splitlines() if para.lstrip().startswith("|") else [para]
            for r in rows:
                if any(w in r.lower() for w in SPEC["counts"]["terms"]) and re.search(r"ris|fell|more|less|trend|increase|decrease|jump|surge", r, flags=re.I) and sentence not in r.lower():
                    bad.append(r[:80])
        out[p] = not bad
    both = all(sentence in rd(p).lower() for p in ("README.md", "docs/CASE_STUDY.md"))
    return all(out.values()) and both, {"per_doc": out, "readme_and_case_study_state_it": both}


def w6(v):
    res = {}
    for p in ("README.md", "docs/CASE_STUDY.md"):
        t = rd(p)
        low = t.lower()
        lim = re.search(r"^## [^\n]*Limitations[^\n]*\n(.*?)(?=^## |\Z)", t, flags=re.M | re.S)
        lim_text = re.sub(r"\s+", " ", lim.group(1).lower()) if lim else ""
        missing = [i for i in SPEC["honesty"]["limitations"] if i.lower() not in lim_text]
        res[p] = {"phase7_score": v["phase7"] in t, "withheld_n_of_48": f"{v['redteam_withheld']} of {v['redteam_n']}" in t,
                  "ai_labels_no_human": "from an ai" in low and "no human check" in low, "limitations_missing": missing}
    ok = all(r["phase7_score"] and r["withheld_n_of_48"] and r["ai_labels_no_human"] and not r["limitations_missing"] for r in res.values())
    return ok, res


def readme_block() -> str:
    t = rd("README.md")
    sec = t[t.index("## Check it without the data"):]
    return re.search(r"```bash\n(.*?)\n```", sec, flags=re.S).group(1)


def w7_code():
    ci = rd(".github/workflows/ci.yml")
    m = re.search(r"^  writeup-repro:\n(.*?)(?=^  \S|\Z)", ci, flags=re.M | re.S)
    if not m:
        return False, {"job": "writeup-repro not found"}
    run = re.search(r"- name: README block, verbatim\n\s+run: \|\n((?:\s{10}.*\n?)+)", m.group(1))
    cmds = "\n".join(l[10:] for l in run.group(1).rstrip("\n").splitlines()) if run else ""
    py = re.search(r'python-version: "([\d.]+)"', m.group(1))
    states = bool(py) and f"Python {py.group(1)}" in rd("README.md")
    return cmds == readme_block() and states, {"ci_equals_readme": cmds == readme_block(), "readme_states_ci_python": states}


def w9():
    files = tracked()
    idx = rd("docs/README.md")
    need = [p for p in files if p.startswith("docs/") and p.count("/") == 1 and p != "docs/README.md"] + [p for p in files if p.startswith("notebooks/") and p.endswith(".ipynb")]
    missing = []
    for p in need:
        target = p[5:] if p.startswith("docs/") else "../" + p
        descs = [l.split(f"]({target})", 1)[1].lstrip(": ") for l in idx.splitlines() if l.lstrip().startswith("- [") and f"]({target})" in l]
        if not any(len(d.split()) >= 5 for d in descs):
            missing.append(p)
    reserved = re.compile(r"@(?:[\w-]+\.)*(?:example|invalid|test)$|@example\.(?:com|org|net)$")
    test_globs = SPEC["privacy"]["test_data"]
    emails, phones = [], []
    for p in files:
        fp = ROOT / p
        if fp.suffix.lower() in {".png", ".pdf", ".npz", ".npy", ".gz", ".jpg"}:
            continue
        try:
            t = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for e in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", t):
            if not reserved.search(e) and e != "noreply@anthropic.com":
                emails.append(f"{p}: {e}")
        if not any(fnmatch.fnmatch(p, g) for g in test_globs):
            for ph in re.findall(r"(?<!\d)(?:\+?1[ .-])?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)", t):
                if not re.search(r"(?<!\d)555(?!\d)", ph):  # post hoc 2026-11-26: 555 numbers are fictional (spec post_hoc)
                    phones.append(f"{p}: {ph}")
    ok = not missing and not emails and not phones
    return ok, {"index_missing": missing, "emails": emails[:10], "phones": phones[:10]}


# ---------- network ----------

def network(evidence: dict) -> None:
    import requests

    ext = sorted({u for p in all_md() for u in LINK.findall(rd(p)) if u.startswith("http")} | {u for p in all_md() for u in re.findall(r"<(https?://[^>]+)>", rd(p))})
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (link check)"
    status = {}
    for u in ext:
        try:
            status[u] = s.get(u, timeout=30, allow_redirects=True).status_code
        except requests.RequestException as e:
            status[u] = f"error: {type(e).__name__}"
    exc = SPEC["links"]["exceptions"]
    bad = {u: c for u, c in status.items() if c != 200 and not (any(x["pattern"] in u for x in exc) and c in (200, 999))}
    evidence["W3_network"] = {"checked_utc": now(), "links": status, "failing": bad, "pass": not bad}
    app = (ROOT / "dashboards/app_url.txt").read_text(encoding="utf-8").strip()
    r = s.get(app, timeout=60, allow_redirects=True)
    evidence["W8_http"] = {"checked_utc": now(), "url": app, "status": r.status_code, "pass": r.status_code == 200}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv) -> int:
    ev_path = ROOT / "writeup/phase9_evidence.json"
    evidence = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
    if "--browser-check" in argv:
        got = argv[argv.index("--browser-check") + 1]
        want = js("dashboards/snapshots/manifest.json")["data_checksum"]
        evidence["W8_browser"] = {"checked_utc": now(), "method": "Claude desktop browser pane: Home and About pages opened on the public app",
                                  "about_checksum": got, "manifest_checksum": want, "pass": got == want}
        ev_path.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8", newline="\n")
        print("W8 browser", "PASS" if got == want else "FAIL")
        return 0
    if "--network" in argv:
        network(evidence)
        ev_path.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8", newline="\n")
    v = expected()
    res = {}
    for name, fn in (("W1", lambda: w1(v)), ("W2", w2), ("W3 code", w3_code), ("W4", lambda: w4(v)), ("W5", w5), ("W6", lambda: w6(v)), ("W7 code", w7_code), ("W9", w9)):
        ok, detail = fn()
        res[name] = {"pass": ok, "detail": detail}
    for k in ("W3_network", "W8_http", "W8_browser"):
        res[k] = {"pass": evidence.get(k, {}).get("pass"), "detail": "from writeup/phase9_evidence.json" if k in evidence else "not run yet"}
    (ROOT / "writeup/phase9_results.json").write_text(json.dumps({"checked_utc": now(), "checks": res}, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    code_ok = True
    for k, r in res.items():
        flag = "PASS" if r["pass"] else ("PENDING" if r["pass"] is None else "FAIL")
        print(f"{k:11} {flag}")
        if r["pass"] is False:
            print("            ", json.dumps(r["detail"], default=str)[:600])
        if k in ("W1", "W2", "W3 code", "W4", "W5", "W6", "W7 code", "W9") and not r["pass"]:
            code_ok = False
    return 0 if code_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
