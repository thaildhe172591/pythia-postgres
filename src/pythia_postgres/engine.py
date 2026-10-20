"""PostgreSQL, through psycopg 3, as a pythia-core engine.

It answers every tier of pythia_core.engine: connect (here), read (read.py),
write (write.py) — the write tier rehearsing each statement inside a
transaction, since PostgreSQL's DDL runs in one — release (a script split
where PostgreSQL would split it), lint (rules.py) and harness (guard.py).
"""
import copy
import sys

from . import __version__, guard, read, write
from .catalog import QUERY_BINDS, QUERY_DIR, q  # noqa: F401 — QUERY_* re-exported

CONFIG_REL = ".pythia/postgres/connections.json"
REQUIRED = ("host", "dbname", "user")


class PostgresEngine:
    name = "postgres"
    label = "PostgreSQL"
    command = "pythia-pg"
    env_prefix = "PYTHIA_PG"
    version = __version__
    bind_style = "pyformat"
    default_port = 5432
    # printed by `pythia-pg policy`: is rollback real, group by group?
    rollback_notes = {
        "source": "Yes — the definition is snapshotted before every write; a "
                  "new object's undo is a DROP.",
        "comments": "Yes — the previous comment is snapshotted.",
        "data_dml": "No. After commit only a backup or point-in-time recovery "
                    "brings rows back. Revalidation checks the rows; it is not "
                    "an undo.",
        "structural": "No. A dropped column or table is gone; the rehearsal "
                      "shows what breaks before anything commits.",
        "grants": "By hand — write the opposite GRANT or REVOKE.",
        "session": "Not needed — it ends with the connection.",
    }

    # --- the connection's life ------------------------------------------------

    def driver_errors(self):
        try:
            import psycopg
        except ModuleNotFoundError:
            sys.exit("The 'psycopg' package is required to connect: "
                     'pip install "psycopg[binary]"')
        return (psycopg.Error,)

    def connect(self, entry):
        import psycopg
        gaps = [k for k in REQUIRED if not entry.get(k)]
        if gaps:
            sys.exit(f"Connection is missing {', '.join(map(repr, gaps))} — "
                     f"fill in {CONFIG_REL}.")
        kw = {"host": entry["host"], "port": int(entry.get("port") or 5432),
              "dbname": entry["dbname"], "user": entry["user"],
              "connect_timeout": int(entry.get("connect_timeout") or 10),
              "application_name": self.command}
        # no password key means libpq's own sources (PGPASSWORD, ~/.pgpass)
        if entry.get("password"):
            kw["password"] = entry["password"]
        if entry.get("sslmode"):
            kw["sslmode"] = entry["sslmode"]
        return psycopg.connect(**kw)

    def session(self, conn, readonly):
        if readonly:
            # every transaction this command opens is READ ONLY, so
            # PostgreSQL itself refuses a write — the second line of defence.
            # dblink and foreign data wrappers reach past it; the agent
            # account should not hold them.
            conn.read_only = True
        return conn

    def close(self, conn):
        conn.close()

    def connect_failure(self, exc, conn_name, entry):
        """Name the next step for the failures PostgreSQL has already
        diagnosed precisely. Connection errors may carry no SQLSTATE, so the
        server's message text is the fallback."""
        text = str(exc)
        state = getattr(exc, "sqlstate", None) or ""
        low = text.lower()
        who = entry.get("user") or "<the connecting user>"
        head = f"Could not connect using connection {conn_name!r}: {text}"
        if state == "28P01" or "password authentication failed" in low:
            return (f"{head}\nWrong password for {who}. Check the entry in "
                    f"{CONFIG_REL} (or ~/.pgpass when it holds no password).")
        if "no pg_hba.conf entry" in low:
            return (f"{head}\nThe server refuses this host/user/database "
                    "combination. A superuser adds a line for it to "
                    "pg_hba.conf and reloads the configuration.")
        if state == "28000" or "not permitted to log in" in low:
            return (f"{head}\nThe role {who} may not log in. A superuser "
                    f"allows it:\n  ALTER ROLE {who} LOGIN;")
        if state == "3D000" or ("database" in low and "does not exist" in low):
            return (f"{head}\nThe database {entry.get('dbname')!r} does not "
                    f"exist on this server. Check \"dbname\" in {CONFIG_REL}.")
        if state == "53300" or "too many clients" in low:
            return (f"{head}\nThe server is at max_connections. Retry later, "
                    "or ask a DBA which sessions hold the slots.")
        return (f"{head}\nCheck host/port/dbname, the credentials, and that "
                "the server is reachable from here. Use --conn NAME to try a "
                "different entry.")

    def schema_of(self, entry):
        # an unquoted PostgreSQL identifier is lower case in the catalog
        return str(entry.get("schema") or "public").lower()

    def target_of(self, entry):
        host = entry.get("host")
        if not host:
            return ""
        target = f"{host}:{entry.get('port') or self.default_port}"
        return f"{target}/{entry['dbname']}" if entry.get("dbname") else target

    # --- what check asks --------------------------------------------------------

    def server_version(self, conn):
        version, database = q(conn, "server-version.sql")[1][0]
        return f"PostgreSQL {version} — database {database}"

    def current_schema(self, conn):
        rows = q(conn, "current-schema.sql")[1]
        return rows[0][0] if rows and rows[0] and rows[0][0] else None

    # --- the read tier (read.py) -------------------------------------------------

    def object_names(self, conn, schema, pattern, fetch):
        return read.object_names(conn, schema, pattern, fetch)

    def source(self, conn, schema, name):
        return read.source(conn, schema, name)

    def columns(self, conn, schema, name):
        return read.columns(conn, schema, name)

    def ddl(self, conn, schema, name):
        return read.ddl(conn, schema, name)

    def grep(self, conn, schema, text, fetch):
        return read.grep(conn, schema, text, fetch)

    def dependencies(self, conn, schema, name, depth):
        return read.dependencies(conn, schema, name, depth)

    def dependents(self, conn, schema, name, depth):
        return read.dependents(conn, schema, name, depth)

    def compile_errors(self, conn, schema, name):
        return read.compile_errors(conn, schema, name)

    # --- the write tier (write.py) -----------------------------------------------

    def classify(self, text):
        return write.classify(text)

    def prepare_statement(self, text, group):
        return write.prepare_statement(text, group)

    def parse_object(self, stmt, group):
        return write.parse_object(stmt, group)

    def destructive_reason(self, stmt, group):
        return write.destructive_reason(stmt, group)

    def dml_probe(self, stmt):
        return write.dml_probe(stmt)

    def measure_row_set(self, conn, target, pred):
        return write.measure_row_set(conn, target, pred)

    def snapshot(self, conn, schema, group, ident):
        return write.snapshot(conn, schema, group, ident)

    def rehearse(self, conn, schema, group, stmt, ident, snapshot):
        return write.rehearse(conn, schema, group, stmt, ident, snapshot)

    def restore_statement(self, group, ident, before, outcome):
        return write.restore_statement(group, ident, before, outcome)

    def privilege_warning(self, conn, schema):
        return write.privilege_warning(conn, schema)

    # --- the release tier ----------------------------------------------------------

    def split_script(self, text):
        return write.split_script(text)

    # --- the lint tier (rules.py) ---------------------------------------------------

    def lint_rules(self):
        from . import rules
        return list(rules.RULES)

    # --- the harness tier (guard.py) ---------------------------------------------

    def raw_client_pattern(self):
        return guard.CLIENTS

    def write_sql_pattern(self):
        return guard.WRITE_SQL

    def script_pattern(self):
        return guard.SCRIPT

    def connections_template(self):
        return copy.deepcopy(guard.TEMPLATE)

    def skills_dir(self):
        return guard.SKILLS_DIR
