"""Execute parameterized templates in a fresh, read-only SQLite session."""

from contextlib import closing
from hashlib import sha256
import json
import sqlite3
from time import monotonic

from course_content.sql_fixtures import FIXTURES, PARAMETERIZED_QUERIES


ROW_LIMIT = 50


class LabError(ValueError):
    """A safe error to return to a diagnostic caller."""


def describe(fixture_id: str) -> dict:
    fixture = FIXTURES.get(fixture_id)
    if fixture is None:
        raise LabError("unknown_fixture")
    return {
        "fixture_id": fixture.id,
        "version": 1,
        "dialect": "sqlite",
        "tables": fixture.tables,
        "queries": {
            query: {"sql": sql, "parameters": {} if query not in PARAMETERIZED_QUERIES else {
                "min_count": {"type": "integer", "minimum": 0, "maximum": 50, "required": True},
            }}
            for query, sql in fixture.queries.items()
        },
    }


def execute(fixture_id: str, query_id: str, parameters: dict, *, timeout: float = 1.0) -> dict:
    fixture = FIXTURES.get(fixture_id)
    if fixture is None:
        raise LabError("unknown_fixture")
    if query_id not in fixture.queries:
        raise LabError("unknown_query")
    if query_id not in PARAMETERIZED_QUERIES:
        if parameters:
            raise LabError("invalid_parameters")
    elif (set(parameters) != {"min_count"} or type(parameters["min_count"]) is not int
          or not 0 <= parameters["min_count"] <= 50):
        raise LabError("invalid_parameters")

    start = monotonic()
    deadline = start + timeout
    sql = fixture.queries[query_id]

    def authorize(action, arg1, arg2, database, trigger):
        if (action == sqlite3.SQLITE_SELECT
                or (action == sqlite3.SQLITE_READ and arg1 in fixture.tables and database in (None, "main"))
                or (action == sqlite3.SQLITE_FUNCTION and arg2 == "count")):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    try:
        with closing(sqlite3.connect(":memory:")) as db:
            for table, columns in fixture.tables.items():
                definition = ", ".join(f"{name} {type_}" for name, type_ in columns.items())
                placeholders = ", ".join("?" for _ in columns)
                db.execute(f"CREATE TABLE {table} ({definition})")
                db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", fixture.rows[table])
            db.execute("PRAGMA query_only=ON")
            db.set_authorizer(authorize)
            db.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
            cursor = db.execute(sql, parameters)
            rows = [list(row) for row in cursor.fetchmany(ROW_LIMIT + 1)]
            columns = [column[0] for column in cursor.description]
    except sqlite3.Error as error:
        code = "query_timeout" if monotonic() >= deadline else "query_rejected"
        raise LabError(code) from error

    if monotonic() >= deadline:
        raise LabError("query_timeout")
    if len(rows) > ROW_LIMIT:
        raise LabError("row_limit_exceeded")
    result = {"fixture_id": fixture.id, "query_id": query_id, "sql": sql,
              "parameters": dict(parameters), "columns": columns, "rows": rows, "row_count": len(rows)}
    digest = sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return {**result, "fingerprint": digest, "elapsed_ms": round((monotonic() - start) * 1000, 3)}


def compare(before: dict, after: dict) -> dict:
    if before["fixture_id"] != after["fixture_id"] or before["columns"] != after["columns"]:
        raise LabError("incompatible_observations")
    left = {str(row[0]): row for row in before["rows"]}
    right = {str(row[0]): row for row in after["rows"]}
    return {
        "before_row_count": before["row_count"], "after_row_count": after["row_count"],
        "removed_keys": sorted(left.keys() - right.keys()),
        "added_keys": sorted(right.keys() - left.keys()),
        "changed_keys": sorted(key for key in left.keys() & right.keys() if left[key] != right[key]),
    }
