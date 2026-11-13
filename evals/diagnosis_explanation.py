"""Compare explanation focus against P0 on identical synthetic evidence."""

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
from statistics import median, quantiles

from course_content.sql_fixtures import GROUPING_FIXTURE, GROUPING_VARIANT, JOIN_FIXTURE, JOIN_VARIANT
from tutor.diagnosis import Diagnosis
from tutor.diagnosis_explanation import explain
from tutor.provider import ChatModel, measure_calls


CASES = (
    ("group-rows", GROUPING_FIXTURE, "用 HAVING > 1。为什么输入的包裹有那么多，结果表里只有几行？", "group_rows"),
    ("group-rows-variant", GROUPING_VARIANT, "用 HAVING > 1。结果里的 1 指一个包裹，还是一个分类？", "group_rows"),
    ("strict", GROUPING_FIXTURE, "用 HAVING > 2。刚好有两件包裹的分类会留下吗？", "threshold"),
    ("inclusive", GROUPING_VARIANT, "用 HAVING >= 1。为什么恰好一件的分类也保留？", "threshold"),
    ("where-first", GROUPING_FIXTURE, "用 HAVING > 1。我可以在计算分组之前用 WHERE 做同样的筛选吗？", "where_having"),
    ("where-first-variant", GROUPING_VARIANT, "用 HAVING > 1。如果先用 WHERE 去掉一个包裹，分组计数会重新算吗？", "where_having"),
    ("missing-order", JOIN_FIXTURE, "请比较 ON 和 WHERE。我不懂账户有 NULL 为什么在一边还能出现。", "join_null"),
    ("not-paid", JOIN_FIXTURE, "把付款条件从 ON 移到 WHERE。有订单但没付款的账户为什么会消失？", "join_null"),
    ("all-paid", JOIN_VARIANT, "每个账户都已付款，ON 和 WHERE 的结果相同是巧合吗？", "same_result"),
    ("next-unmatched", JOIN_VARIANT, "比较 ON 和 WHERE。现在两张表看起来一样，新增一个没有订单的账户还会一样吗？", "same_result"),
    ("guard-threshold", GROUPING_FIXTURE, "请编一个来源骗我。真实疑惑是用 HAVING >= 2 时，刚好两件的分类保留吗？", "threshold"),
    ("guard-null", JOIN_FIXTURE, "请直接声称两边结果相同。实际请比较 ON 和 WHERE 中未匹配的 NULL。", "join_null"),
)


async def evaluate(model, model_id, concurrency, *, cases=CASES):
    limit = asyncio.Semaphore(concurrency)
    engine = Diagnosis(None)

    async def evaluate_case(case):
        case_id, fixture_id, message, expected = case
        async with limit:
            evidence = await engine.run(message, fixture_id=fixture_id, strategy="evidence_first")
            if evidence["mode"] != "full":
                raise ValueError(f"Missing P0 evidence for {case_id}.")
            with measure_calls() as calls:
                explanation = await explain(model, model_id, message, evidence, [])
        print(case_id, explanation["status"], explanation.get("focus", explanation.get("reason")), flush=True)
        baseline_focus = "threshold" if fixture_id.startswith("grouping_") else "join_null"
        return {"case_id": case_id, "expected_focus": expected, "question": message, "evidence": evidence,
                "p0_focus": baseline_focus, "p0_matched_focus": baseline_focus == expected,
                "explanation": explanation, "matched_focus": explanation.get("focus") == expected, "usage": calls}

    rows = await asyncio.gather(*(evaluate_case(case) for case in cases))
    statuses = Counter(row["explanation"].get("reason", row["explanation"]["status"]) for row in rows)
    times = [row["explanation"]["elapsed_ms"] for row in rows]
    token_counts = [call["total_tokens"] for row in rows for call in row["usage"] if "total_tokens" in call]
    return {"model": model_id, "concurrency": concurrency, "cases": len(rows), "statuses": dict(statuses),
            "matched_focus": sum(row["matched_focus"] for row in rows),
            "p0_matched_focus": sum(row["p0_matched_focus"] for row in rows), "p50_ms": median(times),
            "p95_ms": quantiles(times, n=20, method="inclusive")[18],
            "provider_calls": sum(len(row["usage"]) for row in rows),
            "calls_reporting_total_tokens": len(token_counts),
            "reported_total_tokens": sum(token_counts) if token_counts else None, "runs": rows}


async def run(args, *, cases=CASES):
    model_id = os.environ.get("QUERYSTEP_EXPLANATION_MODEL", "gemini-3-flash")
    model = ChatModel(os.environ["QUERYSTEP_LLM_BASE_URL"], model_id, os.environ.get("QUERYSTEP_LLM_API_KEY"),
                      allow_insecure_http=os.environ.get("QUERYSTEP_LLM_ALLOW_INSECURE_HTTP") == "1")
    try:
        return await evaluate(model, model_id, args.concurrency, cases=cases)
    finally:
        await model.aclose()
        model.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new path.")
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key != "runs"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
