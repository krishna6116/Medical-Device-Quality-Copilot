"""Phase 8 part 2: database side of the Power BI report.

Run:  python -m dashboards.powerbi_setup --views    create schema powerbi (views over core_all) with the app login
      python -m dashboards.powerbi_setup --login    YOU run this: creates the read-only login mdqc_powerbi_ro and tests it

--login asks at hidden prompts for a PostgreSQL admin login (one allowed to create logins, e.g. postgres) and for the new
login's password, twice. Nothing is printed, logged or saved: the admin password is used once, the new password only by
Power BI (which keeps it in the Windows credential store). It then checks criterion C1 and writes dashboards/powerbi_login_check.json.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE, DB = "mdqc_powerbi_ro", "mdqc"


def views() -> None:
    import psycopg
    from dotenv import load_dotenv
    from psycopg import sql

    load_dotenv(ROOT / ".env")
    book = json.loads((ROOT / "config" / "failure_modes.json").read_text(encoding="utf-8"))
    modes = [(m, d["definition"]) for f in book["families"].values() for m, d in f["modes"].items()]
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        con.execute((ROOT / "dashboards" / "powerbi_views.sql").read_text(encoding="utf-8"))
        rows = sql.SQL(", ").join(sql.SQL("({}, {})").format(sql.Literal(m), sql.Literal(d)) for m, d in modes)
        con.execute(sql.SQL("CREATE VIEW powerbi.failure_modes AS SELECT * FROM (VALUES {}) v(failure_mode, definition)").format(rows))
        n = {v: con.execute(f"SELECT count(*) FROM powerbi.{v}").fetchone()[0] for v in ("products", "reports", "failure_modes", "recalls", "battery_families")}
        con.commit()
    print("schema powerbi:", n)


def login() -> None:
    import psycopg
    from psycopg import sql

    print(f"Creates the read-only login {ROLE} for Power BI. Nothing you type is shown or saved.")
    admin_user = input("PostgreSQL admin login name [postgres]: ").strip() or "postgres"
    admin_pw = getpass(f"Password for {admin_user} (hidden): ")
    pw = getpass(f"New password for {ROLE} (hidden, 12+ characters): ")
    if len(pw) < 12 or pw != getpass("Repeat it (hidden): "):
        raise SystemExit("Passwords differ or are shorter than 12 characters; nothing changed.")
    with psycopg.connect(host="localhost", port=5432, dbname=DB, user=admin_user, password=admin_pw, autocommit=True) as con:
        verb = "ALTER" if con.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,)).fetchone() else "CREATE"
        con.execute(sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}").format(sql.Identifier(ROLE), sql.Literal(pw)))
        con.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(ROLE)))
        con.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(DB), sql.Identifier(ROLE)))
        con.execute(sql.SQL("GRANT USAGE ON SCHEMA powerbi TO {0}; GRANT SELECT ON ALL TABLES IN SCHEMA powerbi TO {0}").format(sql.Identifier(ROLE)))
    del admin_pw
    print(f"{'Updated' if verb == 'ALTER' else 'Created'} {ROLE}. Testing it...")
    checks = {}
    with psycopg.connect(host="localhost", port=5432, dbname=DB, user=ROLE, password=pw, autocommit=True) as ro:
        def refused(stmt):
            try:
                ro.execute(stmt)
                return False
            except psycopg.Error:
                return True
        checks["reads powerbi.reports"] = ro.execute("SELECT count(*) FROM powerbi.reports").fetchone()[0] > 0
        for s in ("core.fact_report", "core_all.fact_report", "analytics.report_failure_mode", "analytics_all.signal_month", "memory.memory_item"):
            checks[f"cannot read {s}"] = refused(f"SELECT 1 FROM {s} LIMIT 1")
        checks["cannot create a table"] = refused("CREATE TABLE powerbi.x (a int)")
        checks["cannot create a schema"] = refused("CREATE SCHEMA x")
        checks["cannot turn read-only off and write"] = refused("SET default_transaction_read_only = off; CREATE TABLE public.x (a int)")
        checks["cannot delete through a view"] = refused("DELETE FROM powerbi.recalls")
        checks["session is read-only"] = ro.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
    del pw
    out = {"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "role": ROLE, "checks": checks, "all_pass": all(checks.values()),
           "note": "passwords were typed at hidden prompts and are not stored anywhere by this script"}
    (ROOT / "dashboards" / "powerbi_login_check.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("All checks pass." if out["all_pass"] else "Some checks FAILED: tell Claude.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--views", action="store_true")
    g.add_argument("--login", action="store_true")
    a = ap.parse_args()
    views() if a.views else login()
