"""One-request subprocess. Started with -I -S, empty env and no inherited FDs.

No application modules, credentials, databases or user-defined SQLite extensions
are loaded. This is defense in depth, not a native-code/OS security sandbox.
"""

import json
import math
import os
import resource
import sqlite3
import sys
import threading
import time

MAX_SQL_BYTES = 8192
MAX_TOKENS = 1600
MAX_NODES = 512
MAX_DEPTH = 32
MAX_JOINS = 4
MAX_SELECTS = 8
MAX_LIMIT = 1000
MAX_ROWS = 1000
MAX_RESULT_BYTES = 128 * 1024
MAX_CELL_BYTES = 4096
MAX_REQUEST_BYTES = 128 * 1024
MEMORY_BYTES = 192 * 1024 * 1024
SQLITE_HEAP_BYTES = 16 * 1024 * 1024
MAX_STEPS = 250_000
QUERY_SECONDS = 0.65
WORKER_SECONDS = 2.0
FUNCTIONS = frozenset({"count", "sum", "avg", "min", "max", "total", "coalesce", "ifnull",
                       "nullif", "abs", "round", "lower", "upper", "length", "like", "iif"})


class Rejected(ValueError):
    pass


def _restrict_resources() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (1, 2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    elif sys.platform != "darwin":
        raise Rejected("sandbox_unavailable")
    # Darwin rejects or ignores RLIMIT_AS/DATA. The parent enforces RSS and
    # SQLite enforces a hard heap cap; this independent watchdog also bounds
    # worker lifetime if the parent is interrupted or disappears.
    deadline = time.monotonic() + WORKER_SECONDS

    def watchdog() -> None:
        while True:
            if time.monotonic() >= deadline:
                os._exit(74)
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform != "darwin":
                rss *= 1024
            if rss > MEMORY_BYTES:
                os._exit(73)
            time.sleep(0.025)

    threading.Thread(target=watchdog, daemon=True).start()


def _validate_sql(sql: str, allowed_tables: list[str]) -> None:
    # SQLGlot is imported only in the restricted process, never in the API.
    import sqlglot
    from sqlglot import exp
    from sqlglot.tokens import TokenType

    if not isinstance(sql, str) or not sql.strip() or "\x00" in sql:
        raise Rejected("invalid_sql")
    if len(sql.encode("utf-8")) > MAX_SQL_BYTES:
        raise Rejected("sql_too_large")
    try:
        tokens = sqlglot.Dialect.get_or_raise("sqlite").tokenize(sql)
        if not tokens or len(tokens) > MAX_TOKENS:
            raise Rejected("query_too_complex")
        nesting = 0
        for index, token in enumerate(tokens):
            if token.token_type == TokenType.SEMICOLON and index != len(tokens) - 1:
                raise Rejected("single_select_required")
            if token.token_type == TokenType.L_PAREN:
                nesting += 1
                if nesting > MAX_DEPTH:
                    raise Rejected("query_too_complex")
            elif token.token_type == TokenType.R_PAREN:
                nesting -= 1
            if len(token.text) > 1024:
                raise Rejected("literal_too_large")
        # SQLGlot models a comment after the final terminator as a separate
        # Semicolon node. Token checks above already exclude interior terminators.
        parse_text = sql[:tokens[-1].start] if tokens[-1].token_type == TokenType.SEMICOLON else sql
        statements = [statement for statement in sqlglot.parse(
            parse_text, read="sqlite", error_level=sqlglot.ErrorLevel.RAISE) if statement is not None]
    except Rejected:
        raise
    except (sqlglot.errors.SqlglotError, RecursionError, ValueError):
        raise Rejected("invalid_sql") from None
    if len(statements) != 1 or type(statements[0]) is not exp.Select:
        raise Rejected("single_select_required")

    # Exact classes, not isinstance(Func): newly added SQLGlot nodes fail closed.
    allowed = {
        exp.Select, exp.From, exp.Table, exp.TableAlias, exp.Identifier, exp.Column,
        exp.Star, exp.Alias, exp.Literal, exp.Null, exp.Boolean, exp.Paren, exp.Subquery,
        exp.Join, exp.Where, exp.Group, exp.Having, exp.Order, exp.Ordered, exp.Limit,
        exp.Offset, exp.Distinct, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
        exp.Is, exp.Not, exp.And, exp.Or, exp.In, exp.Between, exp.Exists,
        exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg, exp.DPipe,
        exp.Case, exp.If, exp.Like, exp.Escape, exp.Cast, exp.DataType,
        exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Coalesce, exp.Nullif,
        exp.Abs, exp.Round, exp.Lower, exp.Upper, exp.Length,
    }
    table_names = {name.lower() for name in allowed_tables}
    stack = [(statements[0], 0)]
    nodes = joins = selects = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise Rejected("query_too_complex")
        if type(node) not in allowed:
            if not (type(node) is exp.Anonymous and node.name.lower() == "total"):
                raise Rejected("unsupported_sql")
        if isinstance(node, exp.Identifier):
            if len(node.name) > 64 or not node.name.isidentifier():
                raise Rejected("invalid_identifier")
        if isinstance(node, exp.Table):
            if (type(node.this) is not exp.Identifier or node.db or node.catalog
                    or node.name.lower() not in table_names):
                raise Rejected("table_not_allowed")
        if isinstance(node, exp.Column) and (node.db or node.catalog):
            raise Rejected("table_not_allowed")
        if isinstance(node, exp.Join):
            joins += 1
            if (joins > MAX_JOINS or node.side.upper() not in ("", "LEFT")
                    or node.kind.upper() not in ("", "INNER", "OUTER", "CROSS")
                    or node.args.get("method")):
                raise Rejected("join_not_allowed")
        if isinstance(node, exp.Select):
            selects += 1
            if selects > MAX_SELECTS or len(node.expressions) > 32:
                raise Rejected("query_too_complex")
        if isinstance(node, (exp.Limit, exp.Offset)):
            value = node.expression
            if (type(value) is not exp.Literal or value.is_string or not value.this.isascii()
                    or not value.this.isdigit() or len(value.this) > 4
                    or not 0 <= int(value.this) <= MAX_LIMIT):
                raise Rejected("limit_not_allowed")
        if isinstance(node, exp.DataType):
            if node.this.value not in {"INT", "BIGINT", "FLOAT", "DOUBLE", "TEXT", "VARCHAR", "DECIMAL"}:
                raise Rejected("unsupported_sql")
        stack.extend((child, depth + 1) for child in node.iter_expressions())


def _sqlite_error_code(error: sqlite3.Error) -> str:
    """Classify known diagnostics without returning identifiers, SQL or paths."""
    if (not isinstance(error, sqlite3.OperationalError)
            or getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_ERROR):
        return "query_error"
    message = str(error)
    for prefix, code in (("no such column: ", "unknown_column"),
                         ("no such table: ", "unknown_table"),
                         ("ambiguous column name: ", "ambiguous_column"),
                         ("misuse of aggregate: ", "invalid_aggregate"),
                         ("misuse of aggregate function ", "invalid_aggregate")):
        if message.startswith(prefix):
            return code
    if (message == "incomplete input"
            or (message.startswith('near "') and message.endswith('": syntax error'))):
        return "syntax_error"
    if message == "HAVING clause on a non-aggregate query":
        return "invalid_aggregate"
    return "query_error"


def _query(payload: dict) -> dict:
    tables = payload["tables"]
    allowed_tables = {table["name"].lower() for table in tables}
    with sqlite3.connect(":memory:", isolation_level=None) as db:
        # Set SQLite's own allocation/compilation limits before loading data.
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_RESULT_BYTES)
        db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_BYTES)
        db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 64)
        db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, MAX_DEPTH + 8)
        db.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 1)
        db.setlimit(sqlite3.SQLITE_LIMIT_VDBE_OP, 20000)
        db.setlimit(sqlite3.SQLITE_LIMIT_FUNCTION_ARG, 16)
        db.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16)
        db.setlimit(sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH, 256)
        db.setlimit(sqlite3.SQLITE_LIMIT_WORKER_THREADS, 0)
        # No temporary files or extension loading, including during sorting.
        if hasattr(db, "enable_load_extension"):
            db.enable_load_extension(False)
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA foreign_keys=ON")
        cap = db.execute(f"PRAGMA hard_heap_limit={SQLITE_HEAP_BYTES}").fetchone()
        if not cap or not 0 < cap[0] <= SQLITE_HEAP_BYTES:
            raise Rejected("sandbox_unavailable")
        for ddl, table in zip(payload["ddl"], tables, strict=True):
            db.execute(ddl)
            placeholders = ",".join("?" for _ in table["columns"])
            db.executemany(f'INSERT INTO "{table["name"]}" VALUES ({placeholders})', table["rows"])
        db.execute("PRAGMA query_only=ON")

        denied = False

        def authorize(action, arg1, arg2, database, source):
            nonlocal denied
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if (action == sqlite3.SQLITE_READ and (arg1 or "").lower() in allowed_tables
                    and (database == "main" or (database is None and arg2 == "")) and source is None):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FUNCTIONS:
                return sqlite3.SQLITE_OK
            denied = True
            return sqlite3.SQLITE_DENY

        db.set_authorizer(authorize)
        steps = 0
        deadline = time.monotonic() + QUERY_SECONDS

        def progress():
            nonlocal steps
            steps += 1000
            return int(steps >= MAX_STEPS or time.monotonic() >= deadline)

        db.set_progress_handler(progress, 1000)
        try:
            cursor = db.execute(payload["sql"])
            columns = [column[0] for column in cursor.description]
            rows = []
            size = len(json.dumps(columns, ensure_ascii=True).encode("utf-8"))
            for row in cursor:
                if time.monotonic() >= deadline:
                    return _failure("timeout", "query_timeout")
                if len(rows) >= MAX_ROWS:
                    return _failure("error", "result_limit_exceeded")
                for cell in row:
                    if (isinstance(cell, bytes) or (isinstance(cell, str) and len(cell.encode()) > MAX_CELL_BYTES)
                            or (isinstance(cell, float) and not math.isfinite(cell))):
                        return _failure("error", "result_limit_exceeded")
                value = list(row)
                size += len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")) + 2
                if size > MAX_RESULT_BYTES:
                    return _failure("error", "result_limit_exceeded")
                rows.append(value)
        except sqlite3.Error as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
                return _failure("timeout", "query_timeout")
            if denied or getattr(exc, "sqlite_errorcode", None) in (sqlite3.SQLITE_AUTH, sqlite3.SQLITE_PERM):
                return _failure("rejected", "query_not_allowed")
            return _failure("error", _sqlite_error_code(exc))
        return {"status": "ok", "columns": columns, "rows": rows, "row_count": len(rows), "error": None}


def _failure(status: str, code: str) -> dict:
    return {"status": status, "columns": [], "rows": [], "row_count": 0, "error": code}


def main() -> None:
    mode = None
    try:
        _restrict_resources()
        # The sole search path addition is the installed, trusted SQLGlot package
        # directory supplied by the parent. -S prevents site/.pth startup code.
        sys.path.insert(0, sys.argv[1])
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise Rejected("request_too_large")
        payload = json.loads(raw)
        mode = payload["mode"]
        _validate_sql(payload["sql"], payload["allowed_tables"])
        result = {"valid": True, "error": None} if mode == "inspect" else _query(payload)
    except Rejected as exc:
        result = ({"valid": False, "error": str(exc)} if mode == "inspect"
                  else _failure("rejected", str(exc)))
    except MemoryError:
        result = _failure("error", "memory_limit_exceeded")
    except Exception:
        # Never return SQLite/parser exceptions, SQL text, paths or tracebacks.
        result = _failure("error", "worker_error")
    sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
