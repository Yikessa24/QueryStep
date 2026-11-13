"""MCP client with scoped tool access and validation at the process boundary."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import sys

from mcp import ClientSession, McpError, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from course_content.sql_fixtures import FIXTURES
from sql_lab.contracts import CompareRequest, FixtureRequest, QueryRequest, ROLE_TOOLS, TOOL_CONTRACTS
from sql_lab.executor import LabError


class LabClient:
    def __init__(self, session: ClientSession, fixture_id: str):
        self.session = session
        self.fixture_id = fixture_id

    async def call(self, role: str, name: str, arguments: dict, *, timeout: float = 2) -> dict:
        if name not in ROLE_TOOLS.get(role, ()):
            raise LabError("tool_not_allowed")
        request_type, result_type, _ = TOOL_CONTRACTS[name]
        try:
            request = request_type.model_validate(arguments)
        except ValidationError as error:
            raise LabError("invalid_parameters") from error
        if isinstance(request, FixtureRequest) and request.fixture_id != self.fixture_id:
            raise LabError("fixture_not_allowed")
        try:
            result = await self.session.call_tool(name, request.model_dump(),
                                                  read_timeout_seconds=timedelta(seconds=timeout))
        except (McpError, OSError) as error:
            raise LabError("mcp_request_failed") from error
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
        return validated.model_dump()


@asynccontextmanager
async def open_lab(fixture_id: str):
    if fixture_id not in FIXTURES:
        raise LabError("unknown_fixture")
    parameters = StdioServerParameters(command=sys.executable,
                                       args=["-m", "sql_lab.server", "--fixture", fixture_id])
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        async with asyncio.timeout(8):
            await session.initialize()
            discovered = (await session.list_tools()).tools
        tools = {tool.name: tool for tool in discovered}
        for name, (request, result, _) in TOOL_CONTRACTS.items():
            tool = tools.get(name)
            if (tool is None or tool.inputSchema != request.model_json_schema()
                    or tool.outputSchema != result.model_json_schema()):
                raise LabError("mcp_tool_contract_mismatch")
        yield LabClient(session, fixture_id)
