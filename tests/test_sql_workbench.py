"""Synthetic-only tests; never open real databases or read application secrets."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
import subprocess
import sys
from threading import Event
from time import monotonic

import pytest

from course_content.sql_tasks import SCENARIOS, _get_task, public_tasks, task_view
from sql_lab import query_worker, workbench
from sql_lab.workbench import dataset_view, evaluate, inspect_sql, run_query


IDS = ("filter_paid", "null_contacts", "distinct_cities", "group_counts", "having_totals",
       "inner_join_orders", "left_join_counts", "left_join_filter", "sum_totals", "order_top")


def _oracle(task_id, tables):
    """Independent Python semantics for the trusted reference queries."""
    data = {table["name"]: table["rows"] for table in tables}
    if task_id == "filter_paid":
        return [[key, amount] for key, status, amount in data["orders"] if status == "paid" and amount >= 100]
    if task_id == "null_contacts":
        return [[key, name] for key, name, email, phone in data["customers"] if email is None and phone is None]
    if task_id == "distinct_cities":
        return [[city] for city in dict.fromkeys(row[1] for row in data["customers"])]
    if task_id == "group_counts":
        return [[channel, count] for channel, count in Counter(row[1] for row in data["visits"]).items()]
    if task_id == "having_totals":
        teams = dict.fromkeys(row[1] for row in data["pledges"])
        result = []
        for team in teams:
            amounts = [row[2] for row in data["pledges"] if row[1] == team and row[2] is not None]
            if amounts and sum(amounts) > 100:
                result.append([team, sum(amounts)])
        return result
    if task_id == "inner_join_orders":
        return [[name, amount] for key, name in data["customers"]
                for _, customer_id, status, amount in data["orders"] if key == customer_id and status == "paid"]
    if task_id == "left_join_counts":
        return [[key, sum(row[1] == key for row in data["orders"])] for key, _ in data["customers"]]
    if task_id == "left_join_filter":
        result = []
        for key, _ in data["customers"]:
            orders = [row[0] for row in data["orders"] if row[1] == key and row[2] == "paid"]
            result.extend([[key, order_id] for order_id in (orders or [None])])
        return result
    if task_id == "sum_totals":
        amounts = [amount for _, amount in data["line_items"] if amount is not None]
        return [[sum(amounts) if amounts else None]]
    if task_id == "order_top":
        return sorted(data["products"], key=lambda row: (row[2] is None, -(row[2] or 0), row[0]))[:3]
    raise AssertionError(task_id)


@pytest.mark.parametrize("task_id", IDS)
@pytest.mark.parametrize("seed", [0, 31])
def test_every_reference_passes_all_scenarios_and_python_oracle(task_id, seed):
    task = _get_task(task_id)
    report = evaluate(task_id, task.reference_sql, seed=seed)
    assert report["status"] == "passed", report
    assert report["passed"] and report["checked"] == report["total"] == 4
    assert report["counterexample"] is None
    assert "有限" in report["message"] and "不构成" in report["message"]
    for scenario in SCENARIOS:
        result = run_query(task_id, task.reference_sql, scenario, seed)
        expected = _oracle(task_id, dataset_view(task_id, scenario, seed)["tables"])
        assert result["status"] == "ok", result
        if task.ordered:
            assert result["rows"] == expected
        else:
            assert Counter(map(tuple, result["rows"])) == Counter(map(tuple, expected))
        assert result["row_count"] == len(expected)
        assert result["scenario"] == scenario and result["seed"] == seed


@pytest.mark.parametrize("task_id", IDS)
def test_generated_data_is_reproducible_constrained_and_not_relabelled(task_id):
    task = _get_task(task_id)
    samples = []
    for scenario in SCENARIOS:
        first = dataset_view(task_id, scenario, 9)
        assert first == dataset_view(task_id, scenario, 9)
        if scenario != "empty":
            assert first["tables"] != dataset_view(task_id, scenario, 10)["tables"]
        samples.append(first["tables"])
        with sqlite3.connect(":memory:") as db:
            db.execute("PRAGMA foreign_keys=ON")
            for spec, table in zip(task.tables, first["tables"], strict=True):
                assert len(table["columns"]) == len(table["types"])
                assert len({row[0] for row in table["rows"]}) == len(table["rows"])
                db.execute(spec.ddl)
                for row in table["rows"]:
                    assert len(row) == len(table["columns"])
                    db.execute(f'INSERT INTO "{spec.name}" VALUES ({",".join("?" for _ in row)})', row)
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert len({json.dumps(tables, sort_keys=True) for tables in samples}) == 4
    # Scenario content differs beyond generated IDs and row order.
    signatures = [sorted([sorted([repr(row[1:]) for row in table["rows"]]) for table in tables])
                  for tables in samples]
    assert len({repr(value) for value in signatures}) == 4


def test_public_contract_and_answers_never_leak():
    assert [task["id"] for task in public_tasks()] == list(IDS)
    for item in public_tasks():
        assert set(item) == {"id", "title", "topic", "concepts"}
        view = task_view(item["id"])
        assert set(view) == {"id", "title", "prompt", "topic", "concepts", "starter_sql",
                             "dialect", "version", "tables", "ordered"}
        assert view["dialect"] == "sqlite" and view["version"] == 1
        assert view["ordered"] == (item["id"] == "order_top")
        assert view["tables"] == dataset_view(item["id"])["tables"]
        report = evaluate(item["id"], "SELECT 1")
        serialized = json.dumps([item, view, report], ensure_ascii=False)
        assert "reference_sql" not in serialized
        assert _get_task(item["id"]).reference_sql not in serialized
    view = task_view("sum_totals")
    view["tables"][0]["rows"][0][1] = "modified"
    assert view != task_view("sum_totals")
    with pytest.raises(ValueError, match="^unknown_task$"):
        task_view("secret-path-not-to-be-echoed")


EQUIVALENT = {
    "filter_paid": "SELECT order_id AS id, amount FROM orders WHERE NOT (status <> 'paid' OR amount < 100)",
    "null_contacts": "SELECT customer_id, name FROM customers WHERE NOT (email IS NOT NULL OR phone IS NOT NULL)",
    "distinct_cities": "SELECT city FROM customers GROUP BY city",
    "group_counts": "SELECT channel, COUNT(visit_id) FROM visits GROUP BY channel",
    "having_totals": "SELECT team, SUM(amount) FROM pledges GROUP BY team HAVING 100 < SUM(amount)",
    "inner_join_orders": "SELECT c.name, o.amount FROM orders o, customers c "
                         "WHERE o.customer_id=c.customer_id AND o.status='paid'",
    "left_join_counts": "SELECT c.customer_id, (SELECT COUNT(*) FROM orders o "
                        "WHERE o.customer_id=c.customer_id) FROM customers c",
    "left_join_filter": "SELECT c.customer_id, p.order_id FROM customers c LEFT JOIN "
                        "(SELECT order_id, customer_id FROM orders WHERE status='paid') p "
                        "ON c.customer_id=p.customer_id",
    "sum_totals": "SELECT SUM(amount + 0) FROM line_items",
    "order_top": "SELECT p.product_id, p.name, p.score FROM products p "
                 "ORDER BY p.score DESC, p.product_id ASC LIMIT 3",
}


@pytest.mark.parametrize("task_id,sql", EQUIVALENT.items())
def test_valid_equivalent_queries(task_id, sql):
    assert inspect_sql(task_id, sql) == {"valid": True, "error": None}
    report = evaluate(task_id, sql, seed=42)
    assert report["status"] == "passed", report


@pytest.mark.parametrize("task_id,sql", [
    ("filter_paid", "SELECT order_id, amount FROM orders WHERE status='paid' AND amount>100"),
    ("having_totals", "SELECT team, SUM(amount) FROM pledges GROUP BY team HAVING SUM(amount)>=100"),
    ("left_join_counts", "SELECT c.customer_id, COUNT(*) FROM customers c LEFT JOIN orders o "
                         "ON c.customer_id=o.customer_id GROUP BY c.customer_id"),
    ("left_join_filter", "SELECT c.customer_id, o.order_id FROM customers c LEFT JOIN orders o "
                         "ON c.customer_id=o.customer_id WHERE o.status='paid'"),
])
def test_boundary_counterexample_after_sample_passes(task_id, sql):
    report = evaluate(task_id, sql, seed=5)
    assert report["status"] == "mismatch" and not report["passed"]
    assert report["checked"] == 2 and report["total"] == 4
    example = report["counterexample"]
    assert example["scenario"] == "boundary" and example["seed"] == 5
    assert example["tables"] == dataset_view(task_id, "boundary", 5)["tables"]
    assert example["actual"]["fingerprint"] == run_query(task_id, sql, "boundary", 5)["fingerprint"]
    assert example["actual"]["rows"] != example["expected"]["rows"]
    assert report["query_result"]["scenario"] == "sample"


def test_empty_aggregate_null_is_not_zero_or_no_rows():
    assert run_query("sum_totals", "SELECT SUM(amount) FROM line_items", "empty")["rows"] == [[None]]
    for scenario in ("boundary", "empty"):
        report = evaluate("sum_totals", "SELECT COALESCE(SUM(amount),0) FROM line_items", [scenario])
        assert report["status"] == "mismatch"
        assert report["counterexample"]["expected"]["rows"] == [[None]]
    report = evaluate("sum_totals", "SELECT SUM(amount) FROM line_items GROUP BY amount", ["empty"])
    assert report["status"] == "mismatch"
    assert report["counterexample"]["actual"]["rows"] == []


@pytest.mark.parametrize("task_id,sql", [
    ("distinct_cities", "SELECT city FROM customers"),
    ("inner_join_orders", "SELECT DISTINCT c.name, o.amount FROM customers c JOIN orders o "
                          "ON c.customer_id=o.customer_id WHERE o.status='paid'"),
    ("group_counts", "SELECT channel, COUNT(channel) FROM visits GROUP BY channel"),
    ("sum_totals", "SELECT SUM(DISTINCT amount) FROM line_items"),
    ("null_contacts", "SELECT customer_id, name FROM customers WHERE email=NULL AND phone=NULL"),
])
def test_duplicates_and_nulls_are_not_collapsed(task_id, sql):
    report = evaluate(task_id, sql, ["duplicates"])
    assert report["status"] == "mismatch", report
    assert report["counterexample"]["scenario"] == "duplicates"


def test_order_column_count_and_value_comparison():
    expected = {"columns": ["x"], "rows": [[None], [None], [0], [""]]}
    assert workbench._same_result(expected, {"columns": ["renamed"], "rows": [[0], [None], [""], [None]]}, False)
    assert not workbench._same_result(expected, {"columns": ["x"], "rows": [[None], [0], [""]]}, False)
    assert not workbench._same_result(expected, {"columns": ["x"], "rows": [[0], [None], [""], [None]]}, True)
    assert not workbench._same_result({"columns": ["x"], "rows": []}, {"columns": ["x", "y"], "rows": []}, False)
    assert not workbench._same_result({"columns": ["x"], "rows": [[1]]}, {"columns": ["x"], "rows": [["1"]]}, False)
    report = evaluate("order_top", "SELECT product_id,name,score FROM products ORDER BY score DESC,product_id DESC LIMIT 3", ["boundary"])
    assert report["status"] == "mismatch"
    report = evaluate("distinct_cities", "SELECT DISTINCT city, city FROM customers", ["empty"])
    assert report["status"] == "mismatch"


@pytest.mark.parametrize("sql", [
    "SELECT 1; SELECT 2", "SELECT 1; -- comment\nDELETE FROM orders", "SELECT 1;/* x */;",
    "SELECT 1/**/; ATTACH ':memory:' AS other", "SELECT 1;\x00SELECT 2",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT * FROM x",
    "PRAGMA table_info(orders)", "ATTACH ':memory:' AS other", "DETACH main",
    "DELETE FROM orders RETURNING *", "UPDATE orders SET amount=0", "DROP TABLE orders",
    "INSERT INTO orders VALUES (1,'paid',100)", "CREATE TABLE x(a)", "VACUUM INTO 'blocked.db'",
    "EXPLAIN SELECT * FROM orders", "SELECT * FROM orders UNION SELECT * FROM orders",
    "SELECT * FROM sqlite_master", "SELECT * FROM main.orders", "SELECT * FROM temp.orders",
    "SELECT * FROM schema.sqlite_master", "SELECT * FROM sqlite_schema", "SELECT * FROM customers",
    "SELECT * FROM pragma_table_info('orders')", "SELECT * FROM json_each('[1]')",
    "SELECT load_extension('blocked')", "SELECT readfile('blocked')", "SELECT writefile('blocked','x')",
    "SELECT sqlite_version()", "SELECT randomblob(1000000000)", "SELECT zeroblob(1000000000)",
    "SELECT printf('%1000000000s','x')", "SELECT hex(amount) FROM orders", "SELECT random()",
    "SELECT group_concat(status) FROM orders", "SELECT row_number() OVER () FROM orders",
    "SELECT ?", "SELECT ?1", "SELECT :secret", "SELECT @secret", "SELECT $secret",
    "SELECT * FROM orders LIMIT -1", "SELECT * FROM orders LIMIT 1001",
    "SELECT * FROM orders LIMIT (SELECT 1)", "SELECT * FROM orders LIMIT 1 OFFSET 1001",
    "SELECT * FROM orders NATURAL JOIN orders b", "SELECT * FROM orders RIGHT JOIN orders b ON 1=1",
])
def test_strict_rejections(sql):
    validation = inspect_sql("filter_paid", sql)
    assert validation["valid"] is False, (sql, validation)
    assert validation["error"]
    result = run_query("filter_paid", sql)
    assert result["status"] == "rejected", (sql, result)
    assert result["rows"] == result["columns"] == [] and result["row_count"] == 0
    assert result["error"] and sql not in result["error"]


def test_comments_semicolon_string_and_allowed_functions_are_not_false_positives():
    for sql in ("SELECT ';' AS punctuation; -- one statement", "SELECT 1 /* ; DROP TABLE orders; */",
                "SELECT COUNT(*), SUM(amount), AVG(amount), MIN(amount), MAX(amount) FROM orders",
                "SELECT CASE WHEN amount>=100 THEN 1 ELSE 0 END FROM orders",
                "SELECT CAST(amount AS REAL), COALESCE(NULL, amount), NULLIF(amount,0), "
                "ABS(amount), ROUND(amount,1), LOWER(status), UPPER(status), LENGTH(status) FROM orders",
                "SELECT * FROM orders WHERE EXISTS (SELECT 1 FROM orders b WHERE b.order_id=orders.order_id)"):
        assert inspect_sql("filter_paid", sql)["valid"], sql
        assert run_query("filter_paid", sql)["status"] == "ok", sql


def test_length_depth_nodes_join_and_result_limits():
    cases = ["SELECT 1" + " " * query_worker.MAX_SQL_BYTES,
             "SELECT " + "(" * 40 + "1" + ")" * 40,
             "SELECT 1 WHERE " + " AND ".join("1=1" for _ in range(180)),
             "SELECT COUNT(*) FROM orders a " + " ".join(f"CROSS JOIN orders a{i}" for i in range(5)),
             "SELECT " + ",".join("1" for _ in range(33))]
    for sql in cases:
        assert not inspect_sql("filter_paid", sql)["valid"]
    sql = "SELECT a.visit_id FROM visits a CROSS JOIN visits b CROSS JOIN visits c"
    result = run_query("group_counts", sql, "duplicates")
    assert result["status"] == "error" and result["error"] == "result_limit_exceeded", result
    assert result["rows"] == []  # Never compare silently truncated results.
    text = "a" * 1000
    sql = "SELECT '" + text + "'||'" + text + "'||'" + text + "'||'" + text + "'||'" + text + "'"
    result = run_query("filter_paid", sql)
    assert result["error"] == "result_limit_exceeded"
    result = run_query("group_counts", f"SELECT '{text}' FROM visits a CROSS JOIN visits b", "duplicates")
    assert result["error"] == "result_limit_exceeded"


def test_large_valid_query_times_out_and_is_reaped(monkeypatch):
    processes = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(workbench.subprocess, "Popen", capture)
    sql = "SELECT COUNT(*) FROM visits a CROSS JOIN visits b CROSS JOIN visits c CROSS JOIN visits d CROSS JOIN visits e"
    assert inspect_sql("group_counts", sql)["valid"]
    started = monotonic()
    result = run_query("group_counts", sql, "duplicates")
    assert result["status"] == "timeout", result
    assert monotonic() - started < 4
    for process in processes:
        assert process.poll() is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)


def test_wall_deadline_memory_monitor_and_cancellation_reap_workers(monkeypatch):
    processes = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(workbench.subprocess, "Popen", capture)
    with monkeypatch.context() as patch:
        patch.setattr(workbench, "WALL_SECONDS", 0)
        assert run_query("filter_paid", "SELECT 1")["status"] == "timeout"
    with monkeypatch.context() as patch:
        patch.setattr(workbench, "_resident_bytes", lambda pid: query_worker.MEMORY_BYTES + 1)
        result = run_query("filter_paid", "SELECT 1")
        assert result["error"] == "memory_limit_exceeded", result
    with monkeypatch.context() as patch:
        def cancel(*args, **kwargs):
            raise KeyboardInterrupt
        patch.setattr(original, "communicate", cancel)
        with pytest.raises(KeyboardInterrupt):
            run_query("filter_paid", "SELECT 1")
    assert len(processes) == 3
    for process in processes:
        assert process.poll() is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)


def test_pre_cancelled_work_never_launches_a_worker(monkeypatch):
    cancel_event = Event()
    cancel_event.set()

    def unexpected_spawn(*args, **kwargs):
        pytest.fail("cancelled work spawned a worker")

    monkeypatch.setattr(workbench.subprocess, "Popen", unexpected_spawn)
    assert workbench._invoke({}, cancel_event=cancel_event)["error"] == "query_cancelled"
    result = run_query("group_counts", "SELECT 1", cancel_event=cancel_event)
    assert result["status"] == "timeout" and result["error"] == "query_cancelled"
    assert result["rows"] == [] and len(result["fingerprint"]) == 64
    report = evaluate("group_counts", "SELECT 1", cancel_event=cancel_event)
    assert report["status"] == "timeout" and report["message"] == "query_cancelled"
    assert report["checked"] == 0 and report["total"] == 4
    assert not report["passed"] and report["query_result"] is report["counterexample"] is None


@pytest.mark.parametrize("checking", [False, True])
def test_cancel_long_bounded_read_reaps_worker_and_stops_scenarios(monkeypatch, checking):
    sql = "SELECT COUNT(*) FROM visits a CROSS JOIN visits b CROSS JOIN visits c CROSS JOIN visits d CROSS JOIN visits e"
    assert inspect_sql("group_counts", sql)["valid"]
    cancel_event = Event()
    monitoring = Event()
    processes = []
    datasets = []
    original_popen = subprocess.Popen
    original_dataset = workbench._dataset

    def capture(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        communicate = process.communicate

        def monitored_read(*args, **kwargs):
            try:
                return communicate(*args, **kwargs)
            except subprocess.TimeoutExpired:
                # Hand off at a real monitor tick, not a sleep or mocked worker.
                monitoring.set()
                assert cancel_event.wait(2)
                raise

        monkeypatch.setattr(process, "communicate", monitored_read)
        return process

    def dataset(task_id, scenario, seed):
        datasets.append(scenario)
        return original_dataset(task_id, scenario, seed)

    monkeypatch.setattr(workbench.subprocess, "Popen", capture)
    monkeypatch.setattr(workbench, "_dataset", dataset)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = (executor.submit(evaluate, "group_counts", sql,
                                  ["duplicates", "sample", "boundary", "empty"], cancel_event=cancel_event)
                  if checking else executor.submit(run_query, "group_counts", sql, "duplicates",
                                                   cancel_event=cancel_event))
        try:
            assert monitoring.wait(2), "worker finished before the cancellation monitor"
            started = monotonic()
            cancel_event.set()
            result = future.result(timeout=2)
            assert monotonic() - started < 1
        finally:
            cancel_event.set()
    assert result["status"] == "timeout"
    if checking:
        assert result["message"] == "query_cancelled"
        assert result["checked"] == 0 and result["total"] == 4
        assert not result["passed"] and result["counterexample"] is None
        result = result["query_result"]
    assert result["error"] == "query_cancelled" and result["rows"] == []
    assert datasets == ["duplicates"] and len(processes) == 1
    process = processes[0]
    assert process.poll() is not None
    assert process.stdin.closed and process.stdout.closed
    with pytest.raises(ChildProcessError):
        os.waitpid(process.pid, os.WNOHANG)


@pytest.mark.parametrize("stage", ["student", "reference", "scenario"])
def test_evaluation_cancellation_between_workers_stops_next_launch(monkeypatch, stage):
    cancel_event = Event()
    calls = []
    original_run = workbench.run_query
    original_compare = workbench._same_result

    def run(*args, **kwargs):
        assert kwargs["cancel_event"] is cancel_event
        calls.append(args[2])
        result = original_run(*args, **kwargs)
        if len(calls) == {"student": 1, "reference": 2, "scenario": 0}[stage]:
            cancel_event.set()
        return result

    def compare(*args):
        result = original_compare(*args)
        if stage == "scenario":
            cancel_event.set()
        return result

    monkeypatch.setattr(workbench, "run_query", run)
    monkeypatch.setattr(workbench, "_same_result", compare)
    report = evaluate("group_counts", _get_task("group_counts").reference_sql, cancel_event=cancel_event)
    assert report["status"] == "timeout" and report["message"] == "query_cancelled"
    assert not report["passed"] and report["counterexample"] is None
    assert report["checked"] == (1 if stage == "scenario" else 0) and report["total"] == 4
    assert calls == ["sample"] * (1 if stage == "student" else 2)


def test_worker_receives_no_environment_or_application_import_path(monkeypatch):
    original = subprocess.Popen
    observed = []
    monkeypatch.setenv("QUERYSTEP_TEST_API_KEY", "synthetic-test-marker-not-a-secret")

    def capture(*args, **kwargs):
        observed.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(workbench.subprocess, "Popen", capture)
    assert run_query("sum_totals", "SELECT SUM(amount) FROM line_items")["status"] == "ok"
    args, kwargs = observed[0]
    assert kwargs["env"] == {} and kwargs["close_fds"] and kwargs["start_new_session"]
    assert kwargs["cwd"] == "/" and kwargs["stderr"] == subprocess.DEVNULL
    assert args[0][1:4] == ["-I", "-S", "-B"]
    assert "synthetic-test-marker" not in repr(args)


def test_authorizer_and_function_whitelist_even_if_ast_gate_is_bypassed():
    # Deliberately bypass ONLY validation in an isolated test worker. Do not
    # change the test runner's process-global SQLite hard_heap_limit.
    task = _get_task("filter_paid")
    dataset = dataset_view(task.id)
    bootstrap = (f"import sys; sys.path.insert(0, {str(workbench._WORKER.parent.parent)!r}); "
                 "from sql_lab import query_worker; "
                 "query_worker._validate_sql = lambda sql, tables: None; query_worker.main()")
    for sql in ("DELETE FROM orders", "ATTACH ':memory:' AS other", "PRAGMA user_version",
                "SELECT name FROM sqlite_master", "SELECT sqlite_version()", "SELECT randomblob(1)"):
        payload = {"mode": "query", "sql": sql, "tables": dataset["tables"],
                   "allowed_tables": [table.name for table in task.tables],
                   "ddl": [table.ddl for table in task.tables]}
        child = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", bootstrap, "/"],
                               input=json.dumps(payload).encode(), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env={}, close_fds=True, timeout=4)
        assert child.returncode == 0, child.stderr
        result = json.loads(child.stdout)
        assert result["status"] == "rejected", (sql, result)


@pytest.mark.parametrize("sql,code", [
    ("SELECT amuont FROM orders", "unknown_column"),
    ("SELECT order_id FROM orders a JOIN orders b ON a.order_id=b.order_id", "ambiguous_column"),
    ("SELECT * FROM orders WHERE SUM(amount)>0", "invalid_aggregate"),
    ("SELECT SUM(COUNT(*)) FROM orders", "invalid_aggregate"),
    ("SELECT order_id FROM orders HAVING order_id>0", "invalid_aggregate"),
    ("SELECT FROM orders", "syntax_error"),
    ("SELECT order_id FROM orders OFFSET 1", "syntax_error"),
])
def test_sqlite_diagnostics_are_actionable_bounded_codes(sql, code):
    result = run_query("filter_paid", sql)
    assert result["status"] == "error" and result["error"] == code
    assert result["columns"] == result["rows"] == [] and result["row_count"] == 0
    report = evaluate("filter_paid", sql)
    assert report["status"] == "error" and report["message"] == code
    assert report["checked"] == 0 and report["total"] == 4
    assert report["query_result"]["error"] == code and report["counterexample"] is None


@pytest.mark.parametrize("sql,code", [
    ("SELECT * FROM orders WHERE", "invalid_sql"),
    ("SELECT * FROM orders WHERE (", "invalid_sql"),
    ("SELECT * FROM missing", "table_not_allowed"),
])
def test_parser_rejections_remain_safe(sql, code):
    assert inspect_sql("filter_paid", sql) == {"valid": False, "error": code}
    result = run_query("filter_paid", sql)
    assert result["status"] == "rejected" and result["error"] == code


@pytest.mark.parametrize("sql,code", [
    ('SELECT "private-marker" FROM absent_table', "unknown_table"),
    ('SELECT private_column FROM (SELECT 1)', "unknown_column"),
    ('SELECT (', "syntax_error"),
    ('SELECT 1 +', "syntax_error"),
    ('SELECT abs(1, 2)', "query_error"),
])
def test_sqlite_error_allowlist_uses_real_error_types_without_echoing_details(sql, code):
    # No worker/global heap limits here: just classify real in-memory exceptions.
    with sqlite3.connect(":memory:") as db:
        with pytest.raises(sqlite3.Error) as caught:
            db.execute(sql)
    assert query_worker._sqlite_error_code(caught.value) == code
    for error in (sqlite3.OperationalError("no such table: /private/secret"),
                  sqlite3.DatabaseError("no such column: private_column")):
        assert query_worker._sqlite_error_code(error) == "query_error"
    unknown = sqlite3.OperationalError("unrecognized /private/secret SELECT 1")
    unknown.sqlite_errorcode = sqlite3.SQLITE_ERROR
    assert query_worker._sqlite_error_code(unknown) == "query_error"


@pytest.mark.parametrize("result", [{}, {"valid": False}, {"valid": False, "error": None},
                                    {"valid": True, "error": "worker_error"}])
def test_invalid_inspection_always_has_an_error(monkeypatch, result):
    monkeypatch.setattr(workbench, "_invoke", lambda payload: result)
    assert inspect_sql("filter_paid", "SELECT 1") == {"valid": False, "error": "worker_error"}


def test_unknown_inputs_errors_fingerprints_and_scenario_bounds():
    assert inspect_sql("missing", "SELECT 1") == {"valid": False, "error": "unknown_task"}
    assert run_query("missing", "SELECT 1")["status"] == "rejected"
    assert evaluate("missing", "SELECT 1")["status"] == "rejected"
    for seed in (-1, True, 2**31, "0", None):
        assert run_query("filter_paid", "SELECT 1", seed=seed)["error"] == "invalid_seed"
    for scenarios in ([], "sample", ["bogus"], ["sample", "sample"], [None]):
        assert evaluate("filter_paid", "SELECT 1", scenarios)["status"] == "rejected"
    with pytest.raises(ValueError, match="^invalid_scenario$"):
        dataset_view("filter_paid", "bogus")
    for sql in (None, [], "", "\ud800"):
        assert not inspect_sql("filter_paid", sql)["valid"]
    error = run_query("filter_paid", "SELECT unknown_column FROM orders")
    assert error["status"] == "error" and error["error"] == "unknown_column"
    first = run_query("filter_paid", "SELECT * FROM orders")
    second = run_query("filter_paid", "SELECT * FROM orders")
    assert first["fingerprint"] == second["fingerprint"] and len(first["fingerprint"]) == 64
    assert first["elapsed_ms"] >= 0 and first["error"] is None
    assert set(first) == {"status", "columns", "rows", "row_count", "error", "elapsed_ms", "fingerprint", "scenario", "seed"}
    assert run_query("filter_paid", "SELECT * FROM orders", seed=1)["fingerprint"] != first["fingerprint"]


def test_linux_worker_rss_reads_proc_statm_not_fork_inherited_ru_maxrss(monkeypatch):
    import builtins
    import io

    class HugeParentRusage:
        ru_maxrss = 1024 * 1024  # 1 GiB (KiB on Linux) inherited across fork()+execve()

    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/proc/self/statm":
            return io.StringIO("25000 6400 3000 10 0 4000 0\n")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(query_worker.sys, "platform", "linux")
    monkeypatch.setattr(query_worker.resource, "getrusage", lambda _who: HugeParentRusage())
    monkeypatch.setattr(query_worker.os, "sysconf", lambda name: 4096 if name == "SC_PAGE_SIZE" else 0)
    monkeypatch.setattr(builtins, "open", fake_open)
    assert query_worker._current_rss_bytes() == 6400 * 4096
    assert query_worker._current_rss_bytes() < query_worker.MEMORY_BYTES
