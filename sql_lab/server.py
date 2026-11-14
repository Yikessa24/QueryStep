"""Serve the diagnostic tools over a per-run MCP stdio connection."""

import argparse
import asyncio
import logging
from pathlib import Path
import sqlite3
from uuid import uuid4

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, ToolAnnotations
from pydantic import ValidationError

from course_content.diagnosis_cards import search
from course_content.sql_fixtures import FIXTURES, GROUPING_FIXTURE
from sql_lab.coach import experiment, search as coach_search
from sql_lab.contracts import (COACH_SCOPE, TRANSFER_SCOPE, CoachExperimentRequest, CompareRequest, FixtureRequest,
                               KnowledgeRequest, QueryRequest, SearchRequest, TransferRequest, contracts_for)
from sql_lab.executor import LabError, compare, describe, execute
from sql_lab.transfer import build_transfer


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
    parser.add_argument("--fixture", choices=(*FIXTURES, TRANSFER_SCOPE, COACH_SCOPE), default=GROUPING_FIXTURE)
    parser.add_argument("--knowledge-index", type=Path)
    parser.add_argument("--embedding-model", type=Path)
    args = parser.parse_args()
    index = None
    if args.fixture == COACH_SCOPE and args.knowledge_index:
        from course_content.knowledge_index import Embedder, KnowledgeIndex

        embedder = None
        if args.embedding_model:
            try:
                embedder = Embedder(str(args.embedding_model.resolve()))
            except (ImportError, OSError, ValueError, RuntimeError) as error:
                logging.warning("Coach embedding unavailable (%s)", type(error).__name__)
        try:
            index = KnowledgeIndex(args.knowledge_index, embedder)
        except (ImportError, OSError, ValueError, KeyError, RuntimeError, TypeError, sqlite3.Error) as error:
            logging.warning("Coach knowledge unavailable (%s)", type(error).__name__)
    try:
        asyncio.run(serve(args.fixture, index))
    finally:
        if index:
            index.close()


if __name__ == "__main__":
    main()
