#!/usr/bin/env python3
"""Against a real, disposable PostgreSQL: every pythia-pg command, end to end.

1. `check` works, and the read-only session it opens is refused a write by
   the server itself.
2. With PYTHIA_PG_LIVE_DISPOSABLE=1 only: tests/fixtures/app_owner.sql is
   loaded (it DROPS and recreates the app_owner and reporting schemas), and
   every read command is checked against it; then the write gate end to end
   (preview, approve, confirm, restore, overloads, rows that move, a
   verification that moves); then a DDL round trip: drop the table, run the
   DDL pythia-pg rebuilt, rebuild it again, compare.
3. With PYTHIA_PG_LIVE_PLPGSQL_CHECK=1 as well: plpgsql_check is installed
   for the run (the server must have the package), so `errors` and the
   rehearsals are checked with it as well as without.

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

    return ddl


def ddl_round_trip(entry, ddl):
    """What ddl prints must rebuild what it describes — from any session:
    with the schema on the role's search_path it must print the same."""
    with admin(entry) as conn:
        conn.execute(f"alter role current_user in database {entry['dbname']} "
                     "set search_path = app_owner, public")
    try:
        on_path = pg(entry, "ddl", "t_order")["rows"][0]["DDL"]
    finally:
        with admin(entry) as conn:
            conn.execute(f"alter role current_user in database {entry['dbname']} "
                         "reset search_path")
    assert on_path == ddl, (ddl, on_path)
    with admin(entry) as conn:
        conn.execute("drop table app_owner.t_order cascade")
        conn.execute(ddl)
    again = pg(entry, "ddl", "t_order")["rows"][0]["DDL"]
    assert again == ddl, (ddl, again)
    ok("ddl round trip: drop, run the rebuilt DDL, rebuild — identical")


# --- the write gate, end to end --------------------------------------------------

class Project:
    """One project folder for a run of writes: the journal and the grants
    have to outlive a single command."""

    def __init__(self, entry):
        self.td = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.td.name)
        self.state = self.root / ".pythia" / "postgres"
        self.state.mkdir(parents=True)
        path = self.state / "connections.json"
        path.write_text(json.dumps({"live": entry}), encoding="utf-8")
        if os.name == "posix":
            os.chmod(path, 0o600)

    def file(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")
        return name

    def run(self, *argv):
        """(exit code, last stdout line parsed when it is JSON, the refusal)"""
        from pythia_postgres import cli
        keep = os.getcwd()
        os.chdir(self.root)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                code, why = cli.main(list(argv)) or 0, ""
        except SystemExit as e:
            code, why = (e.code, "") if isinstance(e.code, int) else (1, str(e))
        finally:
            os.chdir(keep)
        lines = out.getvalue().strip().splitlines()
        doc = None
        if lines and lines[-1].startswith("{"):
            doc = json.loads(lines[-1])
        return code, doc, why

    def preview(self, name, text):
        code, doc, why = self.run("apply", self.file(name, text), "--json")
        assert code == 0 and doc, (code, why)
        return doc

    def approve(self, token):
        """The developer's own act, at their own console."""
        from pythia_core import human
        human.FORCE_CONSOLE = True
        try:
            code, _, why = self.run("approve", token)
            assert code == 0, why
        finally:
            human.FORCE_CONSOLE = None

    def confirm(self, *argv):
        code, doc, why = self.run(*argv, "--json")
        return code, doc, why

    def policy(self, **groups):
        (self.state / "policy.json").write_text(json.dumps(groups), encoding="utf-8")


def scalar(entry, sql):
    with admin(entry) as conn:
        return conn.execute(sql).fetchone()[0]


SOURCE = "select prosrc from pg_proc where oid = 'app_owner.f_order_total(bigint)'::regprocedure"
CENTS = """-- f_order_total, in cents
create or replace function f_order_total(p_id bigint) returns numeric
language plpgsql as $$
declare
  v_total numeric;
begin
  select total * 100 into v_total from t_order where id = p_id;
  raise notice 'total for % is % cents', p_id, v_total;
  return coalesce(v_total, 0);
end;
$$;
"""


def check_writes(entry, with_plpgsql_check):
    from pythia_core import human
    human.FORCE_CONSOLE = False             # no person here unless one approves
    with admin(entry) as conn:
        # where the agent's unqualified names land, as an application role has it
        conn.execute(f"alter role current_user in database {entry['dbname']} "
                     "set search_path = app_owner, public")
        if with_plpgsql_check:
            conn.execute("create extension if not exists plpgsql_check")
    p = Project(entry)
    try:
        _writes(entry, p, with_plpgsql_check)
    finally:
        human.FORCE_CONSOLE = None
        with admin(entry) as conn:
            conn.execute(f"alter role current_user in database {entry['dbname']} "
                         "reset search_path")
            conn.execute("drop extension if exists plpgsql_check")


def _writes(entry, p, checked):
    original = scalar(entry, SOURCE)

    doc = p.preview("cents.sql", CENTS)
    assert doc["object"] == "f_order_total(p_id bigint)" and doc["changed_lines"] == 3
    assert doc["will_apply"] is False and scalar(entry, SOURCE) == original
    assert doc["rehearsal"]["verified"] is checked, doc["rehearsal"]
    if not checked:
        assert "not installed" in doc["rehearsal"]["blind"]
    token = doc["token"]
    ok("apply previews: rehearsed, rolled back, the database unchanged")

    code, _, why = p.run("approve", token)
    assert code == 1 and "real console" in why
    code, _, why = p.confirm("apply", "cents.sql", "--confirm", token)
    assert code == 1 and "no developer approval is on file" in why
    assert scalar(entry, SOURCE) == original
    ok("no console, no approval: nothing written")

    p.approve(token)
    code, res, why = p.confirm("apply", "cents.sql", "--confirm", token)
    assert code == 0 and res["applied"], (code, why, res)
    body = scalar(entry, SOURCE)
    assert "total * 100" in body and "'total for % is % cents'" in body
    ok("approved and confirmed: written once, a % in the body kept as written")

    code, _, why = p.confirm("apply", "cents.sql", "--confirm", token)
    assert code == 1 and "already used" in why
    ok("one approval, one write")

    code, doc, _ = p.run("journal", "restore", res["restore"].split()[-1], "--json")
    assert code == 0 and doc["will_apply"] is False
    p.approve(doc["token"])
    code, _, why = p.confirm("journal", "restore", res["restore"].split()[-1],
                             "--confirm", doc["token"])
    assert code == 0, why
    assert scalar(entry, SOURCE) == original
    ok("journal restore: previewed, approved, written — the original is back")

    doc = p.preview("overload.sql", "create or replace function "
                    "f_order_total(p_id integer) returns numeric language sql "
                    "as 'select 0'")
    assert doc["created"] is True and "new overload" in doc["rehearsal"]["notes"][0]
    ok("a new overload is named, and the old one said to stay callable")

    code, _, why = p.run("apply", p.file("bad.sql", "create or replace function "
                                         "f_bad() returns int language plpgsql "
                                         "as $$ begin retrun 1; end $$"))
    assert code == 1 and 'syntax error at or near "retrun"' in why
    ok("a statement that fails in rehearsal has nothing to approve")

    p.policy(data_dml="confirm", structural="confirm")
    doc = p.preview("paid.sql", "update t_order set status = 'PAID' "
                    "where status = 'DRAFT'")
    assert doc["row_set"]["count"] == 2 and doc["rehearsal"]["rows"] == 2
    p.approve(doc["token"])
    with admin(entry) as conn:      # someone else moves the rows meanwhile
        conn.execute("update app_owner.t_order set status = 'DRAFT' where status = 'PAID'")
    code, _, why = p.confirm("apply", "paid.sql", "--confirm", doc["token"])
    assert code == 1 and "row set moved" in why and "2 rows when you approved it, 3 now" in why
    assert scalar(entry, "select count(*) from app_owner.t_order where status = 'DRAFT'") == 3
    doc = p.preview("paid.sql", "update t_order set status = 'PAID' "
                    "where status = 'DRAFT'")
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "paid.sql", "--confirm", doc["token"])
    assert code == 0 and res["rows"] == 3, (why, res)
    assert scalar(entry, "select count(*) from app_owner.t_order where status = 'DRAFT'") == 0
    ok("DML: approved on its rows; rows that moved are refused, then written")

    doc = p.preview("comment.sql", "comment on column t_order.status is 'paid or not'")
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "comment.sql", "--confirm", doc["token"])
    assert code == 0, why
    col = ("select col_description('app_owner.t_order'::regclass, "
           "(select attnum from pg_attribute where attrelid = "
           "'app_owner.t_order'::regclass and attname = 'status'))")
    assert scalar(entry, col) == "paid or not"
    code, doc, _ = p.run("journal", "restore", res["restore"].split()[-1], "--json")
    p.approve(doc["token"])
    assert p.confirm("journal", "restore", res["restore"].split()[-1],
                     "--confirm", doc["token"])[0] == 0
    assert scalar(entry, col) == "DRAFT until paid"
    ok("a comment: written, and restored to the one it replaced")

    _release(entry, p)
    _lease(entry, p)

    drop = "alter table t_order drop column total"
    doc = p.preview("drop.sql", drop)
    assert doc["destructive"].startswith("ALTER ... DROP")
    if not checked:
        assert doc["rehearsal"]["verified"] is False
        ok("structural: destructive named; not verified without plpgsql_check")
        return
    assert ["f_order_total(p_id bigint)", "FUNCTION",
            'column "total" does not exist'] in doc["rehearsal"]["broken"], doc
    ok("structural: the rehearsal shows the PL/pgSQL function it would break")

    p.approve(doc["token"])
    with admin(entry) as conn:     # after approval, more code comes to depend on it
        conn.execute("create function app_owner.f_order_tax(p_id bigint) "
                     "returns numeric language plpgsql as $$ begin return "
                     "(select total * 0.1 from app_owner.t_order where id = "
                     "p_id); end $$")
    code, _, why = p.confirm("apply", "drop.sql", "--confirm", doc["token"])
    assert code == 1 and "verification moved" in why and "f_order_tax" in why, why
    assert scalar(entry, "select count(*) from pg_attribute where attrelid = "
                         "'app_owner.t_order'::regclass and attname = 'total'") == 1
    ok("a verification that moved after approval is rolled back")


HAS_NOTE = ("select count(*) from pg_attribute where attrelid = "
            "'app_owner.t_order'::regclass and attname = 'note' and not attisdropped")
RELEASE = ("-- release: a column, its first value, its comment\n"
           "alter table t_order add column note text;\n"
           "update t_order set note = 'first' where id = 1;\n"
           "comment on column t_order.note is 'free text';\n")


def _release(entry, p):
    """deploy: rehearsed as one transaction, landed as one, or not at all."""
    p.file("rel.sql", RELEASE)
    code, doc, why = p.run("deploy", "rel.sql", "--json")
    assert code == 0, why
    assert [m["group"] for m in doc["members"]] == ["structural", "data_dml", "comments"]
    # the UPDATE was rehearsed against the column the release adds before it
    assert doc["members"][1]["row_set"]["count"] == 1, doc["members"][1]
    assert scalar(entry, HAS_NOTE) == 0
    ok("deploy previews a release as one transaction: DML on the column it adds")

    code, _, why = p.run("approve", "--card", doc["members"][1]["token"])
    assert code == 1 and "approved as a whole" in why
    p.approve(doc["batch"])
    with admin(entry) as conn:        # someone else changes the row meanwhile
        conn.execute("update app_owner.t_order set total = total where id = 1")
    code, _, why = p.confirm("deploy", "rel.sql", "--confirm", doc["batch"])
    assert code == 1 and "statement 2" in why and "nothing was written" in why.lower(), why
    assert scalar(entry, HAS_NOTE) == 0           # statement 1 did not land either
    ok("a release whose rows moved after approval rolls back whole")

    code, doc, why = p.run("deploy", "rel.sql", "--json")
    p.approve(doc["batch"])
    code, res, why = p.confirm("deploy", "rel.sql", "--confirm", doc["batch"])
    assert code == 0 and res["applied"], (why, res)
    assert scalar(entry, "select note from app_owner.t_order where id = 1") == "first"
    assert scalar(entry, "select col_description('app_owner.t_order'::regclass, "
                         "(select attnum from pg_attribute where attrelid = "
                         "'app_owner.t_order'::regclass and attname = 'note'))") == "free text"
    ok("an approved release lands whole, in one commit")

    p.file("bad.sql", "alter table t_order add column note2 text;\n"
                      "update t_order set nope = 1 where id = 1;\n")
    code, _, why = p.run("deploy", "bad.sql")
    assert code == 1 and "bad.sql:2" in why and "nope" in why, why
    assert scalar(entry, "select count(*) from pg_attribute where attrelid = "
                         "'app_owner.t_order'::regclass and attname = 'note2'") == 0
    ok("a release that fails at statement 2 keeps nothing of statement 1")
    with admin(entry) as conn:
        conn.execute("alter table app_owner.t_order drop column note")


def _lease(entry, p):
    """autopilot: one approved lease lands covered writes, and nothing else."""
    from pythia_core import human
    code, doc, why = p.run("autopilot", "request", "--groups", "comments",
                           "--max-writes", "2", "--json")
    assert code == 0 and len(doc["token"]) == 8, why
    p.file("c1.sql", "comment on table t_order is 'orders, under a lease'")
    code, doc2, _ = p.run("apply", "c1.sql", "--json")
    assert code == 0 and doc2["will_apply"] is False         # a request is no lease
    human.FORCE_CONSOLE = True
    try:
        code, _, why = p.run("approve", doc["token"])
        assert code == 0, why
    finally:
        human.FORCE_CONSOLE = False
    code, res, why = p.run("apply", "c1.sql", "--json")
    assert code == 0 and res["applied"] and res["confirmed_via"] == "autopilot", (why, res)
    assert scalar(entry, "select obj_description('app_owner.t_order'::regclass)") \
        == "orders, under a lease"
    p.file("s1.sql", "alter table t_order add column under_lease int")
    code, doc3, why = p.run("apply", "s1.sql", "--json")
    assert code == 0 and doc3["will_apply"] is False, why
    assert "does not cover structural" in doc3["autopilot"]["why"]
    assert scalar(entry, "select count(*) from pg_attribute where attrelid = "
                         "'app_owner.t_order'::regclass and attname = 'under_lease'") == 0
    code, report, _ = p.run("autopilot", "report", "--json")
    assert [w["verdict"] for w in report["writes"]] == ["ok"]
    assert p.run("autopilot", "off")[0] == 0
    with admin(entry) as conn:      # the round trip below compares with the fixture
        conn.execute("comment on table app_owner.t_order is 'Customer orders'")
    ok("autopilot: an approved lease lands a covered write, and only that")


def main():
    env = os.environ
    if not env.get("PYTHIA_PG_LIVE_HOST"):
        print("SKIP live check: PYTHIA_PG_LIVE_HOST is not set")
        return
    check_connect(entry_from_env("public"))
    if env.get("PYTHIA_PG_LIVE_DISPOSABLE") != "1":
        print("SKIP read and write commands: PYTHIA_PG_LIVE_DISPOSABLE=1 is not "
              "set, and they load a fixture that drops schemas")
    else:
        entry = entry_from_env("app_owner")
        checked = env.get("PYTHIA_PG_LIVE_PLPGSQL_CHECK") == "1"
        ddl = check_reads(entry, checked)
        check_writes(entry, checked)
        ddl_round_trip(entry, ddl)
    print("OK")


if __name__ == "__main__":
    main()
