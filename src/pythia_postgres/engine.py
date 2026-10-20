"""PostgreSQL, through psycopg 3, as a pythia-core engine.

Phase 0 answers the connect tier (pythia_core.engine.CONNECT): enough for
`pythia-pg check` to open a read-only session and say where unqualified
names land. The read and write tiers follow (pythia-core's DESIGN.md §7).
"""
import pathlib
import sys

from pythia_core.queries import load_query, run_query

from . import __version__

QUERY_DIR = pathlib.Path(__file__).resolve().parent / "queries"

# Bind contract: what each query file may use. tests/test_postgres.py fails
# on drift in either direction, so queries/ stays reviewable without a
# database.
QUERY_BINDS = {
    "server-version.sql": set(),
    "current-schema.sql": set(),
}

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
        _, rows = run_query(conn, load_query(QUERY_DIR, "server-version.sql"))
        version, database = rows[0]
        return f"PostgreSQL {version} — database {database}"

    def current_schema(self, conn):
        _, rows = run_query(conn, load_query(QUERY_DIR, "current-schema.sql"))
        return rows[0][0] if rows and rows[0] and rows[0][0] else None
