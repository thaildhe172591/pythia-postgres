"""PostgreSQL's lint rules: what PostgreSQL accepts and a reviewer would not.

Each rule reads the statement as the lexer does — strings and comments
blanked, function bodies read as code of their own — so a keyword inside a
literal never fires one. A rule that PostgreSQL itself enforces when the
statement runs (a RAISE with the wrong number of arguments, say) does not
belong here: the rehearsal already reports it.
"""
import re

from .write import _DOLLAR, lex


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def _bodies(stmt):
    """(offset, body) of every dollar-quoted body: a function's code."""
    out, i, code = [], 0, lex(stmt).uncommented
    while True:
        m = _DOLLAR.search(code, i)
        if not m:
            return out
        end = code.find(m.group(0), m.end())
        if end < 0:
            return out
        out.append((m.end(), stmt[m.end():end]))
        i = end + len(m.group(0))


def _code_parts(stmt):
    """(offset, masked code) of the statement and of each body inside it."""
    return [(0, lex(stmt).masked.lower())] + [
        (off, lex(body).masked.lower()) for off, body in _bodies(stmt)]


def _hits(stmt, pattern, message, parts=None):
    out = []
    for off, code in parts if parts is not None else [(0, lex(stmt).masked.lower())]:
        for m in re.finditer(pattern, code):
            out.append((_line(stmt, off + m.start()), message))
    return out


def definer_search_path(stmt, group, run):
    """CREATE FUNCTION ... SECURITY DEFINER, or ALTER FUNCTION ... SECURITY
    DEFINER, with no SET search_path in the same statement."""
    code = lex(stmt).masked.lower()
    m = re.search(r"\bsecurity\s+definer\b", code)
    if not m or re.search(r"\bset\s+search_path\b", code):
        return []
    return [(_line(stmt, m.start()),
             "SECURITY DEFINER runs with its owner's rights, and without SET "
             "search_path any role that can create objects in a schema on the "
             "caller's path can put its own function in the way. Add "
             "SET search_path = <schema>, pg_temp")]


def _ddl(pattern, message):
    def check(stmt, group, run):
        return _hits(stmt, pattern, message) if group == "structural" else []
    return check


def select_star(stmt, group, run):
    if group != "source":
        return []
    return _hits(stmt, r"\bselect\s+(?:distinct\s+)?\*", "SELECT * in stored code: a "
                 "view freezes the column list when it is created, and a "
                 "function breaks when a column is added — name the columns",
                 _code_parts(stmt))


def not_in_subquery(stmt, group, run):
    return _hits(stmt, r"\bnot\s+in\s*\(\s*select\b", "NOT IN (SELECT ...) is "
                 "never true when the subquery returns a NULL — use NOT EXISTS",
                 _code_parts(stmt))


_NAME = r'((?:"[^"]+"|[a-z_][\w$]*)\s*\.\s*)?("[^"]+"|[a-z_][\w$]*)'


def _fold(name):
    return name[1:-1] if name.startswith('"') else name.lower()


def table_comment(stmt, group, run):
    if group != "structural":
        return []
    code = lex(stmt).uncommented
    m = re.match(r"\s*create\s+(?:(?:global|local)\s+)?(?:unlogged\s+)?table\s+"
                 r"(?:if\s+not\s+exists\s+)?" + _NAME, code, re.I)
    if not m:
        return []
    table = _fold(m.group(2))
    for other in run:
        c = re.match(r"\s*comment\s+on\s+table\s+" + _NAME, lex(other).uncommented, re.I)
        if c and _fold(c.group(2)) == table:
            return []
    return [(_line(stmt, m.start(2)), f"table {table} has no COMMENT ON TABLE in this "
             "change — say what a row is, in the same change that creates it")]


RULES = [
    {"id": "pg-definer-search-path", "severity": "error",
     "summary": "SECURITY DEFINER functions set their search_path",
     "check": definer_search_path},
    {"id": "pg-timestamp-without-tz", "severity": "warn",
     "summary": "timestamp without time zone stores a wall-clock time, not a moment",
     "check": _ddl(r"\btimestamp\b(?!\s*(?:\(\s*\d+\s*\))?\s*with\s+time\s+zone)",
                   "timestamp without time zone records a wall-clock time and "
                   "loses the moment — use timestamptz")},
    {"id": "pg-char-n", "severity": "warn",
     "summary": "char(n) pads with spaces",
     "check": _ddl(r"\b(?:char|character)\s*\(\s*\d+\s*\)",
                   "char(n) pads with spaces and compares surprisingly — use "
                   "text or varchar(n)")},
    {"id": "pg-money", "severity": "warn",
     "summary": "money depends on lc_monetary",
     "check": _ddl(r"\bmoney\b", "money is formatted by lc_monetary and rounds "
                   "to it — use numeric")},
    {"id": "pg-serial", "severity": "info",
     "summary": "identity columns over serial",
     "check": _ddl(r"\b(?:small|big)?serial[248]?\b",
                   "serial is a sequence with loose ownership — prefer "
                   "GENERATED ALWAYS AS IDENTITY")},
    {"id": "pg-select-star", "severity": "warn",
     "summary": "no SELECT * in views and functions", "check": select_star},
    {"id": "pg-not-in-subquery", "severity": "warn",
     "summary": "NOT EXISTS over NOT IN (SELECT ...)", "check": not_in_subquery},
    {"id": "pg-table-comment", "severity": "warn",
     "summary": "every new table carries a comment in the same change",
     "check": table_comment},
]
