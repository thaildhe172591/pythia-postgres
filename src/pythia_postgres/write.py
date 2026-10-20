"""The write tier for PostgreSQL: pythia's Do movement.

PostgreSQL runs DDL inside a transaction, so every write is rehearsed: run
in the transaction pythia-core opened, verified, and rolled back. A preview
shows what happened, not what would. The confirm run is the same rehearsal,
committed only when it still matches what was approved (gate.py in core).

What this module adds is PostgreSQL's own reading of a statement — a lexer
that knows its quoting ('…', E'…', "…", $tag$…$tag$, nested /* */), the
group each statement belongs to, the rows an UPDATE or DELETE touches — and
its own answers: what an object looked like before, which overload a CREATE
OR REPLACE really replaced, and what plpgsql_check says broke.
"""
import re
import sys

from pythia_core.output import cell
from pythia_core.queries import load_query

from . import read
from .catalog import QUERY_DIR, fold, q

# A rehearsal must not hold locks or rewrite a big table for long; the
# confirm run is the same rehearsal, so the write gets the same bounds.
STATEMENT_TIMEOUT = "30s"
LOCK_TIMEOUT = "5s"
SAMPLE_ROWS = 10


# --- reading a statement ---------------------------------------------------------

class Lexed:
    def __init__(self, masked, cuts, meta, unterminated, uncommented):
        self.masked = masked                # same length; quotes and comments blanked
        self.uncommented = uncommented      # same length; only comments blanked
        self.cuts = cuts                    # positions of statement-ending ;
        self.meta = meta                    # a psql meta-command line (\i, \set ...)
        self.unterminated = unterminated    # ends inside a quote, comment or $$ body


_DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def _word_char(ch):
    return ch.isalnum() or ch in "_$"


def lex(text):
    """Blank out string literals, quoted identifiers, dollar-quoted bodies and
    comments (keeping every position and newline), and find the semicolons
    that end statements. What is left is the code a keyword can be read in."""
    out, bare = list(text), list(text)
    cuts, meta, unterminated = [], False, False
    n, i, line_start = len(text), 0, True

    def blank(a, b, comment=False):
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "
                if comment:
                    bare[k] = " "

    while i < n:
        c = text[i]
        if c == "\n":
            line_start, i = True, i + 1
            continue
        if c in " \t\r\f":
            i += 1
            continue
        if line_start and c == "\\":
            meta = True
        line_start = False
        if text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j, comment=True)
            i = j
        elif text.startswith("/*", i):
            depth, j = 1, i + 2                     # PostgreSQL nests them
            while j < n and depth:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            unterminated |= depth > 0
            blank(i, j, comment=True)
            i = j
        elif c == "'" or (c in "eE" and text.startswith("'", i + 1)
                          and not (i and _word_char(text[i - 1]))):
            backslashes = c != "'"                  # E'...' escapes with \
            j, closed = i + (1 if c == "'" else 2), False
            while j < n:
                if backslashes and text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "'":
                    if text.startswith("''", j):
                        j += 2
                        continue
                    closed, j = True, j + 1
                    break
                j += 1
            unterminated |= not closed
            blank(i, j)
            i = j
        elif c == '"':
            j, closed = i + 1, False
            while j < n:
                if text[j] == '"':
                    if text.startswith('""', j):
                        j += 2
                        continue
                    closed, j = True, j + 1
                    break
                j += 1
            unterminated |= not closed
            blank(i, j)
            i = j
        elif c == "$" and not (i and _word_char(text[i - 1])) \
                and _DOLLAR.match(text, i):
            tag = _DOLLAR.match(text, i).group(0)   # $1 is a parameter, not this
            end = text.find(tag, i + len(tag))
            if end < 0:
                unterminated = True
                blank(i, n)
                i = n
            else:
                blank(i, end + len(tag))
                i = end + len(tag)
        else:
            if c == ";":
                cuts.append(i)
            i += 1
    return Lexed("".join(out), cuts, meta, unterminated, "".join(bare))


def split_statements(text):
    """The statements of a file, each without its ending semicolon; empty
    ones (whitespace, comments) are dropped."""
    lexed = lex(text)
    parts, start = [], 0
    for cut in lexed.cuts + [len(text)]:
        if lexed.masked[start:cut].strip():
            parts.append(text[start:cut].strip())
        start = cut + 1
    return parts


def split_script(text):
    """(line, statement) for each statement of a script, in order, cut where
    PostgreSQL would cut it — never inside a quote, a comment or a $$ body.
    The line is where the statement's code starts, as an editor counts."""
    lexed = lex(text)
    out, start = [], 0
    for cut in lexed.cuts + [len(text)]:
        code = lexed.masked[start:cut]
        if code.strip():
            first = start + len(code) - len(code.lstrip())
            out.append((text.count("\n", 0, first) + 1, text[start:cut].strip()))
        start = cut + 1
    return out


def _code(stmt):
    """The statement's code: literals and comments blanked, lower case, one
    space between words."""
    return " ".join(lex(stmt).masked.lower().split())


TXN = ("pythia-pg owns the transaction: it rolls a preview back and commits only "
       "an approved write. Leave transaction control out of the file.")
NONTX = ("This statement cannot run inside a transaction, so pythia-pg can "
         "neither rehearse it nor roll it back. Run it by hand, with a DBA "
         "watching.")
CANNOT = ("Cannot classify this statement, so it is refused rather than guessed "
          "at. apply takes one CREATE [OR REPLACE] FUNCTION / PROCEDURE / VIEW, "
          "COMMENT ON, INSERT / UPDATE / DELETE, DDL, GRANT or SET statement per "
          "file.")

RULES = (
    (r"(begin|start transaction|commit|end|rollback|abort|savepoint|release|"
     r"prepare transaction|set transaction|set session characteristics|lock)\b",
     None, TXN),
    (r"do\b", None,
     "Anonymous blocks (DO) are refused: a DO block can run anything, so no "
     "policy group honestly fits. Put the logic in a function and apply that."),
    (r"call\b", None,
     "CALL runs a procedure's body, which can do anything — no policy group "
     "honestly fits. Run it by hand, or apply the statements it would run."),
    (r"with\b", None,
     "A WITH statement is refused: a data-modifying WITH hides its writes "
     "inside a query. Write it as a plain INSERT, UPDATE or DELETE."),
    (r"(select|values|table|show|explain|fetch|declare|move|listen|unlisten|"
     r"notify|load|discard|checkpoint|prepare|execute|deallocate)\b", None,
     "apply takes writes; reads go through ls, src, cols and grep — and a "
     "SELECT can call a function that writes, so it is refused, not run."),
    (r"copy\b", None,
     "COPY reads or writes files and streams outside the database; refused."),
    (r"(create (unique )?index concurrently|drop index concurrently|"
     r"reindex\b.*\bconcurrently|vacuum|create database|drop database|"
     r"create tablespace|drop tablespace|alter system|"
     r"(create|alter|drop) subscription)\b", None, NONTX),
    (r"create (or replace )?(temp|temporary)\b", None,
     "A temporary object dies with this connection, which ends after the "
     "command: nothing would be left to verify or undo."),
    (r"create (or replace )?(function|procedure)\b", "source", None),
    (r"create (or replace )?(recursive )?view\b", "source", None),
    (r"comment on (table|column)\b", "comments", None),
    (r"comment on\b", None,
     "Only TABLE and COLUMN comments are snapshotted and restorable; other "
     "comments are refused."),
    (r"(insert|update|delete|merge)\b", "data_dml", None),
    (r"(grant|revoke)\b|alter default privileges\b", "grants", None),
    (r"(set|reset) (session |local )?(role|session authorization)\b", None,
     "SET ROLE and SET SESSION AUTHORIZATION change who the session is — and "
     "so who verifies the write. Refused."),
    (r"(set|reset)\b", "session", None),
    (r"(create|alter|drop|truncate|refresh materialized view|reindex|cluster|"
     r"security label|import foreign schema)\b", "structural", None),
)


def classify(text):
    """(group, None) or (None, why it is refused)."""
    lexed = lex(text)
    if lexed.unterminated:
        return None, ("The file ends inside a quote, a comment or a $$ body, so "
                      "it cannot be read safely — refused.")
    if lexed.meta:
        return None, ("psql meta-commands (\\i, \\set, \\gexec ...) are refused: "
                      "pythia-pg runs SQL, not psql scripts.")
    stmts = split_statements(text)
    if not stmts:
        return None, "The file holds no statement."
    if len(stmts) > 1:
        return None, (f"{len(stmts)} statements in one file — apply takes one "
                      "statement per file, so each is previewed, approved and "
                      "journaled on its own.")
    code = _code(stmts[0])
    for pattern, group, why in RULES:
        if re.match(pattern, code):
            return group, why
    return None, CANNOT


def prepare_statement(text, group):
    return split_statements(text)[0]


_IDENT = re.compile(r'"((?:[^"]|"")+)"|([A-Za-z_][A-Za-z0-9_$]*)')


def _qualified_name(text, pos):
    """The parts of a dotted name starting at pos, folded as PostgreSQL folds
    them: unquoted to lower case, quoted exactly."""
    parts = []
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        m = _IDENT.match(text, pos)
        if not m:
            break
        parts.append(m.group(1).replace('""', '"') if m.group(1) is not None
                     else m.group(2).lower())
        pos = m.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos < len(text) and text[pos] == ".":
            pos += 1
            continue
        break
    return parts


_SOURCE_HEAD = re.compile(r"\s*create\s+(?:or\s+replace\s+)?"
                          r"(function|procedure|(?:recursive\s+)?view)\s+", re.I)
_COMMENT_HEAD = re.compile(r"\s*comment\s+on\s+(table|column)\s+", re.I)


def parse_object(stmt, group):
    # comments blanked, quoted names kept: a blanked "Name" would read as space
    masked = lex(stmt).uncommented
    if group == "source":
        m = _SOURCE_HEAD.match(masked)
        if not m:
            return None
        parts = _qualified_name(stmt, m.end())
        kind = "VIEW" if "view" in m.group(1).lower() else m.group(1).upper()
        return {"type": kind, "name": parts[-1],
                "schema": parts[-2] if len(parts) > 1 else None}
    if group == "comments":
        m = _COMMENT_HEAD.match(masked)
        if not m:
            return None
        parts = _qualified_name(stmt, m.end())
        if m.group(1).lower() == "table":
            return {"type": "COMMENT", "kind": "TABLE", "name": parts[-1],
                    "table": parts[-1], "column": None,
                    "schema": parts[-2] if len(parts) > 1 else None}
        return {"type": "COMMENT", "kind": "COLUMN",
                "name": f"{parts[-2]}.{parts[-1]}", "table": parts[-2],
                "column": parts[-1],
                "schema": parts[-3] if len(parts) > 2 else None}
    return None


REVALIDATE = ("Refused: pythia-pg cannot show you the rows this statement would "
              "touch — {}.\nUPDATE and DELETE are approved on their row set, so "
              "a set nobody can see cannot be approved. Write it as one "
              "statement over one table with a plain WHERE, or run it by hand "
              "with a DBA watching.")


def dml_probe(stmt):
    """(target, predicate or None) of the rows an UPDATE or DELETE touches;
    None for INSERT, which has no rows beforehand. What it cannot read as
    one predicate over one table it refuses: a parser that guesses
    generously is one that lets a row set through unseen."""
    lexed = lex(stmt)
    low = lexed.masked.lower()
    stmt = lexed.uncommented     # same positions; a comment never reaches the probe
    verb = re.match(r"\s*(insert|update|delete|merge)\b", low).group(1)
    if verb == "insert":
        return None
    if verb == "merge":
        sys.exit("Refused: a MERGE cannot be revalidated — the rows it touches "
                 "are decided by a join against its source, so pythia-pg cannot "
                 "show you the set you would be approving.\nExpress it as an "
                 "UPDATE and/or a DELETE, or run it by hand with a DBA watching.")
    if re.search(r"\bselect\b", low):
        sys.exit(REVALIDATE.format("it contains a subquery, so its row set is "
                                   "not one predicate over one table"))
    if re.search(r"\bcurrent\s+of\b", low):
        sys.exit(REVALIDATE.format("WHERE CURRENT OF names a cursor's row, not "
                                   "a predicate"))
    wheres = [w.start() for w in re.finditer(r"\bwhere\b", low)]
    if len(wheres) > 1:
        sys.exit(REVALIDATE.format("it has more than one WHERE"))
    returning = re.search(r"\breturning\b", low)
    stop = returning.start() if returning else len(low)
    if verb == "update":
        start = re.match(r"\s*update\s+(only\s+)?", low).end()
        end = start + re.search(r"\bset\b", low[start:]).start()
        if re.search(r"\bfrom\b", low[end:stop]):
            sys.exit(REVALIDATE.format("UPDATE ... FROM joins another table, so "
                                       "its row set is not one predicate over "
                                       "one table"))
    else:
        start = re.match(r"\s*delete\s+from\s+(only\s+)?", low).end()
        if re.search(r"\busing\b", low[start:stop]):
            sys.exit(REVALIDATE.format("DELETE ... USING joins another table, so "
                                       "its row set is not one predicate over "
                                       "one table"))
        end = wheres[0] if wheres else stop
    if wheres and wheres[0] < end:
        sys.exit(REVALIDATE.format("its WHERE comes before the table it reads"))
    target = stmt[start:end].strip()
    pred = stmt[wheres[0] + 5:stop].strip() if wheres else None
    return target, pred


def destructive_reason(stmt, group):
    """Why a statement destroys something no journal brings back, or None. A
    guess in the safe direction is fine: a false alarm costs one question."""
    m = _code(stmt)
    if group == "structural":
        if m.startswith("drop "):
            return ("DROP removes the object and everything in it"
                    + (" — CASCADE also drops everything that depends on it"
                       if " cascade" in m else ""))
        if m.startswith("truncate"):
            return "TRUNCATE deletes every row, and nothing in the journal brings them back"
        if re.match(r"(create|alter|drop) (role|user|group)\b", m) or " owner to " in m:
            return "account, role and ownership changes reach every session that uses them"
        if re.match(r"alter sequence\b.*\brestart\b", m):
            return "restarting a sequence can hand out keys already in use"
        if re.search(r"\brename\b", m):
            return "renaming breaks every caller that still uses the old name"
        if m.startswith("alter ") and re.search(r"\bdrop\b", m):
            return "ALTER ... DROP removes a column or constraint, and a column's data with it"
        if re.search(r"\balter (column )?\S+ (set data )?type\b", m):
            return ("changing a column's type rewrites the table and can lose what "
                    "the new type cannot hold")
        if m.startswith("create or replace "):
            return ("CREATE OR REPLACE overwrites an existing definition, and this "
                    "kind of object has no snapshot")
    if group == "data_dml":
        if re.match(r"(delete|update)\b", m) and not re.search(r"\bwhere\b", m):
            return "no WHERE clause — it touches every row in the table"
        if re.match(r"(delete|update)\b", m) and re.search(
                r"\bwhere \(?\s*(1 ?= ?1|0 ?= ?0|true)\b", m):
            return "its WHERE clause is always true — it touches every row"
    if group == "grants":
        if m.startswith("revoke "):
            return "REVOKE can break other users' and programs' access"
        if re.search(r"\bto public\b", m):
            return "GRANT ... TO PUBLIC gives every role in the database access"
        if re.search(r"\bwith (grant|admin) option\b", m):
            return "a grant option lets the grantee pass the privilege on"
        if re.search(r"\ball (tables|sequences|functions|routines) in schema\b", m):
            return "ON ALL ... IN SCHEMA reaches every object there at once"
    return None


def quote_ident(name):
    if re.fullmatch(r"[a-z_][a-z0-9_$]*", name):
        return name
    return '"' + name.replace('"', '""') + '"'


def restore_statement(group, ident, before, outcome):
    """The statement that puts it back: the snapshot for a replaced object, a
    DROP for a new one, the old comment (or NULL) for a comment."""
    if group == "source":
        if before.strip():
            text = before.rstrip()
            return text if text.endswith(";") else text + ";"
        return f"DROP {ident['type']} {outcome['drop']};"
    if group == "comments":
        schema = ident.get("schema") or outcome.get("schema")
        target = ".".join(quote_ident(p) for p in
                          (schema, ident["table"], ident["column"]) if p)
        literal = "NULL" if not before else "'" + before.replace("'", "''") + "'"
        return f"COMMENT ON {ident['kind']} {target} IS {literal};"
    return ""


# --- asking the database around a write --------------------------------------------

def _run_text(conn, sql):
    """Run statement text exactly as written: no parameters, so the driver
    reads no % in it (a RAISE format, a LIKE pattern)."""
    with conn.cursor() as cur:
        cur.execute(sql)
        if cur.description is None:
            return [], [], cur.rowcount
        return [d[0] for d in cur.description], cur.fetchall(), cur.rowcount


def measure_row_set(conn, target, pred):
    """Count, fingerprint and sample the rows an UPDATE or DELETE will touch.
    The fingerprint is the rows' ctids: an update between preview and
    confirm gives a row a new one, so it catches a row that changed as well
    as one that joined or left. The text comes from the very file about to
    run, so it opens no door that statement does not open already."""
    where = f"where {pred}" if pred else ""

    def fill(name):
        return (load_query(QUERY_DIR, name).replace("/*TARGET*/", target)
                .replace("/*WHERE*/", where))
    import psycopg
    try:
        _, agg, _ = _run_text(conn, fill("row-set-count.sql"))
        cols, rows, _ = _run_text(conn, fill("row-set-sample.sql"))
    except psycopg.Error as e:
        sys.exit("Refused: pythia-pg could not measure the rows this statement "
                 f"would touch.\n  {target} — {_error_text(e)}\nRevalidation is "
                 "mandatory for UPDATE and DELETE, so a set that cannot be "
                 "measured cannot be approved.")
    n, fingerprint = agg[0]
    return {"target": target, "predicate": pred or "", "count": int(n or 0),
            "hash": fingerprint, "columns": [str(c).upper() for c in cols],
            "sample": [[cell(v) for v in r] for r in rows[:SAMPLE_ROWS]],
            "truncated": len(rows) > SAMPLE_ROWS}


def _code_objects(conn, schema, ident):
    kinds = ("VIEW",) if ident["type"] == "VIEW" else ("FUNCTION", "PROCEDURE")
    return {unit: (kind, qualified, definition)
            for unit, kind, qualified, definition in
            q(conn, "code-objects.sql", s=schema, n=ident["name"])[1]
            if kind in kinds}


def snapshot(conn, schema, group, ident):
    """Everything the statement could replace, as it stands: every overload
    of a function (which one is replaced is the rehearsal's to say), a view,
    or a comment."""
    if group == "source":
        return {unit: d for unit, (_, _, d) in _code_objects(conn, schema, ident).items()}
    if group == "comments":
        rows = q(conn, "comment-current.sql", s=ident.get("schema") or schema,
                 t=ident["table"], c=ident["column"])[1]
        return {ident["name"]: rows[0][0] or ""} if rows else {}
    return {}


def _error_text(e):
    diag = getattr(e, "diag", None)
    first = (getattr(diag, "message_primary", None) or str(e)).strip().splitlines()[0]
    detail = getattr(diag, "message_detail", None)
    state = getattr(e, "sqlstate", None)
    if state == "57014":
        return (f"{first} — a rehearsal is bounded at {STATEMENT_TIMEOUT}, so a "
                "long rewrite is not run in a preview: run it by hand, with a "
                "DBA watching")
    if state == "55P03":
        return (f"{first} — another session holds a lock it needs; the "
                f"rehearsal waits at most {LOCK_TIMEOUT}")
    return first + (f" ({detail})" if detail else "")


def _code_findings(conn, schema):
    """(errors as {(name, type, message)}, blind spot) across the schema —
    the before and after of a rehearsal, the way pythia compares INVALID."""
    rows, blind = read.compile_errors(conn, schema, None)
    return {(str(r[0]), str(r[1]), str(r[5])) for r in rows
            if str(r[4]).lower() == "error"}, blind


def rehearse(conn, schema, group, stmt, ident, snap):
    """Run the statement in the open transaction and verify it. Core rolls
    back after a preview and commits an approved confirm."""
    import psycopg
    q(conn, "rehearsal-limits.sql", st=STATEMENT_TIMEOUT, lt=LOCK_TIMEOUT)
    checked = group in ("source", "structural")
    found_before, _ = _code_findings(conn, schema) if checked else (set(), None)
    try:
        _, _, rowcount = _run_text(conn, stmt)
    except psycopg.Error as e:
        return {"error": _error_text(e)}
    out = {"error": None, "object": None, "type": None, "after": stmt,
           "rows": None, "broken": [], "own_errors": [], "verified": True,
           "blind": None, "notes": [], "schema": schema}
    if group == "source":
        after = _code_objects(conn, schema, ident)
        created = [u for u in after if u not in snap]
        changed = [u for u in after if u in snap and after[u][2] != snap[u]]
        obj = (created + changed + list(after))[0] if after else ident["name"]
        if obj in after:
            out.update(object=obj, type=after[obj][0], after=after[obj][2],
                       drop=after[obj][1])
        if created and snap:
            others = ", ".join(snap)
            out["notes"].append(
                f"{obj} is a new overload: {others} "
                f"{'stays' if len(snap) == 1 else 'stay'} callable — CREATE OR "
                "REPLACE replaces only the same argument types")
        if len(created) + len(changed) > 1:
            out["notes"].append("the statement changed more than one object: "
                                + ", ".join(created + changed))
    elif group == "comments":
        now = snapshot(conn, schema, group, ident)
        out.update(object=ident["name"], type="COMMENT",
                   after=now.get(ident["name"], ""))
    elif group == "data_dml":
        out["rows"] = rowcount
        out["notes"].append("a rehearsal runs the statement's triggers and "
                            "advances any sequence it draws from: rolling back "
                            "undoes the rows, not nextval")
    elif group == "grants":
        out.update(verified=False, blind="who can still do what after a GRANT "
                   "or REVOKE is not something a rehearsal can check")
    if checked:
        found_after, blind = _code_findings(conn, schema)
        own = sorted(f for f in found_after if f[0] == out["object"])
        out["own_errors"] = own
        out["broken"] = sorted(f for f in found_after - found_before if f not in own)
        if blind:
            out.update(verified=False, blind=blind)
    return out


def privilege_warning(conn, schema):
    rows = q(conn, "session-power.sql", s=schema)[1]
    if not rows:
        return None
    superuser, createrole, owns, account = rows[0]
    if superuser:
        return (f"! Connected as a superuser ({account}): this account can do "
                "anything on the server. A role that owns only what it changes "
                "is safer.")
    if createrole:
        return (f"! {account} can create roles: far more power than changing "
                "this schema needs.")
    if owns:
        return (f"! Connected as the owner of schema {schema} ({account}): the "
                "account can drop anything in it. A least-privilege account is "
                "safer.")
    return None
