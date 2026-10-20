"""The harness tier: what pythia-core's guard and install need to know
about PostgreSQL. The guard denies psql (and pgcli, pg_restore) when it
would write around the gate; reads through psql are left to the client's
own prompt.

The patterns read a shell command for what it names, never for what it
means, so a write spelled in a way they do not list gets through, and a
read that merely mentions DROP TABLE is denied. The gate behind them holds
either way (pythia-core's SECURITY.md).
"""
import pathlib

CLIENTS = r"psql|pgcli|pg_restore"

# matched against the whole command, quoted SQL included
WRITE_SQL = "|".join((
    r"\b(create|alter|drop|truncate|grant|revoke|reindex|cluster|vacuum|"
    r"comment\s+on|insert\s+into|delete\s+from|merge\s+into|lock\s+table|"
    r"refresh\s+materialized|security\s+label|reassign\s+owned|"
    r"import\s+foreign\s+schema)\b",
    r"\bupdate\s+(only\s+)?[\w\".]+(\s+(as\s+)?\w+)?\s+set\b",
    r"\bdo\s*(\$|')",                         # an anonymous block
    r"\bcall\s+[\w\".]+\s*\(",
    r"\bcopy\b[^;|]*\bfrom\b",                 # COPY / \copy into a table
    r"\bselect\b[^;]*\binto\b",               # SELECT ... INTO makes a table
    # functions that change state from a plain SELECT; sequences advance
    # outside any transaction
    r"\b(nextval|setval|pg_terminate_backend|pg_cancel_backend|lo_unlink|"
    r"lo_import|dblink_exec|pg_reload_conf)\s*\(",
    r"\\i(r|nclude(_relative)?)?\b",           # psql running a script file
))

# matched with quoted text emptied: what the shell hands the client
SCRIPT = "|".join((
    r"(?-i:(^|\s)(-f\s*\S|--file(=|\s)))",      # psql -f (case matters: -F is not)
    r"(^|[^<])<(?![<(&])\s*\S",                 # stdin from a file, not <<, <(
    r"\|\s*(\S*[/\\])?(psql|pgcli)\b",          # a script piped into the client
    r"\bpg_restore\b",                          # a dump into a database
))

TEMPLATE = {
    "default": "dev",
    "dev": {
        "host": "",
        "port": 5432,
        "dbname": "",
        "user": "",
        "password": "",
        "schema": "APP_OWNER",
        "sslmode": "",
    },
}

SKILLS_DIR = pathlib.Path(__file__).resolve().parent / "skills"
