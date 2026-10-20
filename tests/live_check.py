#!/usr/bin/env python3
"""Against a real, disposable PostgreSQL: every pythia-pg command, end to end.

1. `check` works, and the read-only session it opens is refused a write by
   the server itself.
2. With PYTHIA_PG_LIVE_DISPOSABLE=1 only: tests/fixtures/app_owner.sql is
   loaded (it DROPS and recreates the app_owner and reporting schemas), and
   every read command is checked against it — including a DDL round trip:
   drop the table, run the DDL pythia-pg rebuilt, rebuild it again, compare.
3. With PYTHIA_PG_LIVE_PLPGSQL_CHECK=1 as well: plpgsql_check is installed
   for the run (the server must have the package) and `errors` is checked
   with it, then dropped again.

Never point this at a shared database. Skipped unless PYTHIA_PG_LIVE_HOST is
set; CI sets all three for a postgres service container.

    PYTHIA_PG_LIVE_HOST=127.0.0.1 PYTHIA_PG_LIVE_PORT=5432 \
    PYTHIA_PG_LIVE_DB=postgres PYTHIA_PG_LIVE_USER=postgres \
    PYTHIA_PG_LIVE_PASSWORD=... PYTHIA_PG_LIVE_DISPOSABLE=1 \
    python tests/live_check.py
"""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "app_owner.sql"


def entry_from_env(schema):
    env = os.environ
    return {"host": env["PYTHIA_PG_LIVE_HOST"],
            "port": int(env.get("PYTHIA_PG_LIVE_PORT") or 5432),
            "dbname": env.get("PYTHIA_PG_LIVE_DB") or "postgres",
            "user": env.get("PYTHIA_PG_LIVE_USER") or "postgres",
            "password": env.get("PYTHIA_PG_LIVE_PASSWORD") or "",
            "schema": schema}


def pg(entry, *argv):
    """Run pythia-pg in-process against entry; the parsed --json document."""
    from pythia_postgres import cli
    keep = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / ".pythia" / "postgres" / "connections.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"live": entry}), encoding="utf-8")
        if os.name == "posix":
            os.chmod(path, 0o600)
        os.chdir(td)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(list(argv) + ["--json"])
        finally:
            os.chdir(keep)
    assert code == 0, (argv, code)
    return json.loads(out.getvalue())


def admin(entry):
    """A plain autocommit connection for the fixture — the test's own setup,
    never pythia-pg's write path."""
    import psycopg
    kw = {k: entry[k] for k in ("host", "port", "dbname", "user", "password")}
    return psycopg.connect(autocommit=True, **kw)


def ok(what):
    print(f"PASS {what}")


def check_connect(entry):
    import psycopg

    from pythia_core.queries import run_query
    from pythia_postgres.engine import PostgresEngine
    doc = pg(entry, "check")
    server = next(r["VALUE"] for r in doc["rows"] if r["ITEM"] == "server")
    assert server.startswith("PostgreSQL "), server
    ok(f"check: {server}")
    e = PostgresEngine()
    conn = e.session(e.connect(entry), True)
    try:
        run_query(conn, "create temporary table pythia_probe (x int)")
    except psycopg.errors.ReadOnlySqlTransaction:
        ok("read-only: the server refused a write in a check session")
    else:
        sys.exit("FAIL read-only: a write ran inside a read-only session")
    finally:
        e.close(conn)


def names(doc, col="NAME"):
    return [r[col] for r in doc["rows"]]


def tree(doc):
    return {(r["SCHEMA"], r["NAME"].split("(")[0], r["HOW"]) for r in doc["rows"]}


def check_reads(entry, with_plpgsql_check):
    with admin(entry) as conn:
        conn.execute(FIXTURE.read_text(encoding="utf-8"))
    ok("fixture loaded")

    assert {"t_order", "t_order_line", "t_order_audit"} <= set(
        names(pg(entry, "ls", "t_order%")))
    ok("ls")
    src = pg(entry, "src", "F_ORDER_TOTAL")
    assert any("from t_order where" in r["TEXT"] for r in src["rows"]), src
    ok("src (an unquoted name folds to lower case)")
    assert names(pg(entry, "cols", "t_order"), "COLUMN_NAME") == [
        "id", "status", "total", "created"]
    ok("cols")
    ddl = pg(entry, "ddl", "t_order")["rows"][0]["DDL"]
    for piece in ("CREATE TABLE app_owner.t_order (",
                  "CONSTRAINT t_order_pkey PRIMARY KEY (id)",
                  "CREATE INDEX ix_order_status",
                  "CREATE TRIGGER trg_order_audit",
                  "COMMENT ON COLUMN app_owner.t_order.status IS 'DRAFT until paid';"):
        assert piece in ddl, (piece, ddl)
    ok("ddl")
    hits = {(r["NAME"].split("(")[0], r["LINE"]) for r in pg(entry, "grep", "T_ORDER WHERE")["rows"]}
    assert ("f_order_total", 8) in hits, hits
    ok("grep (line numbers as src prints them)")

    impact = pg(entry, "impact", "t_order")
    found = tree(impact)
    for want in (("app_owner", "v_order_total", "catalog"),
                 ("reporting", "v_sales", "catalog"),
                 ("app_owner", "t_order_line", "catalog"),
                 ("app_owner", "trg_order_audit on t_order", "catalog"),
                 ("app_owner", "f_order_total", "text"),
                 ("app_owner", "f_order_paid", "text")):
        assert want in found, (want, found)
    assert impact["summary"]["needs_review"] is True      # reporting.v_sales
    assert impact["summary"]["other_schemas"] == ["reporting.v_sales"]
    assert any("pg_depend" in n for n in impact["blind_spots"])
    ok("impact: catalog, text, cross-schema, blind spots")
    assert ("app_owner", "t_order_line", "catalog") in tree(
        pg(entry, "deps", "f_line_count"))
    ok("deps: a SQL-standard body is in the catalog")
    paid = tree(pg(entry, "deps", "f_order_paid"))
    assert {("app_owner", "f_order_total", "text"),
            ("app_owner", "t_order", "text")} <= paid, paid
    ok("deps: a PL/pgSQL body is read as text")

    if with_plpgsql_check:
        with admin(entry) as conn:      # start from the database without it
            conn.execute("drop extension if exists plpgsql_check")
    errors = pg(entry, "errors")
    assert errors["verified"] is False and "not installed" in errors["blind_spot"]
    ok("errors: not verified without plpgsql_check, and says so")
    if with_plpgsql_check:
        with admin(entry) as conn:
            conn.execute("create extension plpgsql_check")
        try:
            errors = pg(entry, "errors")
            assert errors["verified"] is True, errors
            assert [r["NAME"] for r in errors["rows"]] == ["f_broken()"], errors
            assert "t_gone" in errors["rows"][0]["MESSAGE"]
            ok("errors: plpgsql_check finds the one broken function, with "
               "names resolved as the schema's application would")
        finally:
            with admin(entry) as conn:
                conn.execute("drop extension if exists plpgsql_check")

    # the DDL round trip: what ddl prints must rebuild what it describes
    with admin(entry) as conn:
        conn.execute("drop table app_owner.t_order cascade")
        conn.execute(ddl)
    again = pg(entry, "ddl", "t_order")["rows"][0]["DDL"]
    assert again == ddl, (ddl, again)
    ok("ddl round trip: drop, run the rebuilt DDL, rebuild — identical")


def main():
    env = os.environ
    if not env.get("PYTHIA_PG_LIVE_HOST"):
        print("SKIP live check: PYTHIA_PG_LIVE_HOST is not set")
        return
    check_connect(entry_from_env("public"))
    if env.get("PYTHIA_PG_LIVE_DISPOSABLE") != "1":
        print("SKIP read commands: PYTHIA_PG_LIVE_DISPOSABLE=1 is not set, and "
              "they load a fixture that drops schemas")
    else:
        check_reads(entry_from_env("app_owner"),
                    env.get("PYTHIA_PG_LIVE_PLPGSQL_CHECK") == "1")
    print("OK")


if __name__ == "__main__":
    main()
