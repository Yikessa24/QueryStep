"""MCP client with scoped tool access and validation at the process boundary."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from hashlib import sha256
import sys

import anyio
from mcp import ClientSession, McpError, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolRequest, CancelledNotification, CancelledNotificationParams, ClientNotification
from pydantic import ValidationError

from course_content.sql_fixtures import FIXTURES
from sql_lab.contracts import (COACH_SCOPE, TRANSFER_SCOPE, WORKBENCH_SCOPE, CheckStudentSQLRequest,
                               CoachExperimentRequest, CompareRequest, FixtureRequest, InspectStudentSQLRequest,
                               QueryRequest, ROLE_TOOLS, RunStudentSQLRequest, SQLTaskRequest, contracts_for)
from sql_lab.executor import LabError


class _CancellableClientSession(ClientSession):
    """Bridge local tool-call cancellation to MCP without closing a shared session."""

    async def send_request(self, request, result_type, request_read_timeout_seconds=None,
                           metadata=None, progress_callback=None):
        # MCP 1.30.0 allocates/increments this ID before its first await in
        # BaseSession.send_request. Capture it here, not after call_tool yields:
        # other requests (including schema discovery) can then advance the counter.
        request_id = self._request_id
        try:
            return await super().send_request(request, result_type, request_read_timeout_seconds,
                                              metadata, progress_callback)
        except (asyncio.CancelledError, McpError) as error:
            # The SDK wraps its own read timeout in McpError(408), but only
            # discards the local response waiter. Do not cancel initialization
            # or treat a server-returned error as a local timeout.
            timed_out = (isinstance(error, McpError) and error.error.code == 408
                         and isinstance(error.__context__, TimeoutError))
            if isinstance(request.root, CallToolRequest) and (isinstance(error, asyncio.CancelledError) or timed_out):
                try:
                    await self._cancel_request(request_id)
                except asyncio.CancelledError:
                    if not isinstance(error, asyncio.CancelledError):
                        raise
            raise

    async def _cancel_request(self, request_id):
        async def notify():
            try:
                async with asyncio.timeout(1):
                    await self.send_notification(ClientNotification(CancelledNotification(
                        params=CancelledNotificationParams(requestId=request_id))))
            except Exception:
                # Closed/broken/backpressured transports must not replace the
                # caller's cancellation or timeout, or hold it indefinitely.
                pass

        # Shield against both AnyIO scope cancellation and repeated Task.cancel().
        # Await bounded cleanup rather than leaving a notification task behind.
        cancelled = None
        with anyio.CancelScope(shield=True):
            notification = asyncio.create_task(notify())
            while not notification.done():
                try:
                    await asyncio.shield(notification)
                except asyncio.CancelledError as error:
                    cancelled = error
            notification.result()
        if cancelled is not None:
            raise cancelled


class LabClient:
    def __init__(self, session: ClientSession, fixture_id: str):
        self.session = session
        self.fixture_id = fixture_id
        self.contracts = contracts_for(fixture_id)

    async def call(self, role: str, name: str, arguments: dict, *, timeout: float = 2) -> dict:
        if (name not in ROLE_TOOLS.get(role, ()) or name not in self.contracts
                or (self.fixture_id == WORKBENCH_SCOPE) != (role == "workbench")):
            raise LabError("tool_not_allowed")
        request_type, result_type, _ = self.contracts[name]
        try:
            request = request_type.model_validate(arguments)
        except ValidationError as error:
            raise LabError("invalid_parameters") from error
        if isinstance(request, FixtureRequest) and request.fixture_id != self.fixture_id:
            raise LabError("fixture_not_allowed")
        try:
            result = await self.session.call_tool(name, request.model_dump(),
                                                  read_timeout_seconds=timedelta(seconds=timeout))
        except (McpError, OSError, TimeoutError) as error:
            raise LabError("mcp_request_failed") from error
        except Exception:
            if self.fixture_id != WORKBENCH_SCOPE:
                raise
            raise LabError("mcp_request_failed") from None
        if result.isError:
            raise LabError("mcp_tool_failed")
        try:
            validated = result_type.model_validate(result.structuredContent)
        except ValidationError as error:
            raise LabError("invalid_tool_result") from error
        if isinstance(request, FixtureRequest) and validated.fixture_id != self.fixture_id:
            raise LabError("invalid_tool_result")
        if isinstance(request, QueryRequest) and (validated.query_id != request.query_id
                                                 or validated.parameters != request.parameters):
            raise LabError("invalid_tool_result")
        if isinstance(request, CompareRequest) and (validated.fixture_id != self.fixture_id
                or validated.before_id != request.before_id or validated.after_id != request.after_id):
            raise LabError("invalid_tool_result")
        if isinstance(request, CoachExperimentRequest) and any(
            getattr(validated, key) != value for key, value in request.model_dump().items()
        ):
            raise LabError("invalid_tool_result")
        if isinstance(request, SQLTaskRequest) and validated.task_id != request.task_id:
            raise LabError("invalid_tool_result")
        if isinstance(request, InspectStudentSQLRequest) and validated.sql_digest != sha256(request.sql.encode()).hexdigest():
            raise LabError("invalid_tool_result")
        if isinstance(request, RunStudentSQLRequest) and (validated.scenario != request.scenario
                                                        or validated.seed != request.seed):
            raise LabError("invalid_tool_result")
        if isinstance(request, CheckStudentSQLRequest) and (validated.scenarios != request.scenarios
                                                          or validated.seed != request.seed):
            raise LabError("invalid_tool_result")
        return validated.model_dump()


@asynccontextmanager
async def open_lab(fixture_id: str, *, knowledge_args=()):
    if fixture_id not in FIXTURES and fixture_id not in {TRANSFER_SCOPE, COACH_SCOPE, WORKBENCH_SCOPE}:
        raise LabError("unknown_fixture")
    parameters = StdioServerParameters(command=sys.executable,
                                       args=["-m", "sql_lab.server", "--fixture", fixture_id, *knowledge_args])
    async with stdio_client(parameters) as (read, write), _CancellableClientSession(read, write) as session:
        async with asyncio.timeout(25 if fixture_id in {COACH_SCOPE, WORKBENCH_SCOPE} else 8):
            await session.initialize()
            discovered = (await session.list_tools()).tools
        tools = {tool.name: tool for tool in discovered}
        lab = LabClient(session, fixture_id)
        for name, (request, result, _) in lab.contracts.items():
            tool = tools.get(name)
            if (tool is None or tool.inputSchema != request.model_json_schema()
                    or tool.outputSchema != result.model_json_schema()):
                raise LabError("mcp_tool_contract_mismatch")
        yield lab
