#!/usr/bin/env python3
"""Against a real, disposable PostgreSQL: `pythia-pg check` works, and the
read-only session it opens is refused a write by the server itself.

Never point this at a shared database. It is skipped unless
PYTHIA_PG_LIVE_HOST is set; CI sets it for a postgres service container.

    PYTHIA_PG_LIVE_HOST=127.0.0.1 PYTHIA_PG_LIVE_PORT=5432 \
    PYTHIA_PG_LIVE_DB=postgres PYTHIA_PG_LIVE_USER=postgres \
    PYTHIA_PG_LIVE_PASSWORD=... python tests/live_check.py
"""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile


def main():
    env = os.environ
    if not env.get("PYTHIA_PG_LIVE_HOST"):
        print("SKIP live check: PYTHIA_PG_LIVE_HOST is not set")
        return
    import psycopg

    from pythia_core.queries import run_query
    from pythia_postgres import cli
    from pythia_postgres.engine import PostgresEngine

    entry = {"host": env["PYTHIA_PG_LIVE_HOST"],
             "port": int(env.get("PYTHIA_PG_LIVE_PORT") or 5432),
             "dbname": env.get("PYTHIA_PG_LIVE_DB") or "postgres",
             "user": env.get("PYTHIA_PG_LIVE_USER") or "postgres",
             "password": env.get("PYTHIA_PG_LIVE_PASSWORD") or "",
             "schema": "public"}

    # 1. the command, end to end
    keep = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / ".pythia" / "postgres" / "connections.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"live": entry}), encoding="utf-8")
        if os.name == "posix":
            os.chmod(path, 0o600)
        os.chdir(td)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["check", "--json"])
        finally:
            os.chdir(keep)
    doc = json.loads(out.getvalue())
    assert code == 0 and doc["ok"], doc
    server = next(r["VALUE"] for r in doc["rows"] if r["ITEM"] == "server")
    assert server.startswith("PostgreSQL "), server
    print(f"PASS check: {server}; current schema "
          f"{next(r['VALUE'] for r in doc['rows'] if r['ITEM'] == 'current_schema')}")

    # 2. the second line of defence is the server's, not ours
    e = PostgresEngine()
    conn = e.session(e.connect(entry), True)
    try:
        run_query(conn, "create temporary table pythia_probe (x int)")
    except psycopg.errors.ReadOnlySqlTransaction:
        print("PASS read-only: the server refused a write in a check session")
    else:
        sys.exit("FAIL read-only: a write ran inside a read-only session")
    finally:
        e.close(conn)
    print("OK")


if __name__ == "__main__":
    main()
