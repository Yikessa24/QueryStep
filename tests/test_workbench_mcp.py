import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import importlib.util
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError

from course_content.sql_fixtures import GROUPING_FIXTURE
from sql_lab.contracts import (
    CHECK_STUDENT_SQL_TOOL, COACH_SCOPE, DESCRIBE_SQL_TASK_TOOL, INSPECT_STUDENT_SQL_TOOL,
    KNOWLEDGE_TOOL, ROLE_TOOLS, RUN_STUDENT_SQL_TOOL, TRANSFER_SCOPE, WORKBENCH_CONTRACTS,
    WORKBENCH_SCENARIOS, WORKBENCH_SCOPE, CheckStudentSQLRequest, CheckStudentSQLResult,
    InspectStudentSQLRequest, InspectStudentSQLResult, KnowledgeRequest, RunStudentSQLRequest,
    RunStudentSQLResult, SQLTaskDescription, SQLTaskRequest, StudentQueryResult, contracts_for,
)
from sql_lab.executor import LabError


MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
TASKS_AVAILABLE = importlib.util.find_spec("course_content.sql_tasks") is not None
ENGINE_AVAILABLE = importlib.util.find_spec("sql_lab.workbench") is not None and TASKS_AVAILABLE
TASK = "group_counts"
SQL = "SELECT channel, COUNT(*) AS visit_count FROM visits GROUP BY channel"
TABLE = {"name": "customers", "columns": ["city"], "types": ["TEXT"], "rows": [["A"]]}


def query_result(scenario="sample", seed=0):
    return {"status": "ok", "columns": ["city", "n"], "rows": [["A", 1]], "row_count": 1,
            "error": None, "elapsed_ms": 0.1, "fingerprint": "a" * 64, "scenario": scenario, "seed": seed}


def run_result(sql=SQL, scenario="sample", seed=0):
    return {**query_result(scenario, seed), "task_id": TASK, "sql_digest": sha256(sql.encode()).hexdigest()}


def check_result(scenarios=None, seed=0):
    scenarios = list(WORKBENCH_SCENARIOS) if scenarios is None else scenarios
    return {"task_id": TASK, "sql_digest": sha256(SQL.encode()).hexdigest(), "scenarios": scenarios,
            "seed": seed, "status": "passed", "passed": True, "checked": len(scenarios),
            "total": len(scenarios), "counterexample": None, "message": "passed",
            "query_result": query_result(scenarios[0], seed)}


class WorkbenchContractTest(unittest.TestCase):
    def test_scope_schema_and_knowledge_contract_are_explicit(self):
        expected = {DESCRIBE_SQL_TASK_TOOL, INSPECT_STUDENT_SQL_TOOL, RUN_STUDENT_SQL_TOOL,
                    CHECK_STUDENT_SQL_TOOL, KNOWLEDGE_TOOL}
        self.assertEqual(set(contracts_for(WORKBENCH_SCOPE)), expected)
        self.assertEqual(ROLE_TOOLS["workbench"], expected)
        self.assertIs(WORKBENCH_CONTRACTS[KNOWLEDGE_TOOL], contracts_for(COACH_SCOPE)[KNOWLEDGE_TOOL])
        for scope in (GROUPING_FIXTURE, TRANSFER_SCOPE, COACH_SCOPE):
            self.assertFalse((expected - {KNOWLEDGE_TOOL}) & set(contracts_for(scope)))
        for request, result, _ in WORKBENCH_CONTRACTS.values():
            for model in (request, result):
                self.assertIs(model.model_json_schema()["additionalProperties"], False)
        ids = SQLTaskRequest.model_json_schema()["properties"]["task_id"]["enum"]
        self.assertEqual(len(ids), 10)
        self.assertIn("left_join_filter", ids)
        self.assertNotIn("reference_sql", SQLTaskDescription.model_json_schema()["properties"])
        self.assertEqual(KnowledgeRequest.model_fields["topic"].annotation.__args__,
                         ("select", "where", "conditions", "distinct", "aggregate", "set_ops", "join", "subquery", "null"))

    @unittest.skipUnless(TASKS_AVAILABLE, "Task catalog not ready.")
    def test_real_public_task_catalog_matches_contract(self):
        from course_content.sql_tasks import public_tasks, task_view

        public = public_tasks()
        self.assertEqual({task["id"] for task in public},
                         set(SQLTaskRequest.model_json_schema()["properties"]["task_id"]["enum"]))
        for task in public:
            with self.subTest(task_id=task["id"]):
                self.assertNotIn("reference_sql", task)
                description = SQLTaskDescription.model_validate({**task_view(task["id"]), "task_id": task["id"]})
                self.assertEqual(description.title, task["title"])

    def test_requests_are_bounded_strict_and_context_free(self):
        base = {"task_id": TASK, "sql": SQL}
        invalid = [
            {"task_id": "unknown"}, {"sql": ""}, {"sql": "x" * 6001}, {"sql": 42},
            {"seed": True}, {"seed": -1}, {"seed": 1_000_001}, {"seed": "1"},
            {"scenario": "private"}, {"session": "s"}, {"key": "secret"},
            {"learner": {"id": 1}}, {"reference_sql": SQL},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                RunStudentSQLRequest.model_validate({**base, **changes})
        self.assertEqual(RunStudentSQLRequest(**base).seed, 0)
        self.assertEqual(RunStudentSQLRequest(**base, seed=1_000_000).seed, 1_000_000)
        self.assertEqual(len(InspectStudentSQLRequest(task_id=TASK, sql="x" * 6000).sql), 6000)
        self.assertEqual(CheckStudentSQLRequest(**base).scenarios, list(WORKBENCH_SCENARIOS))
        for scenarios in ([], ["sample"] * 5, ["sample", "sample"], ["private"], "sample", None):
            with self.subTest(scenarios=scenarios), self.assertRaises(ValidationError):
                CheckStudentSQLRequest(**base, scenarios=scenarios)
        self.assertEqual(CheckStudentSQLRequest(**base, scenarios=["boundary"]).scenarios, ["boundary"])
        with self.assertRaises(ValidationError):
            CheckStudentSQLRequest(**base, scenario="sample")

    def test_results_validate_shapes_status_and_evaluation_context(self):
        StudentQueryResult.model_validate(query_result())
        RunStudentSQLResult.model_validate(run_result())
        CheckStudentSQLResult.model_validate(check_result())
        malformed = [
            {"row_count": 2}, {"rows": [["A"]]}, {"rows": [["A", True]]},
            {"rows": [["A", float("nan")]]}, {"elapsed_ms": float("inf")},
            {"status": "ok", "error": "failed"}, {"status": "error", "error": None},
            {"sql_digest": "bad"}, {"learner": "private"},
        ]
        for changes in malformed:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                RunStudentSQLResult.model_validate({**run_result(), **changes})
        for changes in ({"checked": 3}, {"total": 3}, {"passed": False},
                        {"query_result": query_result(seed=1)}, {"scenarios": ["boundary"]}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                CheckStudentSQLResult.model_validate({**check_result(), **changes})
        mismatch = {**check_result(["boundary"], 2), "status": "mismatch", "passed": False,
                    "counterexample": {"scenario": "boundary", "seed": 2, "tables": [TABLE],
                                       "actual": query_result("boundary", 2),
                                       "expected": query_result("boundary", 2)}}
        CheckStudentSQLResult.model_validate(mismatch)
        for path in ("actual", "expected"):
            bad = deepcopy(mismatch)
            bad["counterexample"][path]["seed"] = 3
            with self.assertRaises(ValidationError):
                CheckStudentSQLResult.model_validate(bad)
        with self.assertRaises(ValidationError):
            InspectStudentSQLResult(task_id=TASK, sql_digest="a" * 64, valid=True, error="no")

    def test_public_description_rejects_reference_sql_and_wrong_identity(self):
        description = {"task_id": TASK, "id": TASK, "title": "Count", "prompt": "Count by city",
                       "topic": "aggregate", "concepts": ["group_by"], "starter_sql": "SELECT",
                       "dialect": "sqlite", "version": 1, "tables": [TABLE], "ordered": False}
        SQLTaskDescription.model_validate(description)
        for changes in ({"reference_sql": SQL}, {"id": "filter_paid"},
                        {"tables": [{**TABLE, "types": []}]},
                        {"tables": [{**TABLE, "rows": [["A", 1]]}]}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                SQLTaskDescription.model_validate({**description, **changes})


@unittest.skipUnless(MCP_AVAILABLE, "Install diagnostics extras for MCP client/server tests.")
class WorkbenchBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_roles_scopes_and_invalid_parameters_never_reach_transport(self):
        from sql_lab.client import LabClient

        session = AsyncMock()
        lab = LabClient(session, WORKBENCH_SCOPE)
        for role in ("coach", "course", "experiment", "transfer", "unknown"):
            with self.subTest(role=role), self.assertRaisesRegex(LabError, "tool_not_allowed"):
                await lab.call(role, RUN_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL})
        with self.assertRaisesRegex(LabError, "tool_not_allowed"):
            await lab.call("coach", KNOWLEDGE_TOOL, {"query": "COUNT", "topic": "aggregate"})
        for scope in (GROUPING_FIXTURE, TRANSFER_SCOPE, COACH_SCOPE):
            with self.subTest(scope=scope), self.assertRaisesRegex(LabError, "tool_not_allowed"):
                await LabClient(session, scope).call("workbench", KNOWLEDGE_TOOL,
                                                    {"query": "COUNT", "topic": "aggregate"})
        with self.assertRaisesRegex(LabError, "tool_not_allowed"):
            await lab.call("workbench", "run_example_query", {})
        with self.assertRaisesRegex(LabError, "invalid_parameters"):
            await lab.call("workbench", RUN_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL, "seed": True})
        session.call_tool.assert_not_awaited()

    async def test_client_rejects_replayed_identity_sql_and_scenarios(self):
        from sql_lab.client import LabClient

        session = AsyncMock()
        lab = LabClient(session, WORKBENCH_SCOPE)
        for changes in ({"task_id": "sum_totals"}, {"sql_digest": "b" * 64}, {"scenario": "boundary"},
                        {"seed": 1}, {"row_count": 2}, {"reference_sql": SQL}):
            session.call_tool.return_value = SimpleNamespace(isError=False, structuredContent={**run_result(), **changes})
            with self.subTest(changes=changes), self.assertRaisesRegex(LabError, "invalid_tool_result"):
                await lab.call("workbench", RUN_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL})
        session.call_tool.return_value = SimpleNamespace(isError=False, structuredContent=check_result(["empty"], 5))
        with self.assertRaisesRegex(LabError, "invalid_tool_result"):
            await lab.call("workbench", CHECK_STUDENT_SQL_TOOL,
                           {"task_id": TASK, "sql": SQL, "scenarios": ["boundary"], "seed": 5})
        session.call_tool.return_value = SimpleNamespace(isError=False, structuredContent=run_result())
        self.assertEqual((await lab.call("workbench", RUN_STUDENT_SQL_TOOL,
                                        {"task_id": TASK, "sql": SQL}))["task_id"], TASK)
        self.assertEqual(session.call_tool.call_args.args,
                         (RUN_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL, "scenario": "sample", "seed": 0}))

    async def test_transport_and_tool_errors_have_safe_codes(self):
        from sql_lab.client import LabClient

        session = AsyncMock()
        lab = LabClient(session, WORKBENCH_SCOPE)
        for exception in (OSError("private path"), TimeoutError("private context"), RuntimeError("private transport")):
            session.call_tool.side_effect = exception
            with self.assertRaisesRegex(LabError, "^mcp_request_failed$"):
                await lab.call("workbench", RUN_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL})
        session.call_tool.side_effect = None
        session.call_tool.return_value = SimpleNamespace(isError=True, content="private details")
        with self.assertRaisesRegex(LabError, "^mcp_tool_failed$"):
            await lab.call("workbench", RUN_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL})

    async def test_offload_and_concurrent_request_identity(self):
        from sql_lab.server import _workbench_result

        loop = asyncio.get_running_loop()
        main_thread = threading.get_ident()
        started = asyncio.Event()
        release = threading.Event()
        threads = []

        def run_query(task_id, sql, scenario="sample", seed=0, *, cancel_event=None):
            self.assertIsInstance(cancel_event, threading.Event)
            self.assertFalse(cancel_event.is_set())
            threads.append(threading.get_ident())
            loop.call_soon_threadsafe(started.set)
            if not release.wait(2):
                raise RuntimeError("offload did not release the event loop")
            return query_result(scenario, seed)

        def evaluate(task_id, sql, scenarios, seed, *, cancel_event=None):
            self.assertIsInstance(cancel_event, threading.Event)
            self.assertFalse(cancel_event.is_set())
            threads.append(threading.get_ident())
            result = check_result(scenarios, seed)
            return {key: value for key, value in result.items()
                    if key not in {"task_id", "sql_digest", "scenarios", "seed"}}

        engine = ModuleType("sql_lab.workbench")
        engine.run_query = run_query
        engine.evaluate = evaluate
        engine.inspect_sql = lambda **kwargs: {"valid": True, "error": None}
        with patch.dict(sys.modules, {"sql_lab.workbench": engine}):
            first = asyncio.create_task(_workbench_result(RunStudentSQLRequest(task_id=TASK, sql=SQL)))
            try:
                await asyncio.wait_for(started.wait(), 1)
                second = await _workbench_result(CheckStudentSQLRequest(task_id="sum_totals", sql="SELECT 1",
                                                                        scenarios=["boundary"], seed=5))
                self.assertFalse(first.done())
            finally:
                release.set()
                result = await first
        self.assertTrue(all(thread != main_thread for thread in threads))
        self.assertEqual(result["task_id"], TASK)
        self.assertEqual(result["sql_digest"], sha256(SQL.encode()).hexdigest())
        self.assertEqual((second["task_id"], second["scenarios"], second["seed"]),
                         ("sum_totals", ["boundary"], 5))
        self.assertEqual(second["sql_digest"], sha256(b"SELECT 1").hexdigest())

    async def test_server_cancellation_and_timeout_signal_threads_and_propagate(self):
        from mcp.types import CallToolRequest, CallToolRequestParams
        from sql_lab.server import create_server

        loop = asyncio.get_running_loop()
        seen_events = []
        for tool in (RUN_STUDENT_SQL_TOOL, CHECK_STUDENT_SQL_TOOL):
            for timeout in (False, True):
                with self.subTest(tool=tool, timeout=timeout):
                    started = asyncio.Event()
                    stopped = asyncio.Event()

                    def blocking_engine(*, cancel_event, **kwargs):
                        self.assertIsInstance(cancel_event, threading.Event)
                        self.assertFalse(cancel_event.is_set())
                        seen_events.append(cancel_event)
                        loop.call_soon_threadsafe(started.set)
                        try:
                            self.assertTrue(cancel_event.wait(2), "cancelled coroutine left its thread running")
                            return query_result()
                        finally:
                            loop.call_soon_threadsafe(stopped.set)

                    engine = ModuleType("sql_lab.workbench")
                    engine.run_query = engine.evaluate = blocking_engine
                    engine.inspect_sql = Mock()
                    server = create_server(WORKBENCH_SCOPE)
                    request = CallToolRequest(params=CallToolRequestParams(name=tool,
                                                                          arguments={"task_id": TASK, "sql": SQL}))
                    with patch.dict(sys.modules, {"sql_lab.workbench": engine}):
                        task = asyncio.create_task(server.request_handlers[CallToolRequest](request))
                        try:
                            await asyncio.wait_for(started.wait(), 1)
                            if timeout:
                                with self.assertRaises(TimeoutError):
                                    await asyncio.wait_for(task, 0)
                            else:
                                task.cancel()
                                with self.assertRaises(asyncio.CancelledError):
                                    await task
                            await asyncio.wait_for(stopped.wait(), 1)
                            self.assertTrue(task.cancelled())
                            self.assertTrue(seen_events[-1].is_set())
                        finally:
                            for event in seen_events:
                                event.set()
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(len({id(event) for event in seen_events}), 4)

    @unittest.skipUnless(ENGINE_AVAILABLE, "Workbench engine required.")
    async def test_real_cancelled_results_preserve_typed_contract(self):
        from mcp.types import CallToolRequest, CallToolRequestParams
        from sql_lab.server import create_server

        cancelled = threading.Event()
        cancelled.set()
        server = create_server(WORKBENCH_SCOPE)
        with patch("sql_lab.server.Event", return_value=cancelled):
            for tool in (RUN_STUDENT_SQL_TOOL, CHECK_STUDENT_SQL_TOOL):
                request = CallToolRequest(params=CallToolRequestParams(name=tool,
                                                                      arguments={"task_id": TASK, "sql": SQL}))
                result = (await server.request_handlers[CallToolRequest](request)).root
                self.assertFalse(result.isError)
                body = result.structuredContent
                WORKBENCH_CONTRACTS[tool][1].model_validate(body)
                self.assertEqual(body["status"], "timeout")
                self.assertEqual(body["sql_digest"], sha256(SQL.encode()).hexdigest())
                if tool == RUN_STUDENT_SQL_TOOL:
                    self.assertEqual(body["error"], "query_cancelled")
                    self.assertEqual(body["rows"], [])
                else:
                    self.assertEqual(body["message"], "query_cancelled")
                    self.assertEqual((body["checked"], body["total"]), (0, 4))
                    self.assertIsNone(body["query_result"])

    async def test_server_sanitizes_engine_errors_and_malformed_results(self):
        from mcp.types import CallToolRequest, CallToolRequestParams
        from sql_lab.server import create_server

        engine = ModuleType("sql_lab.workbench")
        engine.run_query = Mock()
        engine.inspect_sql = Mock()
        engine.evaluate = Mock()
        server = create_server(WORKBENCH_SCOPE)
        request = CallToolRequest(params=CallToolRequestParams(name=RUN_STUDENT_SQL_TOOL,
                                                              arguments={"task_id": TASK, "sql": SQL}))
        with patch.dict(sys.modules, {"sql_lab.workbench": engine}):
            for failure in (True, False):
                engine.run_query.side_effect = RuntimeError("/private/secret session token") if failure else None
                engine.run_query.return_value = {**query_result(), "reference_sql": "private answer"}
                result = (await server.request_handlers[CallToolRequest](request)).root
                self.assertTrue(result.isError)
                text = " ".join(part.text for part in result.content if hasattr(part, "text"))
                self.assertIn("workbench_tool_failed" if failure else "invalid_tool_result", text)
                self.assertNotIn("private", text)
                self.assertNotIn("secret", text)

    async def test_legacy_scope_does_not_import_optional_engine(self):
        from mcp.types import CallToolRequest, CallToolRequestParams
        from sql_lab.server import create_server

        with patch.dict(sys.modules, {"sql_lab.workbench": None, "course_content.sql_tasks": None}):
            server = create_server(GROUPING_FIXTURE)
            request = CallToolRequest(params=CallToolRequestParams(name="describe_fixture",
                                                                  arguments={"fixture_id": GROUPING_FIXTURE}))
            result = (await server.request_handlers[CallToolRequest](request)).root
            self.assertFalse(result.isError)


@unittest.skipUnless(MCP_AVAILABLE, "Install diagnostics extras for MCP cancellation tests.")
class WorkbenchProtocolCancellationTest(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def memory_lab(self):
        import anyio
        from mcp.shared.memory import create_client_server_memory_streams
        from sql_lab.client import open_lab
        from sql_lab.server import create_server

        messages = []
        server = create_server(WORKBENCH_SCOPE)

        @asynccontextmanager
        async def memory_stdio(parameters):
            async with create_client_server_memory_streams() as (client_streams, server_streams):
                read, write = client_streams

                class RecordingWriteStream:
                    async def send(self, message):
                        await write.send(message)
                        messages.append(message.message.root)

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *exc):
                        await write.aclose()

                async with anyio.create_task_group() as group:
                    group.start_soon(server.run, *server_streams, server.create_initialization_options())
                    try:
                        yield read, RecordingWriteStream()
                    finally:
                        group.cancel_scope.cancel()

        with patch("sql_lab.client.stdio_client", memory_stdio):
            async with open_lab(WORKBENCH_SCOPE) as lab:
                yield lab, messages

    @asynccontextmanager
    async def blocking_engine(self):
        loop = asyncio.get_running_loop()
        states = [SimpleNamespace(started=asyncio.Event(), stopped=asyncio.Event(),
                                  release=threading.Event(), cancel_event=None, completed=False)
                  for _ in range(3)]
        engine = ModuleType("sql_lab.workbench")

        def execute(*, cancel_event, seed=0, scenario="sample", scenarios=None, **kwargs):
            state = states[seed]
            state.cancel_event = cancel_event
            loop.call_soon_threadsafe(state.started.set)
            try:
                # Request 0 stops only on protocol cancellation. Request 1 must
                # survive it; request 2 exercises normal calls on the same session.
                if seed < 2:
                    gate = cancel_event if seed == 0 else state.release
                    self.assertTrue(gate.wait(5), "MCP request left its worker running")
                state.completed = not cancel_event.is_set()
                return (query_result(scenario, seed) if scenarios is None
                        else check_result(scenarios, seed))
            finally:
                loop.call_soon_threadsafe(state.stopped.set)

        engine.run_query = engine.evaluate = execute
        engine.inspect_sql = Mock()
        with patch.dict(sys.modules, {"sql_lab.workbench": engine}):
            try:
                yield states
            finally:
                for state in states:
                    state.release.set()
                    if state.cancel_event is not None:
                        state.cancel_event.set()
                for state in states:
                    if state.cancel_event is not None:
                        await asyncio.wait_for(state.stopped.wait(), 1)

    def assert_cancelled_request(self, messages, tool):
        requests = [message for message in messages if message.method == "tools/call"]
        cancelled = [message for message in messages if message.method == "notifications/cancelled"]
        target = next(message for message in requests
                      if message.params["name"] == tool and message.params["arguments"]["seed"] == 0)
        self.assertEqual([message.params["requestId"] for message in cancelled], [target.id])

    async def test_cancel_and_outer_timeout_stop_workers_without_closing_shared_session(self):
        from sql_lab.client import LabClient

        for tool in (RUN_STUDENT_SQL_TOOL, CHECK_STUDENT_SQL_TOOL):
            for mode in ("cancel", "outer_timeout", "read_timeout"):
                with self.subTest(tool=tool, mode=mode):
                    async with self.blocking_engine() as states, self.memory_lab() as (lab, messages):
                        # A second LabClient shares the connection but not the call.
                        other_lab = LabClient(lab.session, WORKBENCH_SCOPE)
                        deadline = asyncio.timeout(None)

                        async def call():
                            async with deadline:
                                return await lab.call("workbench", tool, {"task_id": TASK, "sql": SQL},
                                                      timeout=0.2 if mode == "read_timeout" else 3)

                        first = asyncio.create_task(call())
                        second = None
                        try:
                            await asyncio.wait_for(states[0].started.wait(), 1)
                            second = asyncio.create_task(other_lab.call(
                                "workbench", tool, {"task_id": TASK, "sql": SQL, "seed": 1}, timeout=3))
                            await asyncio.wait_for(states[1].started.wait(), 1)
                            if mode == "cancel":
                                first.cancel("caller cancelled this request")
                                with self.assertRaises(asyncio.CancelledError) as raised:
                                    await first
                                self.assertEqual(raised.exception.args, ("caller cancelled this request",))
                            elif mode == "outer_timeout":
                                deadline.reschedule(asyncio.get_running_loop().time())
                                with self.assertRaises(TimeoutError):
                                    await first
                                self.assertTrue(deadline.expired())
                            else:
                                from mcp import McpError

                                with self.assertRaisesRegex(LabError, "^mcp_request_failed$") as raised:
                                    await first
                                self.assertIsInstance(raised.exception.__cause__, McpError)
                                self.assertEqual(raised.exception.__cause__.error.code, 408)
                            await asyncio.wait_for(states[0].stopped.wait(), 1)
                            self.assertTrue(states[0].cancel_event.is_set())
                            self.assertFalse(states[0].completed)
                            self.assertFalse(states[1].cancel_event.is_set())
                            self.assertFalse(second.done())
                            self.assert_cancelled_request(messages, tool)
                            states[1].release.set()
                            result = await asyncio.wait_for(second, 1)
                            self.assertEqual(result["seed"], 1)
                            self.assertTrue(states[1].completed)
                            result = await lab.call("workbench", tool, {"task_id": TASK, "sql": SQL, "seed": 2})
                            self.assertEqual(result["seed"], 2)
                            self.assertTrue(states[2].completed)
                            self.assertEqual(lab.session._response_streams, {})
                            self.assertEqual(lab.session._progress_callbacks, {})
                        finally:
                            first.cancel()
                            if second is not None:
                                second.cancel()
                            await asyncio.gather(first, *([second] if second is not None else []),
                                                 return_exceptions=True)

    async def test_repeated_cancellation_during_notification_preserves_original_error(self):
        async with self.blocking_engine() as states, self.memory_lab() as (lab, messages):
            sending = asyncio.Event()
            release = asyncio.Event()
            send_notification = lab.session.send_notification

            async def delayed_notification(*args, **kwargs):
                sending.set()
                await release.wait()
                await send_notification(*args, **kwargs)

            with patch.object(lab.session, "send_notification", side_effect=delayed_notification):
                task = asyncio.create_task(lab.call("workbench", RUN_STUDENT_SQL_TOOL,
                                                   {"task_id": TASK, "sql": SQL}, timeout=3))
                try:
                    await asyncio.wait_for(states[0].started.wait(), 1)
                    task.cancel("original cancellation")
                    await asyncio.wait_for(sending.wait(), 1)
                    task.cancel("second cancellation")
                    release.set()
                    with self.assertRaises(asyncio.CancelledError) as raised:
                        await task
                    self.assertEqual(raised.exception.args, ("original cancellation",))
                    await asyncio.wait_for(states[0].stopped.wait(), 1)
                    self.assertTrue(states[0].cancel_event.is_set())
                    self.assertFalse(states[0].completed)
                    self.assert_cancelled_request(messages, RUN_STUDENT_SQL_TOOL)
                    result = await lab.call("workbench", RUN_STUDENT_SQL_TOOL,
                                            {"task_id": TASK, "sql": SQL, "seed": 2})
                    self.assertEqual(result["seed"], 2)
                finally:
                    release.set()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_close_with_inflight_request_stops_worker_and_rejects_later_calls(self):
        async with self.blocking_engine() as states:
            task = None
            try:
                async with self.memory_lab() as (lab, messages):
                    task = asyncio.create_task(lab.call("workbench", RUN_STUDENT_SQL_TOOL,
                                                       {"task_id": TASK, "sql": SQL}, timeout=0.2))
                    await asyncio.wait_for(states[0].started.wait(), 1)
                await asyncio.wait_for(states[0].stopped.wait(), 1)
                self.assertTrue(states[0].cancel_event.is_set())
                self.assertFalse(states[0].completed)
                with self.assertRaisesRegex(LabError, "^mcp_request_failed$"):
                    await asyncio.wait_for(task, 1)
                with self.assertRaisesRegex(LabError, "^mcp_request_failed$"):
                    await lab.call("workbench", RUN_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL})
                self.assertFalse(any(message.method == "notifications/cancelled" for message in messages))
            finally:
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


@unittest.skipUnless(MCP_AVAILABLE and ENGINE_AVAILABLE, "Workbench engine and diagnostics extras required.")
class WorkbenchStdioTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_discovery_public_task_run_and_targeted_check(self):
        from sql_lab.client import open_lab

        async with open_lab(WORKBENCH_SCOPE) as lab:
            tools = (await lab.session.list_tools()).tools
            self.assertEqual({tool.name for tool in tools}, set(WORKBENCH_CONTRACTS))
            for tool in tools:
                request, result, _ = WORKBENCH_CONTRACTS[tool.name]
                self.assertEqual(tool.inputSchema, request.model_json_schema())
                self.assertEqual(tool.outputSchema, result.model_json_schema())
            task = await lab.call("workbench", DESCRIBE_SQL_TASK_TOOL, {"task_id": TASK})
            self.assertEqual(task["id"], TASK)
            self.assertNotIn("reference_sql", task)
            table = task["tables"][0]["name"]
            sql = f'SELECT * FROM "{table}"'
            inspected = await lab.call("workbench", INSPECT_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": sql})
            self.assertTrue(inspected["valid"])
            observed = await lab.call("workbench", RUN_STUDENT_SQL_TOOL,
                                      {"task_id": TASK, "sql": sql, "scenario": "sample", "seed": 0})
            self.assertEqual(observed["status"], "ok")
            self.assertCountEqual(observed["rows"], task["tables"][0]["rows"])
            passed = await lab.call("workbench", CHECK_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL}, timeout=10)
            self.assertEqual(passed["status"], "passed")
            self.assertEqual((passed["checked"], passed["total"]), (4, 4))
            checked = await lab.call("workbench", CHECK_STUDENT_SQL_TOOL,
                                     {"task_id": TASK, "sql": sql, "scenarios": ["boundary"], "seed": 7})
            self.assertEqual((checked["total"], checked["scenarios"], checked["seed"]), (1, ["boundary"], 7))
            self.assertEqual(checked["status"], "mismatch")
            self.assertEqual(checked["counterexample"]["scenario"], "boundary")
            knowledge = await lab.call("workbench", KNOWLEDGE_TOOL,
                                       {"query": "GROUP BY COUNT", "topic": "aggregate", "mode": "keyword"},
                                       timeout=10)
            self.assertIn("cards", knowledge)

    async def test_real_stdio_invalid_queries_return_actionable_safe_codes(self):
        from sql_lab.client import open_lab

        cases = [
            ("SELECT chanel FROM visits", "error", "unknown_column"),
            ("SELECT visit_id FROM visits a JOIN visits b ON a.visit_id=b.visit_id", "error", "ambiguous_column"),
            ("SELECT * FROM visits WHERE COUNT(*)>0", "error", "invalid_aggregate"),
            ("SELECT FROM visits", "error", "syntax_error"),
            ("SELECT * FROM visits WHERE", "rejected", "invalid_sql"),
            ("SELECT * FROM missing", "rejected", "table_not_allowed"),
        ]
        async with open_lab(WORKBENCH_SCOPE) as lab:
            for sql, status, code in cases:
                with self.subTest(code=code):
                    arguments = {"task_id": TASK, "sql": sql}
                    observed = await lab.call("workbench", RUN_STUDENT_SQL_TOOL, arguments)
                    RunStudentSQLResult.model_validate(observed)
                    self.assertEqual((observed["status"], observed["error"]), (status, code))
                    self.assertEqual(observed["rows"], [])
                    checked = await lab.call("workbench", CHECK_STUDENT_SQL_TOOL, arguments)
                    CheckStudentSQLResult.model_validate(checked)
                    self.assertEqual((checked["status"], checked["message"]), (status, code))
                    self.assertEqual((checked["checked"], checked["total"]), (0, 4))
                    self.assertEqual(checked["query_result"]["error"], code)
                    if status == "rejected":
                        inspected = await lab.call("workbench", INSPECT_STUDENT_SQL_TOOL, arguments)
                        self.assertFalse(inspected["valid"])
                        self.assertEqual(inspected["error"], code)

    async def test_real_stdio_rejects_malicious_sql_and_cross_scope_tools(self):
        from sql_lab.client import open_lab

        async with open_lab(WORKBENCH_SCOPE) as lab:
            malicious = ("DELETE FROM orders", "ATTACH ':memory:' AS other", "PRAGMA database_list",
                         "SELECT name FROM sqlite_master", "SELECT load_extension('bad')", "SELECT 1; SELECT 2")
            for sql in malicious:
                with self.subTest(sql=sql):
                    args = {"task_id": "filter_paid", "sql": sql}
                    inspected = await lab.call("workbench", INSPECT_STUDENT_SQL_TOOL, args)
                    self.assertFalse(inspected["valid"])
                    observed = await lab.call("workbench", RUN_STUDENT_SQL_TOOL, args)
                    self.assertEqual(observed["status"], "rejected")
                    self.assertEqual(observed["rows"], [])
                    checked = await lab.call("workbench", CHECK_STUDENT_SQL_TOOL, {**args, "scenarios": ["sample"]})
                    self.assertEqual(checked["status"], "rejected")
                    self.assertFalse(checked["passed"])
            for name, arguments in (("run_example_query", {"fixture_id": GROUPING_FIXTURE, "query_id": TASK}),
                                    (RUN_STUDENT_SQL_TOOL, {"task_id": TASK, "sql": SQL, "session": "private"})):
                result = await lab.session.call_tool(name, arguments)
                self.assertTrue(result.isError)


if __name__ == "__main__":
    unittest.main()
