"""The read tier for PostgreSQL: pythia's Learn movement, asked of the live
catalog.

PostgreSQL's catalog records less than Oracle's in one place that matters:
pg_depend does not see into a PL/pgSQL body, or a SQL function whose body is
a string. The dependency walks therefore ask twice — the catalog, and then a
whole-word search of function source — and mark what only the search vouches
for (how = "text"), naming that blind spot every time instead of returning a
clean-looking answer it cannot stand behind.
"""
import re

from pythia_core.output import TEXT_HOW

from .catalog import fold, q

CATALOG_HOW = "catalog"
FUNCTION_TYPES = ("FUNCTION", "PROCEDURE", "WINDOW FUNCTION", "AGGREGATE")
SOURCE_TYPES = ("FUNCTION", "PROCEDURE", "WINDOW FUNCTION", "VIEW",
                "MATERIALIZED VIEW")
COLUMN_TYPES = ("TABLE", "PARTITIONED TABLE", "VIEW", "MATERIALIZED VIEW",
                "FOREIGN TABLE")
TABLE_TYPES = ("TABLE", "PARTITIONED TABLE")

DDL_NOTE = ("-- rebuilt from the catalog by pythia-pg; pg_dump --schema-only "
            "is the reference")

BLIND_TEXT_IN = (
    "PL/pgSQL bodies and SQL functions with a string body are not in "
    "pg_depend, so functions are matched by name as text ([text]): a column "
    "or variable with the same name gives a false match, and a name built at "
    "run time (EXECUTE format(...)) is not seen at all")
BLIND_TEXT_OUT = (
    "function bodies are read as text against the names of existing tables, "
    "views, sequences and functions ([text]): a variable or column sharing a "
    "name gives a false match, a name built at run time (EXECUTE) is not "
    "seen, and a name that exists in several schemas is listed for each — "
    "search_path decides which one runs")
BLIND_ELSEWHERE = (
    "other databases on this server, and other servers (dblink, "
    "postgres_fdw), are never seen")
NOT_INSTALLED = (
    "plpgsql_check is not installed in this database, so the only check was "
    "PostgreSQL's own, of syntax, when each function was created: a missing "
    "table or column in a PL/pgSQL body shows up at run time. A superuser "
    "can add it where the server has the package: CREATE EXTENSION "
    "plpgsql_check;")


def resolve(conn, schema, name):
    """(classid, objid, type, label, bare_name) of everything holding a name."""
    return q(conn, "resolve.sql", s=schema, n=fold(name))[1]


def object_names(conn, schema, pattern, fetch):
    return q(conn, "object-names.sql", s=schema, p=pattern, n=fetch)


def split_definition(definition):
    return str(definition).rstrip("\n").split("\n")


def source(conn, schema, name):
    rows = []
    for unit, definition in q(conn, "source.sql", s=schema, n=fold(name))[1]:
        rows.extend((unit, i, line)
                    for i, line in enumerate(split_definition(definition), 1))
    return rows


def columns(conn, schema, name):
    rel = [r for r in resolve(conn, schema, name) if r[2] in COLUMN_TYPES]
    if not rel:
        return None
    return q(conn, "columns.sql", objid=rel[0][1])


def table_ddl(conn, objid):
    qname, unlogged, partkey, partof, bound = q(conn, "table-head.sql",
                                                objid=objid)[1][0]
    lines = []
    if partof:
        tail = f" PARTITION BY {partkey}" if partkey else ""
        lines.append(f"CREATE TABLE {qname} PARTITION OF {partof} {bound}{tail};")
    else:
        body = []
        for name, dtype, not_null, default, identity, generated in q(
                conn, "table-columns.sql", objid=objid)[1]:
            col = f"    {name} {dtype}"
            if generated:
                col += f" GENERATED ALWAYS AS ({default}) STORED"
            elif identity:
                col += (" GENERATED " + ("ALWAYS" if identity == "a" else
                                         "BY DEFAULT") + " AS IDENTITY")
            elif default is not None:
                col += f" DEFAULT {default}"
            if not_null:
                col += " NOT NULL"
            body.append(col)
        body.extend(f"    CONSTRAINT {cname} {cdef}" for cname, cdef in
                    q(conn, "table-constraints.sql", objid=objid)[1])
        lines.append(f"CREATE {'UNLOGGED ' if unlogged else ''}TABLE {qname} (")
        lines.append(",\n".join(body))
        lines.append(")" + (f" PARTITION BY {partkey}" if partkey else "") + ";")
    extras = [r[0] for r in q(conn, "table-extras.sql", objid=objid)[1]]
    if extras:
        lines.append("")
        lines.extend(extras)
    return "\n".join(lines)


def ddl(conn, schema, name):
    # names printed back by the catalog follow search_path: fix it first, so
    # the DDL means the same in whatever session runs it
    q(conn, "search-path-catalog.sql")
    objs = resolve(conn, schema, name)
    if not objs:
        return ""
    parts = []
    for _classid, objid, otype, label, _bare in objs:
        if otype in TABLE_TYPES:
            parts.append(table_ddl(conn, objid))
        elif otype == "SEQUENCE":
            parts.append(q(conn, "sequence-ddl.sql", objid=objid)[1][0][0])
        elif otype not in SOURCE_TYPES:
            parts.append(f"-- {label}: pythia-pg does not rebuild the DDL of "
                         f"a {otype} yet; pg_dump --schema-only is the "
                         "reference")
    if any(r[2] in SOURCE_TYPES for r in objs):
        for _unit, definition in q(conn, "source.sql", s=schema, n=fold(name))[1]:
            text = str(definition).rstrip()
            parts.append(text if text.endswith(";") else text + ";")
    if any(r[2] in TABLE_TYPES for r in objs):
        parts.insert(0, DDL_NOTE)
    return "\n\n".join(parts)


GREP_COLS = ("NAME", "TYPE", "LINE", "TEXT")


def grep(conn, schema, text, fetch):
    needle = str(text).lower()
    out = []
    for unit, otype, definition in q(conn, "grep.sql", s=schema, t=text)[1]:
        for i, line in enumerate(split_definition(definition), 1):
            if needle in line.lower():
                out.append((unit, otype, i, line.strip()))
                if len(out) >= fetch:
                    return GREP_COLS, out
    return GREP_COLS, out


# --- dependency walks ---------------------------------------------------------

def word_pattern(name):
    """A PostgreSQL regular expression matching name as a whole word in any
    case (the query uses ~*): every character that is not a letter, digit or
    underscore is escaped."""
    esc = "".join(ch if ch.isalnum() or ch == "_" else "\\" + ch for ch in name)
    return f"\\m{esc}\\M"


_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_QUOTED = re.compile(r'"((?:[^"]|"")+)"')
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def body_names(body):
    """The names a function body could be referring to: unquoted words
    folded to lower case, quoted identifiers exactly. Comments are dropped;
    string literals are kept, because dynamic SQL and nextval('seq') name
    real objects inside them."""
    text = _COMMENTS.sub(" ", str(body or ""))
    names = {m.group(1).replace('""', '"') for m in _QUOTED.finditer(text)}
    names |= {w.lower() for w in _WORD.findall(_QUOTED.sub(" ", text))}
    return names


def bare(name, otype):
    return name.split("(", 1)[0] if otype in FUNCTION_TYPES else name


def walk(roots, depth, children):
    """Depth-first from each root, in the order a tree is read. An object
    reached twice is listed twice (that is the graph) but walked once."""
    rows = []
    seen = {(r[0], r[1]) for r in roots}

    def visit(node, level):
        if level > depth:
            return
        for schema, name, otype, nclass, nobj, how in children(node):
            rows.append((level, schema, name, otype, how))
            if nobj is not None and (nclass, nobj) not in seen:
                seen.add((nclass, nobj))
                visit((nclass, nobj, otype, bare(name, otype)), level + 1)

    for classid, objid, otype, _label, bare_name in roots:
        visit((classid, objid, otype, bare_name), 1)
    return rows


def _overload_note(roots, name):
    if len(roots) > 1:
        labels = ", ".join(r[3] for r in roots)
        return f"{name} names {len(roots)} objects ({labels}); the walk starts from each"
    return None


def dependents(conn, schema, name, depth):
    roots = resolve(conn, schema, name)
    if not roots:
        return None

    def children(node):
        classid, objid, otype, bare_name = node
        out = [(s, n, t, c, o, CATALOG_HOW) for s, n, t, c, o in
               q(conn, "dependents-catalog.sql", classid=classid, objid=objid)[1]]
        seen = {o for *_, o, _ in out if o is not None}
        for s, n, t, c, o in q(conn, "dependents-text.sql",
                               pattern=word_pattern(bare_name), objid=objid)[1]:
            if o not in seen:
                out.append((s, n, t, c, o, TEXT_HOW))
        return out

    rows = walk(roots, depth, children)
    notes = [n for n in (_overload_note(roots, name), BLIND_TEXT_IN,
                         BLIND_ELSEWHERE) if n]
    return rows, notes


def dependencies(conn, schema, name, depth):
    roots = resolve(conn, schema, name)
    if not roots:
        return None
    cache = {}

    def candidates():
        if "all" not in cache:
            by_name = {}
            for bare_name, *rest in q(conn, "name-candidates.sql")[1]:
                by_name.setdefault(bare_name, []).append(tuple(rest))
            cache["all"] = by_name
        return cache["all"]

    def children(node):
        classid, objid, otype, _bare = node
        out = [(s, n, t, c, o, CATALOG_HOW) for s, n, t, c, o in
               q(conn, "dependencies-catalog.sql", classid=classid, objid=objid)[1]]
        if otype not in FUNCTION_TYPES:
            return out
        found = q(conn, "function-body.sql", objid=objid)[1]
        if not found or found[0][0] not in ("plpgsql", "sql"):
            return out
        seen = {o for *_, o, _ in out if o is not None} | {objid}
        words = body_names(found[0][1])
        for word in sorted(words):
            for s, n, t, c, o in candidates().get(word, ()):
                if o not in seen:
                    seen.add(o)
                    out.append((s, n, t, c, o, TEXT_HOW))
        return out

    rows = walk(roots, depth, children)
    notes = [n for n in (_overload_note(roots, name), BLIND_TEXT_OUT,
                         BLIND_ELSEWHERE) if n]
    return rows, notes


# --- errors -----------------------------------------------------------------------

def compile_errors(conn, schema, name):
    if name is not None:
        objs = resolve(conn, schema, name)
        if not objs:
            return None
        if not any(r[2] in FUNCTION_TYPES for r in objs):
            return [], (f"{name} is a {objs[0][2]}, not a function: there is no "
                        "PL/pgSQL body for plpgsql_check to read")
    if not q(conn, "plpgsql-check-installed.sql")[1][0][0]:
        return [], NOT_INSTALLED
    n = fold(name) if name is not None else None
    # unqualified names in a body resolve by search_path at run time; check
    # them the way the schema's own application resolves them
    _path, usage, account = q(conn, "search-path-first.sql", s=schema)[1][0]
    if not usage:
        return [], (f"this account has no USAGE on schema {schema}, so "
                    "PostgreSQL leaves it off search_path and every name in "
                    "it would look missing to plpgsql_check — no list is "
                    "better than a false one. A DBA grants it: GRANT USAGE "
                    f"ON SCHEMA {schema} TO {account};")
    rows = q(conn, "plpgsql-check.sql", s=schema, n=n)[1]
    unchecked = [r[0] for r in q(conn, "plpgsql-unchecked.sql", s=schema, n=n)[1]]
    blind = None
    if unchecked:
        blind = (f"not checked: {', '.join(unchecked)} — plpgsql_check reads a "
                 "trigger function through a table whose trigger uses it, and "
                 "these have none (or are event trigger functions)")
    return rows, blind
