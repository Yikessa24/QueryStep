"""Compare split and targeted course retrieval under a shared search budget."""

import argparse
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from random import Random
from statistics import mean, median, quantiles
from time import monotonic

from course_content.evidence_retrieval import retrieve_evidence
from course_content.knowledge_index import Embedder, KnowledgeIndex
from evals import evidence_coverage_cases as cases

STRATEGIES = {"A": "whole", "B": "whole_budget", "C": "split", "D": "targeted", "oracle": "targeted"}


def frozen_cases():
    for family, topic, facts, questions in cases.FAMILIES:
        for index, question in enumerate(questions, 1):
            yield {"id": f"{family}-{index}", "family": family, "topic": topic, "question": question,
                   "facts": [{"goal": goal, "fact": fact, "accepted": list(ids)} for goal, fact, ids in facts]}
    for index, (topic, question, ids) in enumerate(cases.SINGLES, 1):
        yield {"id": f"single-{index}", "family": "single", "topic": topic, "question": question,
               "facts": [{"fact": question, "accepted": list(ids)}]}
    for index, (topic, question) in enumerate(cases.NO_ANSWER, 1):
        yield {"id": f"unanswerable-{index}", "family": "unanswerable", "topic": topic, "question": question,
               "facts": []}


def paired(rows, control, treatment):
    families = defaultdict(list)
    improved, regressed = [], []
    for row in rows:
        before, after = (row["arms"][arm]["complete"] for arm in (control, treatment))
        diff = int(after) - int(before)
        families[row["family"]].append(diff)
        if diff > 0:
            improved.append(row["id"])
        elif diff < 0:
            regressed.append(row["id"])
    # Paraphrases share facts. Resample families so they do not inflate precision.
    averages = [mean(group) for group in families.values()]
    rng = Random(20261120)
    bootstrap = sorted(mean(rng.choices(averages, k=len(averages))) * 100 for _ in range(10000))
    return {"improved": improved, "regressed": regressed,
            "delta_pp": round(100 * mean(averages), 2),
            "family_bootstrap_95_pp": [round(bootstrap[i], 2) for i in (250, 9749)]}


def run(index):
    outcomes = []
    for case in frozen_cases():
        facts = case["facts"]
        goals = tuple(fact["goal"] for fact in facts) if len(facts) == 2 else ()
        unknown = {card for fact in facts for card in fact["accepted"] if card not in index.cards}
        if unknown:
            raise ValueError(f"Fixture labels refer to unknown cards: {unknown}")
        arms = {}
        for arm, strategy in STRATEGIES.items():
            started = monotonic()
            result = retrieve_evidence(index, case["question"], case["topic"], strategy=strategy,
                                       goals=goals if arm == "oracle" else None)
            elapsed = round((monotonic() - started) * 1000, 3)
            ids = [card["id"] for card in result["cards"]]
            hits = [bool(set(ids) & set(fact["accepted"])) for fact in facts]
            slots = sum(step["limit"] for step in result["passes"])
            if len(ids) > 3 or slots > 18:
                raise ValueError("Retrieval exceeded the evaluation budget.")
            arms[arm] = {"ids": ids, "hits": hits, "complete": all(hits) if hits else not ids,
                         "latency_ms": elapsed, "candidate_slots": slots, "passes": result["passes"],
                         "coverage": result["coverage"], "mode": result["mode"]}
        outcomes.append({**case, "arms": arms})
    crossed = [row for row in outcomes if len(row["facts"]) == 2]
    singles = [row for row in outcomes if len(row["facts"]) == 1]
    negatives = [row for row in outcomes if not row["facts"]]
    summary = {}
    for arm in STRATEGIES:
        results = [row["arms"][arm] for row in crossed]
        times = [result["latency_ms"] for result in results]
        summary[arm] = {"both": sum(result["complete"] for result in results),
                        "facts": sum(sum(result["hits"]) for result in results),
                        "single": sum(row["arms"][arm]["complete"] for row in singles),
                        "false_hits": sum(not row["arms"][arm]["complete"] for row in negatives),
                        "attempts": sum(len(result["passes"]) for result in results),
                        "retries": sum(any(step["retry"] for step in result["passes"]) for result in results),
                        "slots_per_question": round(mean(result["candidate_slots"] for result in results), 2),
                        "p50_ms": round(median(times), 2),
                        "p95_ms": round(quantiles(times, n=20, method="inclusive")[-1], 2)}
    comparison = {f"{treatment}-{control}": paired(crossed, control, treatment)
                  for control, treatment in (("A", "D"), ("B", "D"), ("C", "D"))}
    return {"index": deepcopy(index.manifest), "cases_sha256": sha256(Path(cases.__file__).read_bytes()).hexdigest(),
            "counts": {"cross": len(crossed), "single": len(singles), "unanswerable": len(negatives)},
            "summary": summary, "comparison": comparison, "rows": outcomes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    index = KnowledgeIndex(args.index, Embedder(args.model))
    try:
        if index.embedder is None:
            parser.error("the embedding model must match the index")
        data = run(index)
    finally:
        index.close()
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({**data["counts"], **data["summary"], **data["comparison"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
