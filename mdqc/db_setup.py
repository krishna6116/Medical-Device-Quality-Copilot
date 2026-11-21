"""One-time database setup: create database `mdqc` and its own login `mdqc_app`.

Run:  python -m mdqc.db_setup [--admin-env PATH]

Why a separate database and login: this project must not share tables or credentials with any
other project. An existing admin connection (by default the DATABASE_URL in the predictive
maintenance project's .env) is used ONCE to create the login and the database; the new login gets
a random password that is written only to this project's .env (git-ignored) and never printed.
Re-running is safe: it re-creates nothing that exists and rotates the app password.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

from mdqc.setup_env import ENV, set_values

DEFAULT_ADMIN_ENV = Path.home() / "Documents" / "Predictive-Maintenance-OEE" / ".env"
DB, ROLE = "mdqc", "mdqc_app"


def plain_url(url: str) -> str:
    """SQLAlchemy-style 'postgresql+psycopg://' -> libpq 'postgresql://'."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def main(admin_env: Path) -> None:
    admin_url = dotenv_values(admin_env).get("DATABASE_URL")
    if not admin_url:
        raise SystemExit(f"No DATABASE_URL in {admin_env}")
    password = secrets.token_urlsafe(24)  # URL-safe characters only, so it needs no escaping
    with psycopg.connect(plain_url(admin_url), autocommit=True) as con:
        info = con.info
        host, port = info.host or "localhost", info.port or 5432
        exists = con.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        con.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(ROLE), sql.Literal(password)))
        if not con.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,)).fetchone():
            con.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(DB), sql.Identifier(ROLE)))
            print(f"created database {DB}")
        else:
            print(f"database {DB} already exists")
        print(f"{'updated' if exists else 'created'} login {ROLE} (password saved to .env, not shown)")
    url = f"postgresql://{ROLE}:{password}@{host}:{port}/{DB}"
    set_values(ENV, {"DATABASE_URL": url})
    with psycopg.connect(url) as con:  # prove the new login works
        who = con.execute("SELECT current_user, current_database(), version()").fetchone()
    print(f"connected as {who[0]} to {who[1]} ({who[2].split(',')[0]})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Create the mdqc database and login")
    ap.add_argument("--admin-env", type=Path, default=DEFAULT_ADMIN_ENV)
    main(ap.parse_args().admin_env)
