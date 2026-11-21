"""Write API keys into .env with a hidden prompt (nothing is echoed, printed or committed).

Run:  python -m mdqc.setup_env              asks for the openFDA key (optional, free)
      python -m mdqc.setup_env --anthropic  also asks for the Claude API key (Phase 4 onwards)

Why: keys must never live in code, notebooks, shell history or git. `.env` is git-ignored
(a test checks it), and `python-dotenv` loads it when a script needs a key.
The openFDA key is optional: Phase 1 downloaded everything without one. With a key, openFDA
allows 120,000 requests a day instead of 1,000 and pages of 1,000 records instead of 999.
Get one (with your email address) at https://open.fda.gov/apis/authentication/.
Press Enter at a prompt to keep the current value.
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"


def set_values(path: Path, values: dict[str, str]) -> None:
    """Set KEY=value lines in a .env file, keeping every other line and comment as it was."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in values and not line.lstrip().startswith("#"):
            out.append(f"{key}={values[key]}")
            done.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in done]
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def check_openfda_key(key: str) -> str:
    """One tiny request with the key; returns a short status (never the key)."""
    from mdqc.openfda import OpenFDAClient
    try:
        data, _ = OpenFDAClient(api_key=key, max_attempts=2).get("classification", limit=1)
        return "works" if data.get("results") else "accepted, but returned no data"
    except Exception as exc:  # noqa: BLE001 - report any failure without showing the key
        return f"did not work ({type(exc).__name__})"


def main(anthropic: bool, path: Path = ENV) -> None:
    values = {}
    key = getpass.getpass("openFDA API key (hidden; Enter to skip): ").strip()
    if key:
        values["OPENFDA_API_KEY"] = key
        print("openFDA key check:", check_openfda_key(key))
    if anthropic:
        ak = getpass.getpass("Anthropic API key (hidden; Enter to skip): ").strip()
        if ak:
            values["ANTHROPIC_API_KEY"] = ak
    if not values:
        print("Nothing changed.")
        return
    set_values(path, values)
    print(f"Saved {', '.join(sorted(values))} to {path.name} (git-ignored).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Write API keys to .env with a hidden prompt")
    ap.add_argument("--anthropic", action="store_true", help="also ask for the Claude API key")
    main(ap.parse_args().anthropic)
