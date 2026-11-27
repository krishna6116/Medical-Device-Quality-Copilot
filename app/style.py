"""Visual components for the app (v1.1). Plain HTML and CSS inside st.html: no external fonts, scripts or images.
Every number passed in comes from the snapshots; these functions only lay it out."""

from __future__ import annotations

import html

import streamlit as st

TEAL, NAVY, GREEN, AMBER, RED, GREY = "#0E6E8C", "#16212E", "#1E8E5A", "#B7791F", "#C0392B", "#5B6B7C"

CSS = f"""<style>
.block-container {{ padding-top: 4.2rem; max-width: 1180px; }}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{ white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }}
.st-key-model_tile [data-testid="stMetricValue"] {{ padding-top: 0.6rem; }}
.st-key-model_tile [data-testid="stMetricValue"], .st-key-model_tile [data-testid="stMetricValue"] * {{ font-size: 1.3rem !important; line-height: 1.35 !important; white-space: normal !important; overflow: visible !important; text-overflow: clip !important; overflow-wrap: anywhere; }}
.hero, .cards, .score, .card {{ box-sizing: border-box; min-width: 0; }}
.hero {{ overflow-wrap: anywhere; background: linear-gradient(135deg, {NAVY} 0%, {TEAL} 100%); color: #fff; border-radius: 18px; padding: 30px 34px 26px; margin-bottom: 18px; }}
.hero h1 {{ color: #fff; font-size: 2.15rem; line-height: 1.15; margin: 0 0 8px; padding: 0; }}
.hero p {{ color: #DCEBF2; font-size: 1.06rem; margin: 0 0 14px; max-width: 760px; }}
.pill {{ display: inline-block; border-radius: 999px; padding: 3px 11px; margin: 0 6px 6px 0; font-size: 0.80rem; font-weight: 600; }}
.hero .pill {{ background: rgba(255,255,255,0.14); color: #fff; border: 1px solid rgba(255,255,255,0.28); }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 14px; margin: 4px 0 18px; }}
.card {{ background: #fff; border: 1px solid #E1E8EE; border-radius: 14px; padding: 16px 18px; box-shadow: 0 1px 3px rgba(22,33,46,0.06); }}
.card .k {{ color: {GREY}; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }}
.card .v {{ color: {NAVY}; font-size: 1.85rem; font-weight: 700; line-height: 1.2; margin: 4px 0 2px; }}
.card .s {{ color: {GREY}; font-size: 0.86rem; }}
.card.alert {{ border-left: 5px solid {AMBER}; }}
.card.good {{ border-left: 5px solid {GREEN}; }}
.card.info {{ border-left: 5px solid {TEAL}; }}
.step {{ display: flex; gap: 14px; align-items: flex-start; margin: 22px 0 6px; }}
.step .n {{ flex: 0 0 34px; height: 34px; border-radius: 50%; background: {TEAL}; color: #fff; font-weight: 700; display: flex; align-items: center; justify-content: center; }}
.step .t {{ font-size: 1.22rem; font-weight: 700; color: {NAVY}; padding-top: 3px; }}
.score {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; }}
.score .row {{ border: 1px solid #E1E8EE; border-radius: 12px; padding: 12px 14px; background: #fff; }}
.score .row b {{ color: {NAVY}; }}
.score .row .d {{ color: {GREY}; font-size: 0.88rem; margin-top: 3px; }}
.ok {{ background: #E3F4EC; color: {GREEN}; }} .warn {{ background: #FCF1DE; color: {AMBER}; }} .bad {{ background: #FBE5E2; color: {RED}; }} .neutral {{ background: #E7F0F5; color: {TEAL}; }}
.quote {{ border-left: 4px solid {TEAL}; background: #F7FAFC; padding: 10px 14px; border-radius: 0 10px 10px 0; color: {NAVY}; }}
@media (max-width: 640px) {{
  .block-container {{ padding-top: 3.4rem; }}
  .hero {{ padding: 20px 16px; }} .hero h1 {{ font-size: 1.45rem; }} .hero p {{ font-size: 0.95rem; }}
  .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }} .card {{ padding: 12px 12px; }} .card .v {{ font-size: 1.35rem; }}
  .score {{ grid-template-columns: minmax(0, 1fr); }}
  [data-testid="stTable"] table {{ font-size: 0.78rem; }}
}}
</style>"""


def esc(x) -> str:
    return html.escape(str(x))


def css() -> None:
    st.html(CSS)


def pills(items: list[tuple[str, str]]) -> str:
    return "".join(f'<span class="pill {esc(kind)}">{esc(text)}</span>' for text, kind in items)


def hero(title: str, text: str, tags: list[str]) -> None:
    st.html(f'<div class="hero"><h1>{esc(title)}</h1><p>{esc(text)}</p>{pills([(t, "") for t in tags])}</div>')


def cards(items: list[dict]) -> None:
    """items: {"k": label, "v": value, "s": small text, "tone": good|alert|info|''}"""
    st.html('<div class="cards">' + "".join(
        f'<div class="card {esc(i.get("tone", ""))}"><div class="k">{esc(i["k"])}</div><div class="v">{esc(i["v"])}</div>'
        f'<div class="s">{esc(i.get("s", ""))}</div></div>' for i in items) + "</div>")


def step(n: int, title: str) -> None:
    st.html(f'<div class="step"><div class="n">{n}</div><div class="t">{esc(title)}</div></div>')


def scoreboard(rows: list[dict]) -> None:
    """rows: {"name", "result", "tone": ok|warn|bad|neutral, "detail"}"""
    st.html('<div class="score">' + "".join(
        f'<div class="row"><b>{esc(r["name"])}</b> <span class="pill {esc(r["tone"])}">{esc(r["result"])}</span><div class="d">{esc(r["detail"])}</div></div>'
        for r in rows) + "</div>")


def quote(text: str) -> None:
    st.html(f'<div class="quote">{esc(text)}</div>')
