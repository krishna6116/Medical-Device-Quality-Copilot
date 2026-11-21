"""Phase 1 exploratory analysis: answer the pre-registered questions Q1-Q8 from the raw files.

Run:  python -m mdqc.eda
Writes results/phase1/eda_summary.json (every number the findings doc quotes),
results/phase1/monthly_counts.csv and figures in docs/figures/phase1/.

Definitions (the verifier, mdqc/verify_phase1.py, re-implements each one independently):
- one report = one distinct mdr_report_key inside a code's file (first copy kept);
- manufacturer = manufacturer_d_name of the first device entry whose product code is the
  searched code, stripped and upper-cased; '(blank)' if missing;
- narrative = all mdr_text[].text joined with a single space; length in characters;
- event type = event_type stripped; '' becomes '(blank)';
- problem term count = number of reports listing the term (openFDA repeats terms inside one report,
  so each term counts once per report; corrected post hoc after a cross-check with openFDA's own counts);
- recall year = first 4 digits of event_date_initiated; missing or before 1976 = invalid (post hoc rule,
  added after the verifier found '0013-11-26'), counted separately and left out of by-year counts;
- Q9 (post hoc) = the 3 manufacturers with most reports in a code (ties by name), their monthly counts,
  yearly totals, and their counts in the code's busiest month;
- lag = date_received - date_of_event in days, when both are valid YYYYMMDD dates;
- percentiles use linear interpolation between order statistics (numpy's default).
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCOPE = json.loads((ROOT / "config" / "scope.json").read_text(encoding="utf-8"))
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results" / "phase1"
FIG = ROOT / "docs" / "figures" / "phase1"
CODES = list(SCOPE["product_codes"])
MIN_RECALL_YEAR = 1976  # FDA device regulation (Medical Device Amendments) starts in 1976; earlier years are typos
CONTACT_FIELDS = ["manufacturer_contact_f_name", "manufacturer_contact_l_name",
                  "manufacturer_contact_phone_number"]


def read_jsonl_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def parse_date(s) -> date | None:
    if not isinstance(s, str) or len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return None


def report_row(rec: dict, code: str) -> dict:
    devices = rec.get("device") or []
    mine = next((d for d in devices if d.get("device_report_product_code") == code), {})
    maker = (mine.get("manufacturer_d_name") or "").strip().upper() or "(blank)"
    texts = [t.get("text") or "" for t in (rec.get("mdr_text") or [])]
    narrative = " ".join(texts)
    received, occurred = parse_date(rec.get("date_received")), parse_date(rec.get("date_of_event"))
    codes_listed = {d.get("device_report_product_code") for d in devices}
    return {
        "code": code,
        "key": rec.get("mdr_report_key"),
        "date_received": rec.get("date_received"),
        "month": f"{rec['date_received'][:4]}-{rec['date_received'][4:6]}",
        "event_type": (rec.get("event_type") or "").strip() or "(blank)",
        "manufacturer": maker,
        "has_narrative": bool(narrative.strip()),
        "narrative_len": len(narrative),
        "lag_days": (received - occurred).days if received and occurred else None,
        "n_devices": len(devices),
        "other_scope_codes": sorted(c for c in codes_listed if c in CODES and c != code),
        "code_listed": code in codes_listed,
        "has_contact": any((rec.get(f) or "").strip() for f in CONTACT_FIELDS),
        "problems": rec.get("product_problems") or [],
    }


def load_reports(raw: Path = RAW) -> pd.DataFrame:
    rows, seen = [], set()
    for code in CODES:
        for rec in read_jsonl_gz(raw / f"events_{code}.jsonl.gz"):
            k = (code, rec.get("mdr_report_key"))
            if k in seen:
                continue
            seen.add(k)
            rows.append(report_row(rec, code))
    return pd.DataFrame(rows)


def load_recalls(raw: Path = RAW) -> pd.DataFrame:
    rows = []
    for code in CODES:
        for rec in read_jsonl_gz(raw / f"recalls_{code}.jsonl.gz"):
            d = rec.get("event_date_initiated") or ""
            year = int(d[:4]) if d[:4].isdigit() else None
            if year is not None and year < MIN_RECALL_YEAR:
                year = None  # e.g. '0013-11-26' (a typo for 2013): invalid, counted separately
            rows.append({"code": code, "year": year,
                         "root_cause": (rec.get("root_cause_description") or "").strip() or "(blank)",
                         "res_event_number": rec.get("res_event_number")})
    return pd.DataFrame(rows)


def pct(values, q: float) -> float | None:
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    return None if arr.size == 0 else round(float(np.percentile(arr, q)), 1)


def all_months() -> list[str]:
    w = SCOPE["event_window"]
    y0, y1 = int(w["from"][:4]), int(w["to"][:4])
    return [f"{y}-{m:02d}" for y in range(y0, y1 + 1) for m in range(1, 13)]


def summarize(rep: pd.DataFrame, rc: pd.DataFrame) -> dict:
    months = all_months()
    s: dict = {"codes": CODES, "months": months, "per_code": {}, "overall": {}}
    for code in CODES:
        r = rep[rep.code == code]
        monthly = r.month.value_counts().reindex(months, fill_value=0)
        med = float(np.median(monthly.values))
        spikes = {m: int(v) for m, v in monthly.items() if v > 3 * med}
        makers = r.manufacturer.value_counts()
        probs = Counter(p for ps in r.problems for p in set(ps))  # reports per term
        lags = [v for v in r.lag_days if v is not None and not pd.isna(v)]
        nonneg = [v for v in lags if v >= 0]
        c_rc = rc[rc.code == code]
        w0, w1 = int(SCOPE["event_window"]["from"][:4]), int(SCOPE["event_window"]["to"][:4])
        s["per_code"][code] = {
            "reports": int(len(r)),
            "q1_monthly_median": med,
            "q1_monthly_max": int(monthly.max()),
            "q1_monthly_max_month": str(monthly.idxmax()),
            "q1_spike_months_over_3x_median": spikes,
            "q2_event_type": {k: int(v) for k, v in r.event_type.value_counts().items()},
            "q3_top_problems": [[p, int(n)] for p, n in sorted(probs.items(), key=lambda x: (-x[1], x[0]))[:10]],
            "q3_reports_without_problem_terms": int(sum(1 for ps in r.problems if not ps)),
            "q4_top_manufacturers": [[m, int(n)] for m, n in sorted(makers.items(), key=lambda x: (-x[1], x[0]))[:5]],
            "q4_top_manufacturer_share": round(float(makers.max()) / len(r), 4),
            "q4_distinct_manufacturers": int(makers.size),
            "q5_share_with_narrative": round(float(r.has_narrative.mean()), 4),
            "q5_narrative_len_median": pct(r.narrative_len[r.has_narrative], 50),
            "q5_narrative_len_p90": pct(r.narrative_len[r.has_narrative], 90),
            "q6_recalls": int(len(c_rc)),
            "q6_recall_events_distinct": int(c_rc.res_event_number.nunique()),
            "q6_recalls_in_window": int(((c_rc.year >= w0) & (c_rc.year <= w1)).sum()),
            "q6_recalls_invalid_initiation_date": int(c_rc.year.isna().sum()),
            "q6_recalls_by_year": {str(int(k)): int(v) for k, v in c_rc.year.dropna().value_counts().sort_index().items()},
            "q6_recalls_by_root_cause": {k: int(v) for k, v in sorted(c_rc.root_cause.value_counts().items(), key=lambda x: (-x[1], x[0]))},
            "q7_lag_reports_with_both_dates": int(len(lags)),
            "q7_lag_negative": int(len(lags) - len(nonneg)),
            "q7_lag_median_days": pct(nonneg, 50),
            "q7_lag_p90_days": pct(nonneg, 90),
            "q8_multi_device_reports": int((r.n_devices > 1).sum()),
            "q8_listed_under_other_scope_code": int(r.other_scope_codes.map(bool).sum()),
            "c3_code_not_in_device_list": int((~r.code_listed).sum()),
            "c3_outside_window": int(((r.date_received < SCOPE["event_window"]["from"]) |
                                      (r.date_received > SCOPE["event_window"]["to"])).sum()),
            "c7_reports_with_contact_fields": int(r.has_contact.sum()),
        }
        # Q9 (post hoc, added on re-check): monthly trend of the 3 largest manufacturers per code
        top3 = [m for m, _ in sorted(makers.items(), key=lambda x: (-x[1], x[0]))[:3]]
        busiest = str(monthly.idxmax())
        q9_monthly, q9_year = {}, {}
        for m in top3:
            rm = r[r.manufacturer == m]
            series = rm.month.value_counts().reindex(months, fill_value=0)
            q9_monthly[m] = [int(v) for v in series.values]
            q9_year[m] = {y: int(series[[x for x in months if x.startswith(y)]].sum())
                          for y in sorted({x[:4] for x in months})}
        s["per_code"][code].update({
            "q9_top3_monthly": q9_monthly,
            "q9_top3_by_year": q9_year,
            "q9_busiest_month_by_maker": {m: q9_monthly[m][months.index(busiest)] for m in top3},
        })
    s["overall"] = {
        "reports": int(len(rep)),
        "distinct_report_keys_across_codes": int(rep.key.nunique()),
        "recalls": int(len(rc)),
        "event_type": {k: int(v) for k, v in rep.event_type.value_counts().items()},
        "reports_with_contact_fields": int(rep.has_contact.sum()),
    }
    return s


# ---- figures (static PNGs for the findings doc; reference palette, light surface) ----
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def figures(s: dict, rep: pd.DataFrame) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG.mkdir(parents=True, exist_ok=True)
    names = {c: SCOPE["product_codes"][c]["family"] for c in CODES}
    out = []

    # 1. Monthly volume: small multiples, own y-scale per code (volumes differ 17x)
    months = s["months"]
    fig, axes = plt.subplots(len(CODES), 1, figsize=(8, 1.7 * len(CODES)), sharex=True, facecolor=SURFACE)
    x = np.arange(len(months))
    for ax, code in zip(axes, CODES):
        counts = rep[rep.code == code].month.value_counts().reindex(months, fill_value=0).values
        _style(ax)
        ax.plot(x, counts, color=SERIES[0], linewidth=2)
        ax.set_title(f"{code} ({names[code]}): reports received per month", loc="left", fontsize=9, color=INK)
        ax.set_ylim(bottom=0)
    axes[-1].set_xticks(x[::6], [months[i] for i in range(0, len(months), 6)])
    fig.tight_layout()
    p = FIG / "monthly_reports.png"
    fig.savefig(p, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    out.append(p.name)

    # 2. Event type mix: 100% horizontal stacked bars, legend + labels on large segments
    types = ["Malfunction", "Injury", "Death", "Other"]
    fig, ax = plt.subplots(figsize=(8, 3.2), facecolor=SURFACE)
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.grid(axis="y", visible=False)
    for i, code in enumerate(CODES):
        et = s["per_code"][code]["q2_event_type"]
        total = sum(et.values())
        shares = [et.get(t, 0) / total for t in types[:3]]
        shares.append(1 - sum(shares))  # Other + blank
        left = 0.0
        for j, (t, v) in enumerate(zip(types, shares)):
            ax.barh(i, v, left=left, color=SERIES[j], edgecolor=SURFACE, linewidth=1.5, height=0.6,
                    label=t if i == 0 else None)
            if v >= 0.08:
                ax.text(left + v / 2, i, f"{v:.0%}", ha="center", va="center", fontsize=8, color=INK)
            left += v
    ax.set_yticks(range(len(CODES)), [f"{c} ({names[c]})" for c in CODES], color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title("Event type of each report (Other includes blank)", loc="left", fontsize=10, color=INK)
    ax.legend(ncol=4, frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12),
              labelcolor=INK2)
    fig.tight_layout()
    p = FIG / "event_type_mix.png"
    fig.savefig(p, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    out.append(p.name)

    # 2b. Q9: top-3 manufacturers per code, monthly (small multiples; 3 series -> legend in each panel)
    fig, axes = plt.subplots(len(CODES), 1, figsize=(8, 2.2 * len(CODES)), sharex=True, facecolor=SURFACE)
    for ax, code in zip(axes, CODES):
        _style(ax)
        for j, (maker, series) in enumerate(s["per_code"][code]["q9_top3_monthly"].items()):
            ax.plot(x, series, color=SERIES[j], linewidth=2, label=maker.title()[:38])
        ax.set_title(f"{code} ({names[code]}): reports per month, 3 largest manufacturers", loc="left",
                     fontsize=9, color=INK, pad=18)
        ax.set_ylim(bottom=0)
        ax.legend(frameon=False, fontsize=7, loc="lower left", bbox_to_anchor=(0, 0.99), labelcolor=INK2,
                  ncol=3, borderaxespad=0, handlelength=1.5)
    axes[-1].set_xticks(x[::6], [months[i] for i in range(0, len(months), 6)])
    fig.tight_layout()
    p = FIG / "manufacturer_trends.png"
    fig.savefig(p, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    out.append(p.name)

    # 3. Recalls per year: small multiples, report window shaded
    years = sorted({int(y) for c in CODES for y in s["per_code"][c]["q6_recalls_by_year"]})
    fig, axes = plt.subplots(len(CODES), 1, figsize=(8, 1.6 * len(CODES)), sharex=True, facecolor=SURFACE)
    w0, w1 = int(SCOPE["event_window"]["from"][:4]), int(SCOPE["event_window"]["to"][:4])
    for ax, code in zip(axes, CODES):
        by = s["per_code"][code]["q6_recalls_by_year"]
        _style(ax)
        ax.axvspan(w0 - 0.5, w1 + 0.5, color="#eef0f2", zorder=0)
        ax.bar(years, [by.get(str(y), 0) for y in years], color=SERIES[0], width=0.7)
        ax.set_title(f"{code} ({names[code]}): recalls initiated per year (shaded = report window)",
                     loc="left", fontsize=9, color=INK)
    fig.tight_layout()
    p = FIG / "recalls_per_year.png"
    fig.savefig(p, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    out.append(p.name)
    return out


def main(raw: Path = RAW, out: Path = OUT, make_figures: bool = True) -> dict:
    rep, rc = load_reports(raw), load_recalls(raw)
    s = summarize(rep, rc)
    s["figures"] = figures(s, rep) if make_figures else []
    out.mkdir(parents=True, exist_ok=True)
    (out / "eda_summary.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8", newline="\n")
    monthly = (rep.groupby(["code", "month"]).size().unstack(0).reindex(s["months"], fill_value=0)
               .fillna(0).astype(int)[CODES])
    monthly.to_csv(out / "monthly_counts.csv", lineterminator="\n")
    print(f"{s['overall']['reports']:,} reports, {s['overall']['recalls']:,} recalls -> {out}")
    return s


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Phase 1 EDA")
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args()
    main(a.raw, a.out, not a.no_figures)
