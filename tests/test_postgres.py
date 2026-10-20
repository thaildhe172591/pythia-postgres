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
    deps = re.search(r"^dependencies\s*=\s*\[(.*?)\]", pyproject(), re.M | re.S).group(1)
    names = {re.match(r"[A-Za-z0-9_.-]+", d.strip().strip('"')).group(0)
             for d in deps.split(",") if d.strip()}
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
