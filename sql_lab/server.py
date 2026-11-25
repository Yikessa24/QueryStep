"""Serve the diagnostic tools over a per-run MCP stdio connection."""

import argparse
import asyncio
from hashlib import sha256
import logging
from pathlib import Path
from threading import Event
from uuid import uuid4

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, ToolAnnotations
from pydantic import ValidationError

from course_content.diagnosis_cards import search
from course_content.sql_fixtures import FIXTURES, GROUPING_FIXTURE
from sql_lab.coach import experiment, search as coach_search
from sql_lab.contracts import (COACH_SCOPE, TRANSFER_SCOPE, WORKBENCH_SCOPE, CheckStudentSQLRequest,
                               CoachExperimentRequest, CompareRequest, FixtureRequest, InspectStudentSQLRequest,
                               KnowledgeRequest, QueryRequest, RunStudentSQLRequest, SearchRequest,
                               TransferRequest, contracts_for)
from sql_lab.executor import LabError, compare, describe, execute
from sql_lab.transfer import build_transfer


async def _cancellable_workbench(function, **arguments) -> dict:
    # Cancelling to_thread alone leaves its thread (and subsequent workers) alive.
    cancel_event = Event()
    try:
        return await asyncio.to_thread(function, **arguments, cancel_event=cancel_event)
    finally:
        # Also runs for caller timeouts; CancelledError must propagate unchanged.
        cancel_event.set()


async def _workbench_result(request) -> dict:
    """Load the optional SQL engine only for a workbench request; retain no observations."""
    if not isinstance(request, InspectStudentSQLRequest):
        from course_content.sql_tasks import task_view

        return {**task_view(request.task_id), "task_id": request.task_id}

    from sql_lab.workbench import evaluate, inspect_sql, run_query

    identity = {"task_id": request.task_id, "sql_digest": sha256(request.sql.encode()).hexdigest()}
    if isinstance(request, RunStudentSQLRequest):
        result = await _cancellable_workbench(run_query, **request.model_dump())
    elif isinstance(request, CheckStudentSQLRequest):
        result = await _cancellable_workbench(evaluate, **request.model_dump())
        identity.update(scenarios=request.scenarios, seed=request.seed)
    else:
        result = await asyncio.to_thread(inspect_sql, **request.model_dump())
    return {**result, **identity}


def create_server(fixture_id: str, index=None) -> Server:
    server = Server("querystep-sql-lab")
    observations: dict[str, dict] = {}
    contracts = contracts_for(fixture_id)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(name=name, description=description, inputSchema=request.model_json_schema(),
                     outputSchema=result.model_json_schema(),
                     annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
                for name, (request, result, description) in contracts.items()]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> dict:
        contract = contracts.get(name)
        if contract is None:
            raise LabError("unknown_tool")
        try:
            request = contract[0].model_validate(arguments)
        except ValidationError as error:
            raise LabError("invalid_parameters") from error

        if fixture_id == WORKBENCH_SCOPE:
            try:
                result = (await asyncio.to_thread(coach_search, request, index)
                          if isinstance(request, KnowledgeRequest) else await _workbench_result(request))
                return contract[1].model_validate(result).model_dump()
            except ValidationError as error:
                raise LabError("invalid_tool_result") from error
            except Exception as error:
                # Never expose SQL-engine exceptions, paths or runtime details over MCP.
                logging.warning("Workbench tool unavailable (%s)", type(error).__name__)
                raise LabError("workbench_tool_failed") from None

        if isinstance(request, TransferRequest):
            return build_transfer(**request.model_dump())
        if isinstance(request, KnowledgeRequest):
            return await asyncio.to_thread(coach_search, request, index)
        if isinstance(request, CoachExperimentRequest):
            return experiment(request)
        if isinstance(request, SearchRequest):
            return {"cards": search(request.query, request.topic, request.top_k)}
        if isinstance(request, CompareRequest):
            before = observations.get(request.before_id)
            after = observations.get(request.after_id)
            if before is None or after is None:
                raise LabError("unknown_observation")
            return {"comparison_id": uuid4().hex, "fixture_id": fixture_id,
                    **request.model_dump(), **compare(before, after)}
        if isinstance(request, FixtureRequest) and request.fixture_id != fixture_id:
            raise LabError("fixture_not_allowed")
        if isinstance(request, QueryRequest):
            if len(observations) >= 32:
                raise LabError("observation_limit_exceeded")
            result = execute(request.fixture_id, request.query_id, request.parameters)
            observation_id = uuid4().hex
            observations[observation_id] = {"observation_id": observation_id, **result}
            return observations[observation_id]
        return describe(request.fixture_id)

    return server


async def serve(fixture_id: str, index=None) -> None:
    server = create_server(fixture_id, index)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=(*FIXTURES, TRANSFER_SCOPE, COACH_SCOPE, WORKBENCH_SCOPE),
                        default=GROUPING_FIXTURE)
    parser.add_argument("--knowledge-index", type=Path)
    parser.add_argument("--embedding-model", type=Path)
    args = parser.parse_args()
    index = None
    if args.fixture in {COACH_SCOPE, WORKBENCH_SCOPE} and args.knowledge_index:
        from course_content.knowledge_index import open_index

        index = open_index(args.knowledge_index, args.embedding_model)
    try:
        asyncio.run(serve(args.fixture, index))
    finally:
        if index:
            index.close()


if __name__ == "__main__":
    main()
