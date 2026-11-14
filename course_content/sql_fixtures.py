"""Reviewed synthetic data and SQL templates for the diagnostic lab."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Fixture:
    id: str
    topic: str
    tables: dict[str, dict[str, str]]
    rows: dict[str, tuple[tuple, ...]]
    queries: dict[str, str]


GROUPING_FIXTURE = "grouping_having@1"
GROUPING_VARIANT = "grouping_having_variant@1"
JOIN_FIXTURE = "left_join_predicate@1"
JOIN_VARIANT = "left_join_predicate_variant@1"

GROUP_COUNTS = "SELECT category, COUNT(*) AS parcel_count FROM parcels GROUP BY category"
GROUPING_QUERIES = {
    "group_counts": GROUP_COUNTS + " ORDER BY category",
    "having_gt": GROUP_COUNTS + " HAVING COUNT(*) > :min_count ORDER BY category",
    "having_gte": GROUP_COUNTS + " HAVING COUNT(*) >= :min_count ORDER BY category",
}

JOIN_FROM = " FROM accounts a LEFT JOIN orders o ON a.id = o.account_id"
JOIN_BASE = "SELECT a.id AS account_id, o.status" + JOIN_FROM
JOIN_QUERIES = {
    "join_on": JOIN_BASE + " AND o.status = 'paid' ORDER BY a.id",
    "join_where": JOIN_BASE + " WHERE o.status = 'paid' ORDER BY a.id",
    "join_count_all": "SELECT COUNT(*) AS total" + JOIN_FROM,
    "join_count_matched": "SELECT COUNT(o.account_id) AS total" + JOIN_FROM,
}
JOIN_TABLES = {
    "accounts": {"id": "INTEGER PRIMARY KEY"},
    "orders": {"account_id": "INTEGER PRIMARY KEY", "status": "TEXT NOT NULL"},
}


def grouping(fixture_id: str, counts: tuple[int, ...]) -> Fixture:
    categories = tuple((index, category) for index, category in enumerate(
        (category for category, count in zip("ABCD", counts, strict=True) for _ in range(count)), start=1
    ))
    return Fixture(fixture_id, "aggregate", {"parcels": {"id": "INTEGER PRIMARY KEY", "category": "TEXT NOT NULL"}},
                   {"parcels": categories}, GROUPING_QUERIES)


def left_join(fixture_id: str, orders: tuple[tuple, ...]) -> Fixture:
    return Fixture(fixture_id, "join", JOIN_TABLES, {"accounts": ((1,), (2,), (3,)), "orders": orders}, JOIN_QUERIES)


FIXTURES = {
    GROUPING_FIXTURE: grouping(GROUPING_FIXTURE, (4, 2, 2, 1)),
    GROUPING_VARIANT: grouping(GROUPING_VARIANT, (4, 1, 1, 1)),
    JOIN_FIXTURE: left_join(JOIN_FIXTURE, ((1, "paid"), (3, "pending"))),
    JOIN_VARIANT: left_join(JOIN_VARIANT, ((1, "paid"), (2, "paid"), (3, "paid"))),
}

PARAMETERIZED_QUERIES = frozenset({"having_gt", "having_gte"})
