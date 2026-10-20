"""Where pythia-pg's SQL lives and how it is run.

Every statement is a file in queries/, under pythia-core's contract:
pyformat binds, a header, and its binds declared here. tests/test_postgres.py
fails on drift in either direction, so queries/ stays reviewable without a
database.
"""
import pathlib

from pythia_core.queries import load_query, run_query

QUERY_DIR = pathlib.Path(__file__).resolve().parent / "queries"

QUERY_BINDS = {
    "server-version.sql": set(),
    "current-schema.sql": set(),
    "resolve.sql": {"s", "n"},
    "object-names.sql": {"s", "p", "n"},
    "source.sql": {"s", "n"},
    "columns.sql": {"objid"},
    "table-head.sql": {"objid"},
    "table-columns.sql": {"objid"},
    "table-constraints.sql": {"objid"},
    "table-extras.sql": {"objid"},
    "sequence-ddl.sql": {"objid"},
    "grep.sql": {"s", "t"},
    "dependents-catalog.sql": {"classid", "objid"},
    "dependents-text.sql": {"pattern", "objid"},
    "dependencies-catalog.sql": {"classid", "objid"},
    "function-body.sql": {"objid"},
    "name-candidates.sql": set(),
    "plpgsql-check-installed.sql": set(),
    "search-path-first.sql": {"s"},
    "plpgsql-check.sql": {"s", "n"},
    "plpgsql-unchecked.sql": {"s", "n"},
}


def q(conn, name, **binds):
    """(COLUMNS, rows) for one query file. Column names are upper case, as
    every pythia engine reports them."""
    cols, rows = run_query(conn, load_query(QUERY_DIR, name), binds)
    return [str(c).upper() for c in cols], rows


def fold(name):
    """A name as the catalog holds it: an unquoted identifier folds to lower
    case; a double-quoted one is taken exactly, quotes removed."""
    name = str(name).strip()
    if len(name) >= 2 and name[0] == name[-1] == '"':
        return name[1:-1].replace('""', '"')
    return name.lower()
