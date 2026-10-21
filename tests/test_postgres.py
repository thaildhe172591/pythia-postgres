#!/usr/bin/env python3
"""Self-checks for pythia-postgres — no database, and no psycopg either: a
stand-in driver module records what the engine asks of it.

Needs pythia-core importable: installed, or a checkout next to this one
(../pythia-core), or PYTHIA_CORE_SRC pointing at its src/.

Run: python tests/test_postgres.py
"""
import contextlib
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
try:
    import pythia_core  # noqa: F401
except ModuleNotFoundError:
    for candidate in (os.environ.get("PYTHIA_CORE_SRC"),
                      ROOT.parent / "pythia-core" / "src"):
        if candidate and pathlib.Path(candidate).is_dir():
            sys.path.insert(1, str(candidate))
            break

from pythia_core.engine import engine_problems  # noqa: E402
from pythia_core.queries import contract_problems  # noqa: E402

import pythia_postgres  # noqa: E402
from pythia_postgres import cli  # noqa: E402
from pythia_postgres.engine import QUERY_BINDS, QUERY_DIR, PostgresEngine  # noqa: E402


def expect_exit(fn, *needles):
    try:
        fn()
    except SystemExit as e:
        msg = str(e).lower()
        for n in needles:
            assert n.lower() in msg, f"exit message missing {n!r}: {e}"
        return str(e)
    raise AssertionError("expected SystemExit, none raised")


# --- a stand-in for psycopg ----------------------------------------------------

class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, None, []

    def execute(self, sql, params=None):
        assert params is not None, "always pass a dict: %% must mean %"
        self.conn.executed.append(sql)
        for key, (cols, rows) in self.conn.script.items():
            if key in sql:
                self.description = [(c,) for c in cols]
                self._rows = list(rows)
                return
        raise AssertionError(f"unscripted query: {sql}")

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, script):
        self.script, self.executed = script, []
        self.read_only, self.closed = False, False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


SCRIPT = {
    "current_setting('server_version')": (("version", "database"),
                                          [("16.4", "app")]),
    "current_schema()": (("current_schema",), [("app_owner",)]),
}


@contextlib.contextmanager
def fake_psycopg(script=None, fail=None):
    """Install a stand-in psycopg; yields the record of what was asked."""
    record = {"connect": [], "conns": []}
    mod = types.ModuleType("psycopg")

    class Error(Exception):
        pass

    def connect(**kw):
        record["connect"].append(kw)
        if fail:
            raise fail(Error)
        conn = FakeConn(dict(script or SCRIPT))
        record["conns"].append(conn)
        return conn

    mod.Error, mod.connect = Error, connect
    saved = sys.modules.get("psycopg", None)
    had = "psycopg" in sys.modules
    sys.modules["psycopg"] = mod
    try:
        yield record
    finally:
        if had:
            sys.modules["psycopg"] = saved
        else:
            del sys.modules["psycopg"]


@contextlib.contextmanager
def project(cfg):
    keep_env = {k: os.environ.pop(k) for k in list(os.environ)
                if k.startswith("PYTHIA_PG_")}
    keep_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / ".pythia" / "postgres" / "connections.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(cfg), encoding="utf-8")
        if os.name == "posix":
            os.chmod(path, 0o600)
        os.chdir(td)
        try:
            yield pathlib.Path(td)
        finally:
            os.chdir(keep_cwd)
            os.environ.update(keep_env)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


DEV = {"dev": {"host": "localhost", "port": 5432, "dbname": "app",
               "user": "app_agent", "password": "s3cret",
               "schema": "APP_OWNER"}}


# --- packaging -----------------------------------------------------------------

def pyproject():
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_version_matches_pyproject():
    declared = re.search(r'^version\s*=\s*"([^"]+)"', pyproject(), re.M).group(1)
    assert pythia_postgres.__version__ == declared == PostgresEngine.version


def test_dependencies_are_core_and_the_driver_only():
    deps = re.search(r"^dependencies\s*=\s*\[(.*)\]\s*$", pyproject(), re.M).group(1)
    names = {re.match(r"[A-Za-z0-9_.-]+", d.strip().strip('"')).group(0)
             for d in re.findall(r'"([^"]+)"', deps)}
    assert names == {"pythia-core", "psycopg"}, names


def test_console_script_is_pythia_pg():
    # `pythia` belongs to pythia for Oracle; this package never takes it
    assert 'pythia-pg = "pythia_postgres.cli:main"' in pyproject()
    assert not re.search(r"^pythia\s*=", pyproject(), re.M)


# --- contracts -----------------------------------------------------------------

def test_engine_answers_the_connect_tier():
    assert engine_problems(PostgresEngine(), tiers=("connect",)) == []


def test_query_contract_holds():
    assert contract_problems(QUERY_DIR, QUERY_BINDS, "pyformat") == []


def test_example_config_resolves_and_holds_no_secret():
    cfg = json.loads((ROOT / "examples" / "connections.example.json")
                     .read_text(encoding="utf-8"))
    assert cfg["default"] in cfg
    for name, entry in cfg.items():
        if name == "default":
            continue
        assert entry["password"] == ""
        assert {"host", "port", "dbname", "user", "schema"} <= set(entry)


# --- the engine ------------------------------------------------------------------

def test_schema_folds_to_lower_and_defaults_to_public():
    e = PostgresEngine()
    assert e.schema_of({"schema": "APP_OWNER"}) == "app_owner"
    assert e.schema_of({"user": "app_agent"}) == "public"


def test_target_never_shows_the_password():
    e = PostgresEngine()
    entry = DEV["dev"]
    assert e.target_of(entry) == "localhost:5432/app"
    assert "s3cret" not in e.target_of(entry)
    assert e.target_of({"host": "db"}) == "db:5432"
    assert e.target_of({}) == ""


def test_connect_passes_exactly_the_settings():
    e = PostgresEngine()
    with fake_psycopg() as rec:
        e.connect(dict(DEV["dev"], sslmode="require"))
        e.connect({"host": "h", "dbname": "d", "user": "u"})
    first, second = rec["connect"]
    assert first == {"host": "localhost", "port": 5432, "dbname": "app",
                     "user": "app_agent", "password": "s3cret",
                     "sslmode": "require", "connect_timeout": 10,
                     "application_name": "pythia-pg"}
    assert "password" not in second         # libpq's own sources then


def test_connect_refuses_a_half_filled_entry_before_the_driver():
    e = PostgresEngine()
    with fake_psycopg() as rec:
        expect_exit(lambda: e.connect({"host": "h", "user": "u"}),
                    "'dbname'", ".pythia/postgres/connections.json")
    assert rec["connect"] == []


def test_session_asks_postgres_to_refuse_writes():
    e = PostgresEngine()
    conn = FakeConn({})
    assert e.session(conn, True) is conn and conn.read_only is True
    conn = FakeConn({})
    e.session(conn, False)
    assert conn.read_only is False


def test_missing_driver_names_the_package():
    saved, had = sys.modules.get("psycopg"), "psycopg" in sys.modules
    sys.modules["psycopg"] = None             # import now fails, as if absent
    try:
        expect_exit(PostgresEngine().driver_errors, 'psycopg[binary]')
    finally:
        if had:
            sys.modules["psycopg"] = saved
        else:
            del sys.modules["psycopg"]


def failure(message, sqlstate=None):
    exc = Exception(message)
    exc.sqlstate = sqlstate
    return PostgresEngine().connect_failure(exc, "dev", DEV["dev"])


def test_connect_failure_names_the_next_step():
    assert "Wrong password for app_agent" in failure(
        'FATAL:  password authentication failed for user "app_agent"')
    assert "Wrong password" in failure("x", "28P01")
    assert "pg_hba.conf" in failure(
        'no pg_hba.conf entry for host "10.0.0.1", user "app_agent"')
    assert "ALTER ROLE app_agent LOGIN" in failure(
        'role "app_agent" is not permitted to log in')
    assert "'app' does not exist" in failure('database "app" does not exist')
    assert "max_connections" in failure("sorry, too many clients already")
    generic = failure("timeout expired")
    assert "host/port/dbname" in generic and "s3cret" not in generic


# --- end to end, through pythia-core ---------------------------------------------

def test_check_end_to_end():
    with fake_psycopg() as rec, project(DEV):
        code, out, err = run("check", "--json")
    doc = json.loads(out)
    assert code == 0 and doc["ok"] and doc["connection"] == "dev"
    assert doc["schema"] == "app_owner" and doc["schema_drift"] is False
    assert {"ITEM": "server", "VALUE": "PostgreSQL 16.4 — database app"} in doc["rows"]
    assert "-- connection=dev schema=app_owner" in err
    conn = rec["conns"][0]
    assert conn.read_only is True and conn.closed is True


def test_check_reports_search_path_drift():
    script = dict(SCRIPT)
    script["current_schema()"] = (("current_schema",), [("public",)])
    with fake_psycopg(script), project(DEV):
        code, out, _ = run("check")
    assert code == 0 and "current schema is 'public'" in out


def test_check_turns_a_refused_login_into_advice():
    def refuse(Error):
        return Error('FATAL:  password authentication failed for user "app_agent"')
    with fake_psycopg(fail=refuse), project(DEV):
        expect_exit(lambda: run("check"), "wrong password for app_agent")


def test_oracle_pythia_config_is_not_ours():
    """A project that also uses pythia for Oracle has .pythia/connections.json;
    pythia-pg must not read it as its own."""
    keep = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        legacy = pathlib.Path(td) / ".pythia" / "connections.json"
        legacy.parent.mkdir()
        legacy.write_text(json.dumps({"dev": {"user": "x"}}), encoding="utf-8")
        os.chdir(td)
        try:
            with fake_psycopg() as rec:
                expect_exit(lambda: run("check"), "no postgresql connection")
            assert rec["connect"] == []
        finally:
            os.chdir(keep)


# --- the read tier, against a catalog answered by query file ------------------

from pythia_core.queries import load_query  # noqa: E402
from pythia_postgres import read  # noqa: E402
from pythia_postgres.catalog import fold  # noqa: E402
from pythia_core.output import ERROR_COLS  # noqa: E402

QUERY_TEXT = {load_query(QUERY_DIR, n): n for n in QUERY_BINDS}
PG_CLASS, PG_PROC = 1259, 1255


class CatalogCursor:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, None, []

    def execute(self, sql, params=None):
        assert params is not None, "always pass a dict: %% must mean %"
        name = QUERY_TEXT[sql]                 # only files from queries/
        self.conn.asked.append((name, dict(params)))
        answer = self.conn.answers[name]       # unscripted query: KeyError
        cols, rows = answer(params) if callable(answer) else answer
        self.description = [(c,) for c in cols]
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class CatalogConn:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def cursor(self):
        return CatalogCursor(self)

    def names(self):
        return [n for n, _ in self.asked]


RESOLVE_COLS = ("classid", "objid", "type", "label", "bare_name")
TREE5 = ("schema", "name", "type", "next_classid", "next_objid")
T_ORDER = (PG_CLASS, 10, "TABLE", "t_order", "t_order")
F_TOTAL = (PG_PROC, 20, "FUNCTION", "f_total(p_id bigint)", "f_total")


def resolving(*objs):
    def answer(b):
        return RESOLVE_COLS, [o for o in objs if o[4] == b["n"]]
    return answer


def test_fold_is_postgres_identifier_folding():
    assert fold("T_Order") == "t_order"
    assert fold('"T_Order"') == "T_Order"
    assert fold('"a""b"') == 'a"b'
    assert fold("  t_order ") == "t_order"


def test_word_pattern_escapes_everything_but_word_characters():
    assert read.word_pattern("seq_order") == "\\mseq_order\\M"
    assert read.word_pattern("a$b.c") == "\\ma\\$b\\.c\\M"


def test_body_names_keeps_literals_drops_comments():
    body = """
      -- t_commented is not a reference
      /* nor t_blocked */
      perform nextval('seq_order');
      select * from "MixedCase" join T_Order using (id);
      execute 'delete from t_dynamic';
    """
    names = read.body_names(body)
    assert {"seq_order", "MixedCase", "t_order", "t_dynamic"} <= names
    assert "t_commented" not in names and "t_blocked" not in names
    assert "mixedcase" not in names


def test_walk_is_depth_first_lists_repeats_and_never_loops():
    graph = {1: [2, 3], 2: [3], 3: [1]}       # 3 -> 1 closes a cycle

    def children(node):
        return [("app", f"o{c}", "VIEW", PG_CLASS, c, "catalog")
                for c in graph.get(node[1], [])]
    rows = read.walk([(PG_CLASS, 1, "TABLE", "o1", "o1")], 5, children)
    assert [(lvl, name) for lvl, _, name, _, _ in rows] == [
        (1, "o2"), (2, "o3"), (3, "o1"), (1, "o3")]
    shallow = read.walk([(PG_CLASS, 1, "TABLE", "o1", "o1")], 1, children)
    assert [name for _, _, name, _, _ in shallow] == ["o2", "o3"]


def test_dependents_joins_catalog_and_text_and_names_the_blind_spot():
    def catalog(b):
        if int(b["objid"]) == 10:
            return TREE5, [("app", "v_total", "VIEW", PG_CLASS, 11),
                           ("app", "f_atomic()", "FUNCTION", PG_PROC, 22),
                           ("app", "trg on t_order", "TRIGGER", None, None)]
        return TREE5, []

    def text(b):
        if b["pattern"] == "\\mt_order\\M":
            # f_total is found only as text; f_atomic, which the catalog
            # already gave, is not listed a second time
            return TREE5, [("app", "f_atomic()", "FUNCTION", PG_PROC, 22),
                           ("app", "f_total(p_id bigint)", "FUNCTION", PG_PROC, 20)]
        return TREE5, []
    conn = CatalogConn({"resolve.sql": resolving(T_ORDER, F_TOTAL),
                        "dependents-catalog.sql": catalog,
                        "dependents-text.sql": text})
    rows, notes = read.dependents(conn, "app", "T_ORDER", 3)
    assert rows == [(1, "app", "v_total", "VIEW", "catalog"),
                    (1, "app", "f_atomic()", "FUNCTION", "catalog"),
                    (1, "app", "trg on t_order", "TRIGGER", "catalog"),
                    (1, "app", "f_total(p_id bigint)", "FUNCTION", "text")]
    assert any("not in pg_depend" in n for n in notes)
    assert any("dblink" in n for n in notes)
    # the text search for f_total looked for the bare name, not the label
    assert ("dependents-text.sql", {"pattern": "\\mf_total\\M", "objid": 20}) \
        in conn.asked
    assert read.dependents(CatalogConn({"resolve.sql": resolving()}),
                           "app", "nope", 3) is None


def test_overloads_are_named_and_each_walked():
    f_text = (PG_PROC, 21, "FUNCTION", "f_total(p text)", "f_total")
    conn = CatalogConn({"resolve.sql": resolving(F_TOTAL, f_text),
                        "dependents-catalog.sql": (TREE5, []),
                        "dependents-text.sql": (TREE5, [])})
    rows, notes = read.dependents(conn, "app", "f_total", 3)
    assert rows == []
    assert notes[0].startswith("f_total names 2 objects (f_total(p_id bigint), "
                               "f_total(p text))")
    walked = {b["objid"] for n, b in conn.asked if n == "dependents-catalog.sql"}
    assert walked == {20, 21}


def test_dependencies_read_a_body_against_existing_names():
    def body(b):
        return ("language", "body"), {
            20: [("plpgsql", "select total from t_order; -- t_ghost\n"
                             "perform f_total(1);")],
            30: [("c", "t_order")]}.get(int(b["objid"]), [])
    candidates = [("t_order", "app", "t_order", "TABLE", PG_CLASS, 10),
                  ("t_order", "archive", "t_order", "TABLE", PG_CLASS, 99),
                  ("t_ghost", "app", "t_ghost", "TABLE", PG_CLASS, 12),
                  ("f_total", "app", "f_total(p_id bigint)", "FUNCTION", PG_PROC, 20)]
    conn = CatalogConn({
        "resolve.sql": resolving(F_TOTAL),
        "dependencies-catalog.sql": (TREE5, []),
        "function-body.sql": body,
        "name-candidates.sql": (("bare_name",) + TREE5, candidates)})
    rows, notes = read.dependencies(conn, "app", "f_total", 1)
    # both schemas' t_order are listed (search_path decides); the comment's
    # t_ghost is not; the function's own name is not a dependency
    assert rows == [(1, "app", "t_order", "TABLE", "text"),
                    (1, "archive", "t_order", "TABLE", "text")]
    assert any("search_path decides" in n for n in notes)
    assert conn.names().count("name-candidates.sql") == 1   # fetched once


def test_dependencies_skip_bodies_that_are_not_sql():
    c_func = (PG_PROC, 30, "FUNCTION", "f_native()", "f_native")
    conn = CatalogConn({
        "resolve.sql": resolving(c_func),
        "dependencies-catalog.sql": (TREE5, []),
        "function-body.sql": (("language", "body"), [("c", "t_order")])})
    rows, _ = read.dependencies(conn, "app", "f_native", 3)
    assert rows == [] and "name-candidates.sql" not in conn.names()


HEAD = ("qname", "unlogged", "partition_key", "partition_of", "partition_bound")


def test_table_ddl_is_rebuilt_column_by_column():
    conn = CatalogConn({
        "search-path-catalog.sql": (("search_path",), [("pg_catalog",)]),
        "resolve.sql": resolving(T_ORDER),
        "table-head.sql": (HEAD, [("app.t_order", True, "RANGE (created)", None, None)]),
        "table-columns.sql": (("name", "data_type", "not_null", "default_expr",
                               "identity", "generated"), [
            ("id", "bigint", True, None, "a", ""),
            ("status", "text", True, "'DRAFT'::text", "", ""),
            ("total_x2", "numeric", False, "(total * 2)", "", "s"),
            ("note", "text", False, None, "", "")]),
        "table-constraints.sql": (("name", "definition"),
                                  [("t_order_pkey", "PRIMARY KEY (id)")]),
        "table-extras.sql": (("statement",),
                             [("COMMENT ON TABLE app.t_order IS 'x';",)])})
    text = read.ddl(conn, "app", "t_order")
    assert text.splitlines() == [
        read.DDL_NOTE, "",
        "CREATE UNLOGGED TABLE app.t_order (",
        "    id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,",
        "    status text DEFAULT 'DRAFT'::text NOT NULL,",
        "    total_x2 numeric GENERATED ALWAYS AS ((total * 2)) STORED,",
        "    note text,",
        "    CONSTRAINT t_order_pkey PRIMARY KEY (id)",
        ") PARTITION BY RANGE (created);",
        "",
        "COMMENT ON TABLE app.t_order IS 'x';"]


def test_ddl_is_written_against_a_fixed_search_path():
    """pg_get_expr and its kin print names relative to the session's
    search_path; DDL meant to run elsewhere must not depend on it — so,
    as pg_dump does, it is rebuilt with only pg_catalog on the path."""
    conn = CatalogConn({
        "search-path-catalog.sql": (("search_path",), [("pg_catalog",)]),
        "resolve.sql": resolving(T_ORDER),
        "table-head.sql": (HEAD, [("app.t_order", False, None, None, None)]),
        "table-columns.sql": (("name", "data_type", "not_null", "default_expr",
                               "identity", "generated"), []),
        "table-constraints.sql": (("name", "definition"), []),
        "table-extras.sql": (("statement",), [])})
    read.ddl(conn, "app", "t_order")
    assert conn.names()[0] == "search-path-catalog.sql"


def test_partition_sequence_function_and_the_uncovered():
    part = (PG_CLASS, 40, "TABLE", "t_order_2026", "t_order_2026")
    conn = CatalogConn({
        "search-path-catalog.sql": (("search_path",), [("pg_catalog",)]),
        "resolve.sql": resolving(part),
        "table-head.sql": (HEAD, [("app.t_order_2026", False, None, "app.t_order",
                                   "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')")]),
        "table-extras.sql": (("statement",), [])})
    assert read.ddl(conn, "app", "t_order_2026").splitlines()[2] == (
        "CREATE TABLE app.t_order_2026 PARTITION OF app.t_order FOR VALUES "
        "FROM ('2026-01-01') TO ('2027-01-01');")
    assert "table-columns.sql" not in conn.names()
    fn = CatalogConn({"search-path-catalog.sql": (("search_path",), [("pg_catalog",)]),
                      "resolve.sql": resolving(F_TOTAL),
                      "source.sql": (("unit", "definition"),
                                     [("f_total(p_id bigint)",
                                       "CREATE OR REPLACE FUNCTION app.f_total()\n$f$\n")])})
    assert read.ddl(fn, "app", "f_total").endswith("$f$;")
    ft = (PG_CLASS, 50, "FOREIGN TABLE", "t_remote", "t_remote")
    other = CatalogConn({"search-path-catalog.sql": (("search_path",), [("pg_catalog",)]),
                         "resolve.sql": resolving(ft)})
    assert "does not rebuild the DDL of a FOREIGN TABLE" in read.ddl(other, "app", "t_remote")
    assert read.ddl(CatalogConn({"search-path-catalog.sql": (("search_path",), [("pg_catalog",)]),
                                 "resolve.sql": resolving()}), "app", "x") == ""


def test_source_and_grep_number_lines_the_same_way():
    definition = "CREATE OR REPLACE FUNCTION app.f_total()\nAS $f$\nselect 1 from t_order;\n$f$\n"
    conn = CatalogConn({
        "source.sql": (("unit", "definition"), [("f_total()", definition)]),
        "grep.sql": (("unit", "type", "definition"),
                     [("f_total()", "FUNCTION", definition)] * 3)})
    src = read.source(conn, "app", "f_total")
    assert src[2] == ("f_total()", 3, "select 1 from t_order;") and len(src) == 4
    cols, rows = read.grep(conn, "app", "T_ORDER", 2)
    assert cols == read.GREP_COLS
    assert rows == [("f_total()", "FUNCTION", 3, "select 1 from t_order;")] * 2


def test_columns_need_a_relation():
    conn = CatalogConn({"resolve.sql": resolving(F_TOTAL)})
    assert read.columns(conn, "app", "f_total") is None


def test_errors_resolve_names_as_the_schema_would():
    conn = CatalogConn({
        "resolve.sql": resolving(F_TOTAL),
        "plpgsql-check-installed.sql": (("installed",), [(True,)]),
        "search-path-first.sql": (("search_path", "schema_usage", "account"),
                                  [("app, public", True, "app_agent")]),
        "plpgsql-check.sql": (ERROR_COLS, []),
        "plpgsql-unchecked.sql": (("name",), [])})
    assert read.compile_errors(conn, "app", "f_total") == ([], None)
    order = conn.names()
    assert order.index("search-path-first.sql") < order.index("plpgsql-check.sql")
    assert ("plpgsql-check.sql", {"s": "app", "n": "f_total"}) in conn.asked


def test_errors_name_what_could_not_be_checked():
    missing = CatalogConn({"resolve.sql": resolving(),
                           "plpgsql-check-installed.sql": (("installed",), [(True,)])})
    assert read.compile_errors(missing, "app", "nope") is None
    table = CatalogConn({"resolve.sql": resolving(T_ORDER)})
    rows, note = read.compile_errors(table, "app", "t_order")
    assert rows == [] and "is a TABLE, not a function" in note
    bare = CatalogConn({"plpgsql-check-installed.sql": (("installed",), [(False,)])})
    assert read.compile_errors(bare, "app", None) == ([], read.NOT_INSTALLED)
    gaps = CatalogConn({
        "plpgsql-check-installed.sql": (("installed",), [(True,)]),
        "search-path-first.sql": (("search_path", "schema_usage", "account"),
                                  [("app", True, "app_agent")]),
        "plpgsql-check.sql": (ERROR_COLS, []),
        "plpgsql-unchecked.sql": (("name",), [("f_unused_trigger()",)])})
    rows, note = read.compile_errors(gaps, "app", None)
    assert rows == [] and note.startswith("not checked: f_unused_trigger()")


def test_errors_refuse_to_guess_without_usage_on_the_schema():
    """Without USAGE, PostgreSQL leaves the schema off search_path silently
    and plpgsql_check reports every reference as missing — a list of errors
    that are not there is worse than none."""
    conn = CatalogConn({
        "plpgsql-check-installed.sql": (("installed",), [(True,)]),
        "search-path-first.sql": (("search_path", "schema_usage", "account"),
                                  [("public", False, "app_agent")])})
    rows, note = read.compile_errors(conn, "app", None)
    assert rows == [] and "no USAGE on schema app" in note
    assert note.endswith("GRANT USAGE ON SCHEMA app TO app_agent;")
    assert "plpgsql-check.sql" not in conn.names()


def test_the_engine_answers_the_read_tier():
    assert engine_problems(PostgresEngine(), tiers=("connect", "read")) == []



# --- the write tier: reading a statement, without a database ------------------

from pythia_postgres import write  # noqa: E402


def test_the_lexer_knows_postgres_quoting():
    text = ("create function f() returns text language plpgsql as $body$\n"
            "begin return 'a;b' || $x$;$x$; end; -- not a cut ;\n"
            "$body$; /* outer /* nested ; */ still comment ; */\n"
            "select E'it\\'s;', \"semi;colon\", $1;")
    parts = write.split_statements(text)
    assert len(parts) == 2, parts
    assert parts[0].endswith("$body$") and parts[1].startswith("/* outer")
    assert parts[1].endswith("$1") and not write.lex(text).unterminated
    masked = write.lex(text).masked
    assert "a;b" not in masked and "nested" not in masked and "semi" not in masked
    assert len(masked) == len(text)
    assert write.lex("select 'open").unterminated
    assert write.lex("select $$ open").unterminated
    assert write.lex("select 1;\n  \\i other.sql\n").meta


def classified(text):
    return write.classify(text)[0]


def refusal(text):
    group, why = write.classify(text)
    assert group is None, (text, group)
    return why


def test_classify_sorts_every_statement_or_says_why_not():
    assert classified("CREATE OR REPLACE FUNCTION f() RETURNS int AS 'select 1' LANGUAGE sql;") == "source"
    assert classified("create procedure p() language sql as 'select 1'") == "source"
    assert classified("-- header\ncreate or replace view v as select 1") == "source"
    assert classified("comment on column app.t.c is 'x'") == "comments"
    assert classified("UPDATE t_order SET status = 'PAID' WHERE id = 1") == "data_dml"
    assert classified("insert into t_order (id) values (1)") == "data_dml"
    assert classified("alter table t_order add column note text") == "structural"
    assert classified("create materialized view m as select 1") == "structural"
    assert classified("drop function f(integer)") == "structural"
    assert classified("truncate t_order") == "structural"
    assert classified("grant select on t_order to app_ro") == "grants"
    assert classified("alter default privileges grant select on tables to app_ro") == "grants"
    assert classified("set work_mem = '64MB'") == "session"
    assert "DO" in refusal("do $$ begin delete from t_order; end $$")
    assert "procedure's body" in refusal("call p_settle()")
    assert "owns the transaction" in refusal("commit")
    assert "owns the transaction" in refusal("set transaction isolation level serializable")
    assert "inside a transaction" in refusal("create index concurrently ix on t_order (id)")
    assert "inside a transaction" in refusal("vacuum t_order")
    assert "who verifies" in refusal("set role app_owner")
    assert "one statement per file" in refusal("insert into t values (1); insert into t values (2);")
    assert "reads" in refusal("select f_order_total(1)")
    assert "WITH" in refusal("with x as (delete from t returning *) select 1")
    assert "temporary" in refusal("create temp table t (x int)")
    assert "TABLE and COLUMN" in refusal("comment on function f() is 'x'")
    assert "meta-command" in refusal("\\i other.sql")
    assert "ends inside" in refusal("create function f() as $$ begin")
    assert "no statement" in refusal("-- only a comment\n")
    assert "Cannot classify" in refusal("vacuumdb everything")


def test_parse_object_reads_the_name_as_postgres_would():
    p = write.parse_object
    assert p('CREATE OR REPLACE FUNCTION App.F_Total(p int) RETURNS int', "source") == \
        {"type": "FUNCTION", "name": "f_total", "schema": "app"}
    assert p('create function "MixedCase"() returns int', "source")["name"] == "MixedCase"
    assert p("create or replace recursive view app.v_tree (n) as select 1", "source") == \
        {"type": "VIEW", "name": "v_tree", "schema": "app"}
    assert p("create procedure p_settle() language sql as 'select 1'", "source")["type"] == "PROCEDURE"
    col = p("COMMENT ON COLUMN app.t_order.status IS 'x'", "comments")
    assert (col["name"], col["schema"], col["table"], col["column"]) == \
        ("t_order.status", "app", "t_order", "status")
    tab = p('comment on table "T_Order" is null', "comments")
    assert (tab["name"], tab["schema"], tab["column"]) == ("T_Order", None, None)
    assert p("delete from t_order", "data_dml") is None


def test_dml_probe_finds_the_rows_or_refuses_to_guess():
    probe = write.dml_probe
    assert probe("update t_order o set status = 'PAID' where o.id < 3 returning o.id") == \
        ("t_order o", "o.id < 3")
    assert probe("delete from only app.t_order where status = 'x;y'") == \
        ("app.t_order", "status = 'x;y'")
    assert probe("delete from t_order") == ("t_order", None)
    # a trailing comment would comment out what the probe appends after it
    assert probe("delete from t_order -- all of them?\n where id = 1 -- just one") \
        == ("t_order", "id = 1")
    assert probe("insert into t_order (id) values (1)") is None
    for stmt, why in (
            ("merge into t using s on t.id = s.id when matched then delete", "MERGE"),
            ("update t set x = s.x from s where t.id = s.id", "FROM"),
            ("delete from t using s where t.id = s.id", "USING"),
            ("delete from t where id in (select id from s)", "subquery"),
            ("delete from t where current of c", "CURRENT OF")):
        try:
            probe(stmt)
        except SystemExit as e:
            assert why in str(e), (stmt, str(e))
        else:
            raise AssertionError(f"probe guessed at: {stmt}")


def test_destruction_is_named():
    d = write.destructive_reason
    assert d("drop table t_order", "structural").startswith("DROP removes")
    assert "CASCADE" in d("drop table t_order cascade", "structural")
    assert "TRUNCATE" in d("truncate t_order", "structural")
    assert "column or constraint" in d("alter table t drop column x", "structural")
    assert "renaming" in d("alter table t rename to t2", "structural")
    assert "type" in d("alter table t alter column x type int", "structural")
    assert "every row" in d("delete from t_order", "data_dml")
    assert "always true" in d("update t set x = 1 where true", "data_dml")
    assert d("delete from t where id = 1", "data_dml") is None
    assert "REVOKE" in d("revoke select on t from app_ro", "grants")
    assert "PUBLIC" in d("grant select on t to public", "grants")
    assert d("comment on table t is 'drop table x'", "comments") is None


def test_restore_puts_back_or_drops():
    r = write.restore_statement
    fn = {"type": "FUNCTION", "name": "f_total", "schema": None}
    assert r("source", fn, "CREATE OR REPLACE FUNCTION app.f_total()\n$f$", {}) == \
        "CREATE OR REPLACE FUNCTION app.f_total()\n$f$;"
    assert r("source", fn, "", {"drop": "app.f_total(p_id bigint)"}) == \
        "DROP FUNCTION app.f_total(p_id bigint);"
    view = {"type": "VIEW", "name": "v_x", "schema": None}
    assert r("source", view, "", {"drop": "app.v_x"}) == "DROP VIEW app.v_x;"
    com = {"type": "COMMENT", "name": "t_order.status", "schema": "app",
           "table": "t_order", "column": "status", "kind": "COLUMN"}
    assert r("comments", com, "it's", {"schema": "app"}) == \
        "COMMENT ON COLUMN app.t_order.status IS 'it''s';"
    assert r("comments", com, "", {"schema": "app"}) == \
        "COMMENT ON COLUMN app.t_order.status IS NULL;"


def test_the_engine_answers_the_write_tier():
    assert engine_problems(PostgresEngine(),
                           tiers=("connect", "read", "write")) == []



# --- the harness tier: the guard's patterns, the template, the skills ----------

from pythia_core import harness, skills as skill_contract  # noqa: E402

SKILL_NAMES = ("using-pythia-pg", "pythia-pg-explore", "pythia-pg-impact",
               "pythia-pg-apply", "pythia-pg-deploy", "pythia-pg-autopilot",
               "pythia-pg-verify")


@contextlib.contextmanager
def scratch_project():
    keep = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("PYTHIA_")}
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td).resolve()
        cfg = root / ".pythia" / "postgres" / "connections.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"dev": {"host": "localhost", "dbname": "app",
                                           "user": "u", "schema": "app_owner"}}),
                       encoding="utf-8")
        try:
            yield root
        finally:
            os.environ.update(keep)


def guard(root, command, tool="Bash"):
    tin = {"command": command} if tool == "Bash" else {"sql": command}
    out = harness.pre_tool_decision(PostgresEngine(), {
        "tool_name": tool, "tool_input": tin, "cwd": str(root)})
    return out and out["hookSpecificOutput"]["permissionDecision"]


def test_the_engine_answers_the_harness_release_and_lint_tiers():
    assert engine_problems(PostgresEngine(), tiers=(
        "connect", "read", "write", "harness", "release", "lint")) == []


def lint_ids(*statements):
    """{(rule, statement index, line)} over a change of statements."""
    from pythia_core import lint
    stmts = [{"file": "f.sql", "line": 1, "text": t, "group": write.classify(t)[0],
              "n": i + 1} for i, t in enumerate(statements)]
    found = lint.run(PostgresEngine(), {"severity": {}, "naming": {}}, stmts)
    return {(f["rule"], f["n"], f["line"]) for f in found}, found


def test_lint_catches_a_security_definer_function_without_a_search_path():
    bad = ("create or replace function f_pay(p bigint) returns void\n"
           "language plpgsql security definer as $$\n"
           "begin\n  -- set search_path here would not help\n"
           "  update t_order set status = 'PAID' where id = p;\nend $$")
    ids, found = lint_ids(bad)
    assert ("pg-definer-search-path", 1, 2) in ids          # where SECURITY DEFINER is
    assert next(f for f in found if f["rule"] == "pg-definer-search-path")["severity"] == "error"
    good = bad.replace("security definer", "security definer set search_path = app_owner, pg_temp")
    assert not any(r == "pg-definer-search-path" for r, _, _ in lint_ids(good)[0])
    invoker = bad.replace("security definer", "")
    assert not any(r == "pg-definer-search-path" for r, _, _ in lint_ids(invoker)[0])
    assert ("pg-definer-search-path", 1, 1) in lint_ids(
        "alter function f_pay(bigint) security definer")[0]
    assert not lint_ids("alter function f_pay(bigint) security definer "
                        "set search_path = app_owner, pg_temp")[0]


def test_lint_reads_column_types_the_postgres_wiki_warns_about():
    ids, _ = lint_ids("create table t_note (\n"
                      "  id serial primary key,\n"
                      "  code char(3),\n"
                      "  price money,\n"
                      "  noted timestamp,\n"
                      "  seen timestamp(3) without time zone,\n"
                      "  fine timestamptz,\n"
                      "  also timestamp with time zone,\n"
                      "  name varchar(40),\n"
                      "  note text default 'char(3) money timestamp serial'\n)")
    got = {(r, ln) for r, _, ln in ids}
    assert {("pg-serial", 2), ("pg-char-n", 3), ("pg-money", 4),
            ("pg-timestamp-without-tz", 5), ("pg-timestamp-without-tz", 6)} <= got, got
    assert not any(ln in (7, 8, 9, 10) for _, ln in got if _ != "pg-table-comment"), got
    code, _ = lint_ids("create or replace function f_when() returns timestamp "
                       "language sql as $$ select now()::timestamp $$")
    assert not code, code           # column types are a table's business, not a cast's


def test_lint_flags_select_star_and_not_in_a_subquery_in_code():
    ids, _ = lint_ids("create view v_order as select * from t_order",
                      "create or replace function f_open() returns setof t_order\n"
                      "language sql as $$\n  select * from t_order\n"
                      "  where id not in (select order_id from t_order_line)\n$$",
                      "delete from t_order where id not in (select order_id from t_paid)")
    assert {("pg-select-star", 1, 1), ("pg-select-star", 2, 3),
            ("pg-not-in-subquery", 2, 4), ("pg-not-in-subquery", 3, 1)} <= ids, ids
    clean, _ = lint_ids("create view v_n as select count(*) as n, t.id from t_order t "
                        "where t.id not in (1, 2) and t.status <> 'select * from x'")
    assert not clean, clean


def test_lint_asks_for_a_comment_on_every_new_table_anywhere_in_the_change():
    table = "create table app_owner.t_note (id bigint)"
    assert ("pg-table-comment", 1, 1) in lint_ids(table)[0]
    assert not lint_ids(table, "comment on table t_note is 'notes'")[0]
    assert not lint_ids(table, 'comment on table APP_OWNER."t_note" is \'notes\'')[0]
    assert ("pg-table-comment", 1, 1) in lint_ids(table, "comment on table t_other is 'x'")[0]


def test_a_script_splits_where_postgres_would_and_says_where_each_starts():
    script = ("-- release 42\n"
              "\n"
              "create or replace function f_note(p text) returns text\n"
              "language plpgsql as $body$\n"
              "begin\n"
              "  return p || ';';   -- a semicolon in a body\n"
              "end;\n"
              "$body$;\n"
              "\n"
              "/* the column */ alter table t_order add column note text;\n"
              "update t_order set note = 'a;b' where id = 1;\n"
              "comment on column t_order.note is 'free text'\n")
    got = PostgresEngine().split_script(script)
    assert [line for line, _ in got] == [3, 10, 11, 12], got
    assert got[0][1].startswith("-- release 42") and got[0][1].endswith("$body$")
    assert got[2][1] == "update t_order set note = 'a;b' where id = 1"
    assert [write.classify(stmt)[0] for _, stmt in got] == [
        "source", "structural", "data_dml", "comments"]
    assert PostgresEngine().split_script("-- only a comment\n\n") == []
    assert write.classify(PostgresEngine().split_script(
        "\\i other.sql\nselect 1;")[0][1])[0] is None       # a psql meta-command


def test_the_guard_denies_psql_writing_around_the_gate():
    with scratch_project() as root:
        for cmd in ('psql -d app -c "drop table app_owner.t_order"',
                    'psql -c "CREATE OR REPLACE FUNCTION f() RETURNS int AS $$ select 1 $$ LANGUAGE sql"',
                    'PGPASSWORD=x psql -h localhost -c "update t_order set status = 1"',
                    'psql app -c "delete from t_order"',
                    'psql app -c "insert into t_order values (1)"',
                    'psql app -c "truncate t_order"',
                    'psql app -c "alter table t_order add column x int"',
                    'psql app -c "grant select on t_order to reporting"',
                    'psql app -c "comment on table t_order is \'x\'"',
                    "psql app -c \"select setval('seq_order', 1)\"",
                    "psql app -c \"select nextval('seq_order')\"",
                    'psql app -c "\\copy t_order from orders.csv"',
                    'psql app -c "do $$ begin perform 1; end $$"',
                    'psql app -c "call p_close_orders()"',
                    'psql app -c "refresh materialized view mv_orders"',
                    'psql app -c "select * into t_order_copy from t_order"',
                    "psql -h db -U app -d app -f release.sql",
                    "psql --file=release.sql app", "psql -1 -frelease.sql app",
                    "psql app < release.sql", 'psql app -c "\\i release.sql"',
                    "cat release.sql | psql app", "pg_restore -d app backup.dump",
                    "/usr/lib/postgresql/16/bin/psql -c 'drop view v_order'",
                    'docker exec db psql -U postgres -c "drop table t_order"'):
            assert guard(root, cmd) == "deny", cmd


def test_the_guard_leaves_psql_reads_to_the_client():
    with scratch_project() as root:
        for cmd in ('psql -d app -c "select count(*) from t_order"',
                    "psql -At -F , -c 'select id from t_order'",
                    "psql -l", "psql --version",
                    "pg_dump -s -t t_order app",
                    'psql app -c "select updated_at, created_by from t_order"'):
            assert guard(root, cmd) is None, cmd
        assert guard(root, 'pythia-pg ls "t_order%"') == "allow"
        assert guard(root, "DROP TABLE t_order", tool="mcp__postgres__query") == "deny"
        assert guard(root, "select 1", tool="mcp__postgres__query") is None


def test_install_scaffolds_the_example_config():
    example = json.loads((ROOT / "examples" / "connections.example.json")
                         .read_text(encoding="utf-8"))
    assert PostgresEngine().connections_template() == example


def test_the_skill_pack_holds_the_contract_and_routes_every_skill():
    pack = skill_contract.pack(PostgresEngine().skills_dir())
    assert tuple(sorted(p.name for p in pack)) == tuple(sorted(SKILL_NAMES))
    for skill in pack:
        assert skill_contract.lint(skill / "SKILL.md") == [], skill.name
    router = (PostgresEngine().skills_dir() / "using-pythia-pg" / "SKILL.md") \
        .read_text(encoding="utf-8")
    for name in SKILL_NAMES[1:]:
        assert f"`{name}`" in router, f"the router never routes to {name}"
    for named in set(re.findall(r"`(pythia-pg-[a-z-]+)`", router)):
        assert named in SKILL_NAMES, f"the router names a skill that is not shipped: {named}"
    text = "\n".join((s / "SKILL.md").read_text(encoding="utf-8") for s in pack)
    assert "pythia-pg approve <token>" in text and "--confirm <token>" in text
    apply_skill = (PostgresEngine().skills_dir() / "pythia-pg-apply" / "SKILL.md") \
        .read_text(encoding="utf-8")
    doors = [apply_skill.index(d) for d in (
        "AskUserQuestion", "pythia_pg_approve", "pythia-pg approve <token>")]
    assert doors == sorted(doors), "the apply skill names the doors out of order"
    assert "pythia-pg approve --card <token>" in apply_skill


def test_the_mcp_approver_answers_as_a_real_process():
    import subprocess
    core_src = pathlib.Path(sys.modules["pythia_core"].__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(core_src)])}
    session = "".join(json.dumps(m) + "\n" for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "pythia_pg_approve", "arguments": {"token": "abc123"}}}))
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, "-m", "pythia_postgres", "mcp"],
                           input=session, capture_output=True, text=True, cwd=td,
                           env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    out = [json.loads(line) for line in r.stdout.splitlines()]
    assert out[0]["result"]["serverInfo"]["name"] == "pythia_pg"
    assert [t["name"] for t in out[1]["result"]["tools"]] == ["pythia_pg_approve"]
    assert out[2]["result"]["isError"]                    # no such preview: nothing minted
    assert "no pending preview" in out[2]["result"]["content"][0]["text"].lower()


def test_the_skills_ship_in_the_wheel():
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for glob in ('"skills/*/SKILL.md"', '"skills/*/reference/*.md"'):
        assert glob in toml, f"package-data misses {glob}"


def test_the_version_has_its_changelog_entry():
    # a release is tagged from a version whose changes are written down
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(pythia_postgres.__version__)} ", text, re.M), \
        f"CHANGELOG.md has no entry for {pythia_postgres.__version__}"


def test_the_release_workflow_checks_the_tag_against_the_version():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in text and "environment: pypi" in text
    assert "id-token: write" in text and "skip-existing: true" in text
    for needle in ('version = \\"$V\\"', 'src/pythia_postgres/__init__.py', "## $V "):
        assert needle in text, needle


def test_it_asks_for_the_core_of_its_release_series():
    # 0.x: a minor version of pythia-core may change the engine contract
    assert '"pythia-core>=0.1.0,<0.2"' in pyproject()


def readme_shape(text):
    """What the two READMEs must share: the heading levels in order, and
    every fenced block, byte for byte — the commands do not translate."""
    levels = [len(m.group(1)) for m in re.finditer(r"^(#+) ", text, re.M)]
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```", text, re.M | re.S)
    return levels, blocks


def test_the_vietnamese_readme_matches_the_english_one():
    en = (ROOT / "README.md").read_text(encoding="utf-8")
    vi = (ROOT / "README.vi.md").read_text(encoding="utf-8")
    assert readme_shape(vi) == readme_shape(en), "README.vi.md has drifted from README.md"
    assert re.search(r"\[Tiếng Việt\]\([^)]*README\.vi\.md\)", en), "README.md links no translation"
    assert re.search(r"\[English\]\([^)]*README\.md\)", vi), "README.vi.md links no original"


def test_the_package_says_what_it_is_on_pypi():
    text = pyproject()
    if re.match(r"0\.\d+\.\d+$", pythia_postgres.__version__):
        assert '"Development Status :: 3 - Alpha"' in text
    for needle in ('readme = "README.md"', '"Programming Language :: Python :: 3.9"',
                   '"Programming Language :: Python :: 3.13"', "Changelog = "):
        assert needle in text, needle


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except (Exception, SystemExit) as e:  # noqa: BLE001 — keep going
                failed += 1
                print(f"FAIL {name}: {e!r}")
    if failed:
        sys.exit(f"{failed} test(s) failed")
    print("OK")


if __name__ == "__main__":
    main()
