"""Compare the legacy tutor and MCP diagnosis strategies on synthetic SQL cases."""

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
import json
import os
from pathlib import Path
from statistics import median, quantiles
from time import monotonic

from api.catalog import Catalog, DEFAULT_CATALOG
from course_content.diagnosis_cards import CARDS
from course_content.sql_fixtures import FIXTURES
from evals.diagnosis_cases import AGGREGATE_OVERRIDES, CASES
from tutor.agent import TutorAgent
from tutor.diagnosis import Diagnosis
from tutor.provider import ChatModel, measure_calls


def assess(report: dict, expected: list[str], topic: str, case_id: str) -> dict:
    comparison = report.get("comparison")
    observations = {row["observation_id"]: row for row in report.get("observations", [])}
    valid_sources = {card["id"]: card["version"] for card in CARDS if card["topic"] == topic}
    sources = report.get("sources", [])
    cited = bool(sources) and all(valid_sources.get(card["id"]) == card["version"] for card in sources)
    consistent = False
    query_matches = False
    if comparison:
        before = observations.get(comparison["before_id"])
        after = observations.get(comparison["after_id"])
        if before and after:
            left = {str(row[0]): row for row in before["rows"]}
            right = {str(row[0]): row for row in after["rows"]}
            consistent = (set(comparison["removed_keys"]) == left.keys() - right.keys()
                          and set(comparison["added_keys"]) == right.keys() - left.keys()
                          and set(comparison["changed_keys"]) == {key for key in left.keys() & right.keys()
                                                                  if left[key] != right[key]}
                          and comparison["before_row_count"] == len(before["rows"])
                          and comparison["after_row_count"] == len(after["rows"]))
            if topic == "join":
                query_matches = before["query_id"] == "join_on" and after["query_id"] == "join_where"
            else:
                query_id, min_count = AGGREGATE_OVERRIDES.get(case_id, ("having_gt", 1))
                query_matches = (before["query_id"] == "group_counts" and after["query_id"] == query_id
                                 and after["parameters"] == {"min_count": min_count})
    verified = bool(consistent and query_matches and comparison["removed_keys"] == expected)
    return {"verified_requested_result": verified,
            "complete_diagnosis": bool(report.get("mode") == "full" and verified and cited),
            "requested_query_matched": query_matches if comparison else None,
            "evidence_consistent": consistent if comparison else None,
            "valid_course_citations": cited if sources else None}


async def evaluate(model: ChatModel | None, cases, strategies: list[str], concurrency: int = 1) -> dict:
    originals = Catalog.load(DEFAULT_CATALOG)
    legacy = TutorAgent(model, timeout=30)
    engine = Diagnosis(model)
    capacity = asyncio.Semaphore(concurrency)

    async def evaluate_case(case):
        case_id, fixture_id, question, expected = case
        topic = FIXTURES[fixture_id].topic
        rows = []
        async with capacity:
            for strategy in strategies:
                started = monotonic()
                with measure_calls() as calls:
                    try:
                        if strategy == "legacy":
                            item = replace(originals.items[1], topic=topic, prompt="Independent SQL teaching example",
                                           hint="请先检查 SQL 各子句的作用。")
                            report = await asyncio.to_thread(legacy.respond, item, question, [])
                        else:
                            report = await engine.run(question, fixture_id=fixture_id, strategy=strategy)
                    except Exception as error:
                        report = {"mode": "error", "fallback_reason": type(error).__name__}
                    usage = [dict(call) for call in calls]
                rows.append({"case_id": case_id, "strategy": strategy, "fixture_id": fixture_id, "question": question,
                             "expected_removed_keys": expected, "elapsed_ms": round((monotonic() - started) * 1000),
                             "provider_calls": len(usage), "usage": usage,
                             **assess(report, expected, topic, case_id), "result": report})
                print(f"{case_id} {strategy} {report.get('mode', report.get('source'))}", flush=True)
        return rows

    groups = await asyncio.gather(*(evaluate_case(case) for case in cases))
    rows = [row for group in groups for row in group]
    return {"model": model.model if model else None, "suite": "synthetic-sql-v1", "concurrency": concurrency,
            "catalog_revision": originals.revision, "summary": summarize(rows), "runs": rows}


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for strategy in dict.fromkeys(row["strategy"] for row in rows):
        group = [row for row in rows if row["strategy"] == strategy]
        times = [row["elapsed_ms"] for row in group]
        calls = [call for row in group for call in row["usage"]]
        token_counts = [call["total_tokens"] for call in calls if "total_tokens" in call]
        summary[strategy] = {
            "cases": len(group),
            "complete_diagnosis": sum(row["complete_diagnosis"] for row in group),
            "clarification_requested": sum(row["result"].get("mode") == "clarify" for row in group),
            "verified_requested_result": sum(row["verified_requested_result"] for row in group),
            "consistent_evidence": sum(row["evidence_consistent"] is True for row in group),
            "evidence_checked": sum(row["evidence_consistent"] is not None for row in group),
            "valid_course_citations": sum(row["valid_course_citations"] is True for row in group),
            "citations_checked": sum(row["valid_course_citations"] is not None for row in group),
            "provider_calls": len(calls), "calls_reporting_total_tokens": len(token_counts),
            "reported_total_tokens": sum(token_counts) if token_counts else None,
            "fallbacks": dict(Counter(row["result"]["fallback_reason"] for row in group
                                      if row["result"].get("fallback_reason"))),
            "p50_ms": median(times), "p95_ms": quantiles(times, n=20, method="inclusive")[18] if len(times) > 1 else None,
        }
    return summary


def reassess(report: dict) -> dict:
    cases = {case_id: (fixture_id, question, expected) for case_id, fixture_id, question, expected in CASES}
    for row in report["runs"]:
        case_id = row["case_id"]
        fixture_id, question, expected = cases[case_id]
        if row["fixture_id"] != fixture_id or row["expected_removed_keys"] != expected:
            raise ValueError(f"The saved report uses a different fixture or answer for {case_id}.")
        row.update(assess(row["result"], expected, FIXTURES[fixture_id].topic, case_id), question=question)
    return {**report, "summary": summarize(report["runs"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", choices=[row[0] for row in CASES])
    parser.add_argument("--strategies", nargs="+", choices=["legacy", "single", "parallel", "evidence_first"],
                        default=["legacy", "single", "parallel"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=1, choices=range(1, 5))
    parser.add_argument("--from-report", type=Path, help="Recompute metrics without calling the model.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new report path.")
    if args.from_report:
        report = reassess(json.loads(args.from_report.read_text(encoding="utf-8")))
    else:
        model = None
        if set(args.strategies) != {"evidence_first"}:
            model = ChatModel(os.environ["QUERYSTEP_LLM_BASE_URL"], os.environ["QUERYSTEP_LLM_MODEL"],
                              os.environ.get("QUERYSTEP_LLM_API_KEY"),
                              allow_insecure_http=os.environ.get("QUERYSTEP_LLM_ALLOW_INSECURE_HTTP") == "1")
        try:
            cases = [row for row in CASES if not args.cases or row[0] in args.cases]
            report = asyncio.run(evaluate(model, cases, list(dict.fromkeys(args.strategies)), args.concurrency))
        finally:
            if model:
                model.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
