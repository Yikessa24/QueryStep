"""Run the SQL lab through the actual MCP stdio client and print the evidence."""

import argparse
import asyncio
import json

from course_content.sql_fixtures import FIXTURES, GROUPING_FIXTURE
from sql_lab.client import open_lab


async def check(fixture_id: str) -> dict:
    async with open_lab(fixture_id) as lab:
        fixture = {"fixture_id": fixture_id}
        topic = FIXTURES[fixture_id].topic
        notes = await lab.call("course", "search_course_notes", {
            "query": "HAVING COUNT 分组" if topic == "aggregate" else "LEFT JOIN ON WHERE NULL",
            "topic": topic, "top_k": 2,
        })
        if topic == "join":
            observations = [await lab.call("experiment", "run_example_query", {
                **fixture, "query_id": query,
            }) for query in ("join_on", "join_where")]
            difference = await lab.call("experiment", "compare_example_results", {
                "before_id": observations[0]["observation_id"], "after_id": observations[1]["observation_id"],
            })
            return {"fixture_id": fixture_id, "course_sources": [card["id"] for card in notes["cards"]],
                    "join_on": observations[0]["rows"], "join_where": observations[1]["rows"], "comparison": difference}
        baseline = await lab.call("experiment", "run_example_query", {
            **fixture, "query_id": "group_counts",
        })
        filtered = await lab.call("experiment", "run_example_query", {
            **fixture, "query_id": "having_gt", "parameters": {"min_count": 1},
        })
        inclusive = await lab.call("experiment", "run_example_query", {
            **fixture, "query_id": "having_gte", "parameters": {"min_count": 1},
        })
        difference = await lab.call("experiment", "compare_example_results", {
            "before_id": baseline["observation_id"], "after_id": filtered["observation_id"],
        })
    return {"fixture_id": fixture_id, "course_sources": [card["id"] for card in notes["cards"]],
            "group_counts": baseline["rows"], "having_gt": filtered["rows"],
            "having_gte": inclusive["rows"], "comparison": difference}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=FIXTURES, default=GROUPING_FIXTURE)
    print(json.dumps(asyncio.run(check(parser.parse_args().fixture)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
