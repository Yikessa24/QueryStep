"""Paired retrieval evaluation on versioned SQL teaching prompts."""

import argparse
import json
from pathlib import Path
from statistics import median, quantiles
from time import monotonic

from course_content.knowledge_index import Embedder, KnowledgeIndex
from sql_lab.coach import search
from sql_lab.contracts import KnowledgeRequest

LEGACY = {
    "left-join/preserves-left": "join-on-preserves-left",
    "left-join/match-condition": "join-on-preserves-left",
    "where-after-join/predicate-placement": "join-where-after",
    "grouping/group-count": "aggregate-group-by",
    "having/filter-groups": "aggregate-having",
    "having/strict-inclusive": "aggregate-having-boundary",
}


def evaluate(index, path):
    cases = json.loads(path.read_text(encoding="utf-8"))
    report = {}
    for mode in ("reviewed_cards", "keyword", "vector", "hybrid"):
        outcomes = []
        for case in cases:
            start = monotonic()
            result = search(KnowledgeRequest(query=case["query"], topic=case["topic"],
                                             mode=mode if mode != "reviewed_cards" else "keyword"),
                            None if mode == "reviewed_cards" else index)
            ids = {card["id"] for card in result["cards"]}
            groups = [set(group) for group in case["expected"]]
            if mode == "reviewed_cards":
                groups = [{LEGACY.get(key, key) for key in group} for group in groups]
            hit = sum(bool(ids & group) for group in groups)
            outcomes.append({"case": case["id"], "kind": case["kind"], "matched": hit,
                             "required": len(groups), "returned": sorted(ids),
                             "elapsed_ms": (monotonic() - start) * 1000})
        report[mode] = {"rows": outcomes, "groups": {}}
        for kind in sorted({case["kind"] for case in cases}):
            rows = [row for row in outcomes if row["kind"] == kind]
            required = sum(row["required"] for row in rows)
            times = [row["elapsed_ms"] for row in rows]
            report[mode]["groups"][kind] = {
                "count": len(rows), "recall_at_3": sum(row["matched"] for row in rows) / required if required else None,
                "all_evidence": sum(row["matched"] == row["required"] for row in rows) if required else None,
                "false_hit": sum(bool(row["returned"]) for row in rows) if not required else None,
                "p50_ms": round(median(times), 3),
                "p95_ms": round(quantiles(times, n=20, method="inclusive")[-1] if len(times) > 1 else times[0], 3),
            }
    return {"manifest": index.manifest, "reports": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("course_search_cases.json"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    index = KnowledgeIndex(args.index, Embedder(args.model))
    if index.embedder is None:
        parser.error("the embedding model must match the index")
    try:
        report = evaluate(index, args.cases)
    finally:
        index.close()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({mode: result["groups"] for mode, result in report["reports"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
