import importlib.util
import unittest
from unittest.mock import AsyncMock, patch

from course_content.sql_fixtures import FIXTURES, GROUPING_FIXTURE, GROUPING_VARIANT, JOIN_FIXTURE, JOIN_VARIANT
from sql_lab.executor import LabError, execute


class SQLExecutionTest(unittest.TestCase):
    def test_read_only_authorizer_blocks_unapproved_operations(self):
        for sql in ("DELETE FROM parcels", "ATTACH ':memory:' AS other", "SELECT name FROM sqlite_master"):
            with self.subTest(sql=sql), patch.dict(FIXTURES[GROUPING_FIXTURE].queries, {"group_counts": sql}):
                with self.assertRaisesRegex(LabError, "query_rejected"):
                    execute(GROUPING_FIXTURE, "group_counts", {})

    def test_execution_budget_and_row_cap_reject_results(self):
        with self.assertRaisesRegex(LabError, "query_timeout"):
            execute(GROUPING_FIXTURE, "group_counts", {}, timeout=0)
        with patch("sql_lab.executor.ROW_LIMIT", 1):
            with self.assertRaisesRegex(LabError, "row_limit_exceeded"):
                execute(GROUPING_FIXTURE, "group_counts", {})


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install the diagnostics extra for stdio tests.")
class MCPTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_tool_discovery_execution_and_differences(self):
        from sql_lab.check import check

        for fixture, expected, removed in ((GROUPING_FIXTURE, 3, ["D"]),
                                           (GROUPING_VARIANT, 1, ["B", "C", "D"])):
            with self.subTest(fixture=fixture):
                report = await check(fixture)
                self.assertEqual(len(report["group_counts"]), 4)
                self.assertEqual(len(report["having_gt"]), expected)
                self.assertEqual(len(report["having_gte"]), 4)
                self.assertEqual(report["comparison"]["removed_keys"], removed)
                self.assertIn("aggregate-having", report["course_sources"])

    async def test_left_join_filter_and_no_difference_variant(self):
        from sql_lab.client import open_lab

        for fixture_id, removed in ((JOIN_FIXTURE, ["2", "3"]), (JOIN_VARIANT, [])):
            async with open_lab(fixture_id) as lab:
                observations = [await lab.call("experiment", "run_example_query", {
                    "fixture_id": fixture_id, "query_id": query,
                }) for query in ("join_on", "join_where")]
                difference = await lab.call("experiment", "compare_example_results", {
                    "before_id": observations[0]["observation_id"], "after_id": observations[1]["observation_id"],
                })
                self.assertEqual(difference["removed_keys"], removed)
                self.assertEqual(observations[0]["rows"][1][1], None if removed else "paid")

    async def test_client_rejects_role_and_parameters_before_calling_server(self):
        from sql_lab.client import LabClient

        session = AsyncMock()
        client = LabClient(session, GROUPING_FIXTURE)
        request = {"fixture_id": GROUPING_FIXTURE, "query_id": "having_gt",
                   "parameters": {"min_count": 1}}
        cases = [
            ("course", request, "tool_not_allowed"),
            ("experiment", {**request, "query_id": "unreviewed"}, "invalid_parameters"),
            ("experiment", {**request, "parameters": {"min_count": True}}, "invalid_parameters"),
            ("experiment", {**request, "parameters": {"min_count": 51}}, "invalid_parameters"),
            ("experiment", {**request, "fixture_id": GROUPING_VARIANT}, "fixture_not_allowed"),
        ]
        for role, args, error in cases:
            with self.subTest(args=args), self.assertRaisesRegex(LabError, error):
                await client.call(role, "run_example_query", args)
        session.call_tool.assert_not_awaited()

    async def test_independent_sdk_client_cannot_reuse_another_runs_observation(self):
        import sys

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        from sql_lab.client import open_lab

        async with open_lab(GROUPING_FIXTURE) as first:
            observed = await first.call("experiment", "run_example_query", {
                "fixture_id": GROUPING_FIXTURE, "query_id": "group_counts",
            })
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "sql_lab.server"])
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            self.assertEqual(len((await session.list_tools()).tools), 4)
            valid = await session.call_tool("describe_fixture", {"fixture_id": GROUPING_FIXTURE})
            self.assertEqual(valid.structuredContent["dialect"], "sqlite")
            disallowed = await session.call_tool("describe_fixture", {"fixture_id": GROUPING_VARIANT})
            self.assertTrue(disallowed.isError)
            invalid = await session.call_tool("run_example_query", {
                "fixture_id": GROUPING_FIXTURE, "query_id": "having_gt", "parameters": {"min_count": 51},
            })
            self.assertTrue(invalid.isError)
            observation_id = observed["observation_id"]
            result = await session.call_tool("compare_example_results", {
                "before_id": observation_id, "after_id": observation_id,
            })
            self.assertTrue(result.isError)
            self.assertIn("unknown_observation", result.content[0].text)
