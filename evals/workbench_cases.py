"""Frozen, repository-authored synthetic cases; not an external or human-reviewed benchmark.

Labels are preassigned from SQL semantics, independently of the evaluated provider's
outputs. Authoring is coding-agent-assisted, NOT claimed to be human-only or LLM-free.
The engine audits labels; it must never silently replace them with observed verdicts.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json


VERSION = "workbench-cases-v1"
SCENARIOS = ("sample", "boundary", "empty", "duplicates")
SEEDS = (0, 17, 73)
DEV_TASKS = ("filter_paid", "null_contacts", "distinct_cities", "group_counts",
             "having_totals", "inner_join_orders")
TEST_TASKS = ("left_join_counts", "left_join_filter", "sum_totals", "order_top")
STUDENT_MESSAGE = ("请核对我当前 SQL 是否满足题面，说明判断依据并给一个提示，不要直接给改写后的 SQL。"
                   "样本一致也请留意边界；没有充分依据时请说明无法判断。")
PROVENANCE = {
    "source": "repository-authored synthetic SQL, coding-agent-assisted",
    "labels": "preassigned semantic labels, independent of evaluated model outputs; engine-audited, not LLM-judged",
    "external_independent": False,
    "human_reviewed": False,
    "split": "fixed task-disjoint 6/4; topics and schemas can overlap",
    "limitations": "finite fixtures are not equivalence proofs; no learner outcomes or teaching-quality labels",
}


@dataclass(frozen=True)
class Case:
    id: str
    task_id: str
    family: str
    expected: str
    sql: str
    rationale: str
    sample_passes_boundary_fails: bool = False
    message: str = STUDENT_MESSAGE

    @property
    def split(self):
        return "dev" if self.task_id in DEV_TASKS else "test"


def _cases(task_id, rows):
    return tuple(Case(f"{task_id}.{index:02d}", task_id, *row)
                 for index, row in enumerate(rows, 1))


# Each row is an authored SQL program, not a paraphrase of a student prompt.
# The third correct-equivalent variant is a negative control for false accusations.
CASES = (
    *_cases("filter_paid", (
        ("equivalent_between", "passed", "SELECT order_id, amount FROM orders WHERE status IN ('paid') AND amount BETWEEN 100 AND 9223372036854775807", "Nonnegative SQLite integers; inclusive lower bound."),
        ("equivalent_demorgan", "passed", "SELECT order_id, amount FROM orders WHERE NOT (status <> 'paid' OR amount < 100)", "Both operands are nonnull."),
        ("equivalent_case", "passed", "SELECT order_id, amount FROM orders WHERE CASE WHEN status = 'paid' THEN amount >= 100 ELSE 0 END", "CASE encodes the conjunction."),
        ("strict_boundary", "mismatch", "SELECT order_id, amount FROM orders WHERE status = 'paid' AND amount > 100", "Excludes exactly 100.", True),
        ("disjunction", "mismatch", "SELECT order_id, amount FROM orders WHERE status = 'paid' OR amount >= 100", "Includes unpaid large and paid small orders."),
        ("missing_status", "mismatch", "SELECT order_id, amount FROM orders WHERE amount >= 100", "Includes pending and cancelled orders."),
        ("missing_amount", "mismatch", "SELECT order_id, amount FROM orders WHERE status = 'paid'", "Includes small paid orders."),
        ("not_pending", "mismatch", "SELECT order_id, amount FROM orders WHERE status <> 'pending' AND amount >= 100", "Cancelled is not paid.", True),
        ("projection_order", "mismatch", "SELECT amount, order_id FROM orders WHERE status = 'paid' AND amount >= 100", "Swaps the required output columns."),
        ("unrequested_limit", "mismatch", "SELECT order_id, amount FROM orders WHERE status = 'paid' AND amount >= 100 LIMIT 1", "Truncates multiple qualifying rows.", True),
    )),
    *_cases("null_contacts", (
        ("equivalent_not_nonnull", "passed", "SELECT customer_id, name FROM customers WHERE NOT (email IS NOT NULL OR phone IS NOT NULL)", "IS predicates are two-valued."),
        ("equivalent_coalesce", "passed", "SELECT customer_id, name FROM customers WHERE COALESCE(email, phone) IS NULL", "COALESCE is NULL exactly when both contacts are NULL."),
        ("equivalent_case", "passed", "SELECT customer_id, name FROM customers WHERE CASE WHEN email IS NULL THEN phone IS NULL ELSE 0 END", "Nested test preserves empty strings."),
        ("equals_null", "mismatch", "SELECT customer_id, name FROM customers WHERE email = NULL AND phone = NULL", "Equality to NULL is unknown, not true."),
        ("either_missing", "mismatch", "SELECT customer_id, name FROM customers WHERE email IS NULL OR phone IS NULL", "Accepts one-sided contacts."),
        ("email_only", "mismatch", "SELECT customer_id, name FROM customers WHERE email IS NULL", "Does not test phone."),
        ("phone_only", "mismatch", "SELECT customer_id, name FROM customers WHERE phone IS NULL", "Does not test email.", True),
        ("empty_as_null", "mismatch", "SELECT customer_id, name FROM customers WHERE COALESCE(email, '') = '' AND COALESCE(phone, '') = ''", "Empty strings are not missing contacts.", True),
        ("dedup_by_name", "mismatch", "SELECT MIN(customer_id), name FROM customers WHERE email IS NULL AND phone IS NULL GROUP BY name", "Different customers may share a name."),
        ("empty_instead_of_null", "mismatch", "SELECT customer_id, name FROM customers WHERE email = '' AND phone = ''", "Selects empty contacts, not NULL contacts."),
    )),
    *_cases("distinct_cities", (
        ("equivalent_group", "passed", "SELECT city FROM customers GROUP BY city", "One group for each value including NULL."),
        ("equivalent_alias_order", "passed", "SELECT DISTINCT c.city AS location FROM customers c ORDER BY location", "Aliases and extra sorting are immaterial here."),
        ("equivalent_nested_distinct", "passed", "SELECT DISTINCT city FROM (SELECT city FROM customers) AS places", "Projection subquery preserves multiplicity before DISTINCT."),
        ("missing_distinct", "mismatch", "SELECT city FROM customers", "Repeated cities survive."),
        ("drops_unknown", "mismatch", "SELECT DISTINCT city FROM customers WHERE city IS NOT NULL", "Loses the requested NULL group."),
        ("null_as_empty", "mismatch", "SELECT DISTINCT COALESCE(city, '') AS city FROM customers", "NULL and empty text must be separate."),
        ("drops_empty", "mismatch", "SELECT DISTINCT city FROM customers WHERE city <> '' OR city IS NULL", "Empty text is a valid distinct city.", True),
        ("distinct_row_not_city", "mismatch", "SELECT DISTINCT customer_id, city FROM customers", "Extra primary key prevents city deduplication."),
        ("only_repeated", "mismatch", "SELECT city FROM customers GROUP BY city HAVING COUNT(*) > 1", "Excludes singleton cities."),
        ("unsupported_union", "rejected", "SELECT city FROM customers UNION SELECT city FROM customers", "SQLite-equivalent, but compound SELECT is outside the workbench subset."),
    )),
    *_cases("group_counts", (
        ("equivalent_nonnull_key", "passed", "SELECT channel, COUNT(visit_id) AS visit_count FROM visits GROUP BY channel", "Primary keys count every visit."),
        ("equivalent_sum_one", "passed", "SELECT channel, SUM(1) AS visit_count FROM visits GROUP BY channel", "Each existing group contains at least one row."),
        ("equivalent_count_literal", "passed", "SELECT channel, COUNT(1) AS visit_count FROM visits GROUP BY channel", "A nonnull constant counts rows."),
        ("count_nullable", "mismatch", "SELECT channel, COUNT(channel) AS visit_count FROM visits GROUP BY channel", "NULL group gets zero.", True),
        ("count_distinct_channel", "mismatch", "SELECT channel, COUNT(DISTINCT channel) AS visit_count FROM visits GROUP BY channel", "Counts values, not visits."),
        ("drops_null_group", "mismatch", "SELECT channel, COUNT(*) AS visit_count FROM visits WHERE channel IS NOT NULL GROUP BY channel", "Discards NULL-channel visits.", True),
        ("missing_group", "mismatch", "SELECT channel, COUNT(*) AS visit_count FROM visits", "SQLite bare column does not group channels."),
        ("groups_by_key", "mismatch", "SELECT channel, COUNT(*) AS visit_count FROM visits GROUP BY visit_id", "One group per visit, rather than per channel."),
        ("singleton_filter", "mismatch", "SELECT channel, COUNT(*) AS visit_count FROM visits GROUP BY channel HAVING COUNT(*) > 1", "Task includes singleton channels."),
        ("null_relabelled", "mismatch", "SELECT COALESCE(channel, 'unknown'), COUNT(*) AS visit_count FROM visits GROUP BY channel", "NULL output must remain NULL.", True),
    )),
    *_cases("having_totals", (
        ("equivalent_integer_bound", "passed", "SELECT team, SUM(amount) AS total FROM pledges GROUP BY team HAVING SUM(amount) >= 101", "Integer amounts make >=101 equivalent to >100."),
        ("equivalent_derived_filter", "passed", "SELECT team, total FROM (SELECT team, SUM(amount) AS total FROM pledges GROUP BY team) AS totals WHERE total > 100", "Filters already aggregated totals."),
        ("equivalent_null_filter", "passed", "SELECT team, SUM(amount) AS total FROM pledges WHERE amount IS NOT NULL GROUP BY team HAVING SUM(amount) > 100", "All-NULL groups cannot qualify anyway."),
        ("inclusive_boundary", "mismatch", "SELECT team, SUM(amount) AS total FROM pledges GROUP BY team HAVING SUM(amount) >= 100", "Exactly 100 must not qualify.", True),
        ("row_filter_before_sum", "mismatch", "SELECT team, SUM(amount) AS total FROM pledges WHERE amount > 100 GROUP BY team", "Drops small contributions before summing."),
        ("distinct_amounts", "mismatch", "SELECT team, SUM(DISTINCT amount) AS total FROM pledges GROUP BY team HAVING SUM(DISTINCT amount) > 100", "Repeated amounts must contribute separately."),
        ("missing_having", "mismatch", "SELECT team, SUM(amount) AS total FROM pledges GROUP BY team", "Includes under-target and all-NULL teams."),
        ("count_for_sum", "mismatch", "SELECT team, COUNT(amount) AS total FROM pledges GROUP BY team HAVING COUNT(amount) > 100", "Counts contributions instead of their amounts."),
        ("max_for_threshold", "mismatch", "SELECT team, SUM(amount) AS total FROM pledges GROUP BY team HAVING MAX(amount) > 100", "Multiple small contributions may exceed 100.", True),
        ("unsupported_window", "rejected", "SELECT team, SUM(amount) OVER (PARTITION BY team) AS total FROM pledges", "Window expressions are intentionally unsupported, not an engine correctness verdict."),
    )),
    *_cases("inner_join_orders", (
        ("equivalent_on_filter", "passed", "SELECT c.name, o.amount FROM orders o JOIN customers c ON o.customer_id = c.customer_id AND o.status = 'paid'", "Inner join permits moving the status predicate into ON."),
        ("equivalent_filtered_left", "passed", "SELECT c.name, o.amount FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'paid'", "WHERE removes unmatched rows, as required for this task."),
        ("equivalent_comma_join", "passed", "SELECT c.name, o.amount FROM customers c, orders o WHERE c.customer_id = o.customer_id AND o.status IN ('paid')", "Cartesian syntax with the full key predicate."),
        ("missing_status", "mismatch", "SELECT c.name, o.amount FROM customers c JOIN orders o ON c.customer_id = o.customer_id", "Includes unpaid orders."),
        ("cartesian_join", "mismatch", "SELECT c.name, o.amount FROM customers c CROSS JOIN orders o WHERE o.status = 'paid'", "Attaches every paid order to every customer."),
        ("wrong_join_key", "mismatch", "SELECT c.name, o.amount FROM customers c JOIN orders o ON c.customer_id = o.order_id WHERE o.status = 'paid'", "Order key is not a customer foreign key."),
        ("dedup_orders", "mismatch", "SELECT DISTINCT c.name, o.amount FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'paid'", "Different orders can have identical name and amount."),
        ("preserves_unmatched", "mismatch", "SELECT c.name, o.amount FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id AND o.status = 'paid'", "Task must not emit customers without a paid order.", True),
        ("drops_zero_amount", "mismatch", "SELECT c.name, o.amount FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'paid' AND o.amount > 0", "Paid zero-amount orders are valid.", True),
        ("unsupported_full_join", "rejected", "SELECT c.name, o.amount FROM customers c FULL OUTER JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'paid'", "FULL JOIN is outside the permitted join subset."),
    )),
    *_cases("left_join_counts", (
        ("equivalent_fk_count", "passed", "SELECT c.customer_id, COUNT(o.customer_id) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id", "Nonnull matched foreign key counts orders, not the padded row."),
        ("equivalent_conditional_sum", "passed", "SELECT c.customer_id, SUM(CASE WHEN o.order_id IS NULL THEN 0 ELSE 1 END) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id", "CASE gives zero for the padded row."),
        ("equivalent_correlated_count", "passed", "SELECT c.customer_id, (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.customer_id) AS order_count FROM customers c", "Correlated aggregate returns zero when no orders exist."),
        ("count_padded_row", "mismatch", "SELECT c.customer_id, COUNT(*) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id", "A padded left row is not an order.", True),
        ("inner_drops_zero", "mismatch", "SELECT c.customer_id, COUNT(o.order_id) AS order_count FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id", "Customers with no orders disappear.", True),
        ("paid_only", "mismatch", "SELECT c.customer_id, COUNT(o.order_id) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id AND o.status = 'paid' GROUP BY c.customer_id", "Counts all statuses, not just paid.", True),
        ("dedup_customer_fk", "mismatch", "SELECT c.customer_id, COUNT(DISTINCT o.customer_id) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id", "Multiple orders collapse to one customer key."),
        ("group_same_names", "mismatch", "SELECT c.customer_id, COUNT(o.order_id) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.name", "Names are not unique customer identifiers."),
        ("having_removes_zero", "mismatch", "SELECT c.customer_id, COUNT(o.order_id) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id HAVING COUNT(o.order_id) > 0", "Explicitly removes the required zero-count customers.", True),
        ("wrong_projection_id", "mismatch", "SELECT o.customer_id, COUNT(o.order_id) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id", "The right key is NULL for unmatched customers.", True),
    )),
    *_cases("left_join_filter", (
        ("equivalent_derived_orders", "passed", "SELECT c.customer_id, o.order_id FROM customers c LEFT JOIN (SELECT order_id, customer_id FROM orders WHERE status = 'paid') o ON c.customer_id = o.customer_id", "Filters the right relation before the outer join."),
        ("equivalent_in_on", "passed", "SELECT c.customer_id, o.order_id FROM customers c LEFT OUTER JOIN orders o ON o.status IN ('paid') AND o.customer_id = c.customer_id", "Singleton IN and reversed conjunction preserve semantics."),
        ("equivalent_distinct_keys", "passed", "SELECT DISTINCT c.customer_id, o.order_id FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id AND o.status = 'paid'", "Each order key is unique; there is only one padded row per unmatched customer."),
        ("where_null_rejects", "mismatch", "SELECT c.customer_id, o.order_id FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'paid'", "Post-join WHERE removes unmatched customers.", True),
        ("where_or_null_patch", "mismatch", "SELECT c.customer_id, o.order_id FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'paid' OR o.order_id IS NULL", "Customers with only unpaid matches still disappear.", True),
        ("inner_instead_left", "mismatch", "SELECT c.customer_id, o.order_id FROM customers c JOIN orders o ON c.customer_id = o.customer_id AND o.status = 'paid'", "Requires paid matches instead of preserving every customer.", True),
        ("missing_paid_filter", "mismatch", "SELECT c.customer_id, o.order_id FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id", "Emits unpaid order identifiers.", True),
        ("or_in_join", "mismatch", "SELECT c.customer_id, o.order_id FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id OR o.status = 'paid'", "Paid orders match unrelated customers."),
        ("collapse_paid_orders", "mismatch", "SELECT c.customer_id, MIN(o.order_id) FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id AND o.status = 'paid' GROUP BY c.customer_id", "Only emits one paid order per customer."),
        ("case_after_unfiltered_join", "mismatch", "SELECT c.customer_id, CASE WHEN o.status = 'paid' THEN o.order_id ELSE NULL END FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id", "Multiple unpaid matches create multiple NULL rows.", True),
    )),
    *_cases("sum_totals", (
        ("equivalent_case_null", "passed", "SELECT SUM(CASE WHEN amount IS NOT NULL THEN amount END) AS total FROM line_items", "Explicit CASE preserves SUM's NULL and empty behavior."),
        ("equivalent_nonnull_filter", "passed", "SELECT SUM(amount) AS total FROM line_items WHERE amount IS NOT NULL", "Removing ignored NULL inputs does not change the aggregate."),
        ("equivalent_abs", "passed", "SELECT SUM(ABS(amount)) AS total FROM line_items", "Amounts are nonnegative; ABS(NULL) is NULL."),
        ("coalesce_result_zero", "mismatch", "SELECT COALESCE(SUM(amount), 0) AS total FROM line_items", "All-NULL and empty inputs must yield NULL.", True),
        ("coalesce_input_zero", "mismatch", "SELECT SUM(COALESCE(amount, 0)) AS total FROM line_items", "All-NULL nonempty input incorrectly becomes zero.", True),
        ("sum_distinct", "mismatch", "SELECT SUM(DISTINCT amount) AS total FROM line_items", "Duplicate amounts must all contribute."),
        ("count_not_sum", "mismatch", "SELECT COUNT(amount) AS total FROM line_items", "Counts nonnull values rather than adding amounts."),
        ("average_not_sum", "mismatch", "SELECT AVG(amount) AS total FROM line_items", "Computes mean rather than total."),
        ("unrequested_grouping", "mismatch", "SELECT SUM(amount) AS total FROM line_items GROUP BY amount", "Returns one row per amount, not one total row."),
        ("having_drops_null_total", "mismatch", "SELECT SUM(amount) AS total FROM line_items HAVING SUM(amount) IS NOT NULL", "Suppresses the required NULL result row.", True),
    )),
    *_cases("order_top", (
        ("equivalent_explicit_nulls", "passed", "SELECT product_id, name, score FROM products ORDER BY score DESC NULLS LAST, product_id LIMIT 3", "Explicitly states SQLite descending NULL placement."),
        ("equivalent_null_sort_key", "passed", "SELECT product_id, name, score FROM products ORDER BY score IS NULL, score DESC, product_id ASC LIMIT 3", "Boolean sort key places NULL last."),
        ("equivalent_negated_score", "passed", "SELECT product_id, name, score FROM products ORDER BY score IS NULL, -score ASC, product_id ASC LIMIT 3", "Negation reverses finite nonnegative scores."),
        ("ascending_score", "mismatch", "SELECT product_id, name, score FROM products ORDER BY score ASC, product_id ASC LIMIT 3", "Chooses lowest scores, including NULL first."),
        ("descending_tie_key", "mismatch", "SELECT product_id, name, score FROM products ORDER BY score DESC, product_id DESC LIMIT 3", "Tied scores must use ascending product keys.", True),
        ("name_tie_key", "mismatch", "SELECT product_id, name, score FROM products ORDER BY score DESC, name ASC, product_id ASC LIMIT 3", "Names cannot replace the required key tie-breaker.", True),
        ("no_limit", "mismatch", "SELECT product_id, name, score FROM products ORDER BY score DESC, product_id ASC", "Returns more than three products."),
        ("only_two", "mismatch", "SELECT product_id, name, score FROM products ORDER BY score DESC, product_id ASC LIMIT 2", "Undershoots the requested top three."),
        ("offset_skips_best", "mismatch", "SELECT product_id, name, score FROM products ORDER BY score DESC, product_id ASC LIMIT 3 OFFSET 1", "Skips the best product."),
        ("nulls_first", "mismatch", "SELECT product_id, name, score FROM products ORDER BY score DESC NULLS FIRST, product_id ASC LIMIT 3", "Unknown scores must sort last."),
    )),
)


def suite_hash():
    payload = {"version": VERSION, "cases": [asdict(case) for case in CASES],
               "dev_tasks": DEV_TASKS, "test_tasks": TEST_TASKS,
               "scenarios": SCENARIOS, "seeds": SEEDS, "provenance": PROVENANCE}
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def select_cases(split="test", ids=None, limit=None):
    if split not in {"dev", "test", "all"}:
        raise ValueError("Unknown split.")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("Limit must be positive.")
    requested = set(ids or ())
    if requested - {case.id for case in CASES}:
        raise ValueError("Unknown case ID.")
    selected = [case for case in CASES if split == "all" or case.split == split]
    if requested - {case.id for case in selected}:
        raise ValueError("Requested case is outside the selected split.")
    selected = [case for case in selected if not requested or case.id in requested]
    return selected[:limit] if limit else selected
