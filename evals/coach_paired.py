"""Run the real provider and MCP for paired observations and a fixed-policy control."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from sql_lab.client import open_lab
from sql_lab.contracts import COACH_SCOPE
from tutor.coach import Coach
from tutor.provider import ChatModel, measure_calls

CASES = (
    ("join", "查询课程规则，验证把右表状态条件从 ON 移到 WHERE 为什么可能少一行。", "join_filter"),
    ("aggregate", "查找课程规则并执行对照，HAVING COUNT(*) >= 2 和 > 2 为什么有时结果一样？", "having_boundary"),
)


class FixedPlanner:
    """A control with the same two tools, always comparing both scenes."""

    async def reply_json(self, messages, *args, **kwargs):
        state = json.loads(messages[-1]["content"])
        experiments = [item for item in state["evidence"] if "same" in item]
        experiment = next(tool for topic, _, tool in CASES if topic == state["topic"])
        pending = {"kind": "experiment", "experiment": experiment}
        if not experiments:
            payload = {"finish": "continue", "actions": [
                {"kind": "search", "query": state["question"]}, {**pending, "scenario": state["default_scenario"]},
            ], "references": []}
        elif len(experiments) == 1:
            other = "boundary" if experiments[0]["scenario"] == "matching" else "matching"
            payload = {"finish": "continue", "actions": [{**pending, "scenario": other}], "references": []}
        else:
            boundary = next(item for item in experiments if item["scenario"] == "boundary")
            cards = [item["id"] for item in state["evidence"] if "title" in item]
            payload = {"finish": "hint", "actions": [], "references": [*cards[:2], boundary["id"]]}
        return {"content": json.dumps(payload)}


async def evaluate(index, embedding_path, model, model_id):
    arguments = ("--knowledge-index", str(index.resolve()), "--embedding-model", str(embedding_path.resolve()))
    async with open_lab(COACH_SCOPE, knowledge_args=arguments) as lab:
        for strategy, provider in (("fixed", FixedPlanner()), ("adaptive", model)):
            coach = Coach(provider, model_id, lab)
            for topic, question, _ in CASES:
                for scenario in ("matching", "boundary"):
                    with measure_calls() as usage:
                        result = await coach.run(question, topic, scenario=scenario)
                    comparisons = [event["same"] for event in result["trace"] if "same" in event]
                    report = {key: result[key] for key in ("status", "reason", "model_calls", "tool_calls",
                                                           "elapsed_ms", "trace", "citations")}
                    report.update(strategy=strategy, topic=topic, scenario=scenario, usage=usage,
                                  model_calls=result["model_calls"] if strategy == "adaptive" else 0,
                                  compared=comparisons,
                                  course_found=any(item["kind"] == "course" for item in result["evidence"]))
                    yield report


async def main(args):
    model = ChatModel(os.environ["QUERYSTEP_LLM_BASE_URL"], os.environ["QUERYSTEP_LLM_MODEL"],
                      os.environ.get("QUERYSTEP_LLM_API_KEY"),
                      allow_insecure_http=os.environ.get("QUERYSTEP_LLM_ALLOW_INSECURE_HTTP") == "1")
    try:
        with args.output.open("w", encoding="utf-8") as output:
            async for row in evaluate(args.index, args.embedding_model, model, args.model):
                print(json.dumps(row, ensure_ascii=False), file=output, flush=True)
                print(row["strategy"], row["topic"], row["scenario"], row["status"],
                      row["compared"], row["tool_calls"], row["elapsed_ms"], flush=True)
    finally:
        await model.aclose()
        model.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--embedding-model", required=True, type=Path)
    parser.add_argument("--model", default="gemini-3-flash")
    parser.add_argument("--output", required=True, type=Path)
    asyncio.run(main(parser.parse_args()))
