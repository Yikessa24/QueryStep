"""Prepare and score randomized, blinded P0/P1 HAVING review packets."""

import argparse
import asyncio
from collections import Counter
import csv
import json
from pathlib import Path
from random import Random
from statistics import mean

from evals.diagnosis_explanation import run
from evals.having_review_cases import CASES


DIMENSIONS = ("sql_accuracy", "addresses_misconception", "useful_next_step")


def prepare(report, directory, seed):
    directory.mkdir(parents=True, exist_ok=False)
    rng = Random(seed)
    key = {"seed": seed, "cases": {}}
    fields = ["case_id", "candidate", *DIMENSIONS, "notes"]
    with (directory / "review.md").open("x", encoding="utf-8") as packet, \
            (directory / "scores.csv").open("x", encoding="utf-8", newline="") as scores:
        packet.write("# HAVING 讲解盲审\n\n请只阅读本文件，独立填写 scores.csv。每项给 0、1 或 2 分。\n\n"
                     "- SQL 准确性。0 有事实错误，1 正确但关键条件缺失，2 正确且说明相关条件。\n"
                     "- 回应误解。0 没回应，1 部分回应，2 直接回应学生的判断。\n"
                     "- 后续行动。0 没有可用的下一步，1 有笼统建议，2 有能检验理解的具体追问。\n\n")
        writer = csv.DictWriter(scores, fieldnames=fields)
        writer.writeheader()
        for row in report["runs"]:
            case_id, evidence = row["case_id"], row["evidence"]
            baseline = evidence["summary"]
            extra = row["explanation"]
            candidates = [("p0", baseline), ("p1", baseline)]
            if extra["status"] == "ready":
                candidates[1] = ("p1", f"{baseline}\n\n{extra['text']} {extra['question']}")
            rng.shuffle(candidates)
            key["cases"][case_id] = {label: strategy for label, (strategy, _) in zip("AB", candidates, strict=True)}
            packet.write(f"## {case_id}\n\n{row['question']}\n\n")
            for observation in evidence["observations"]:
                packet.write(f"```sql\n{observation['sql']}\n```\n\n")
                packet.write(f"参数 `{json.dumps(observation['parameters'])}`，结果 `{json.dumps(observation['rows'], ensure_ascii=False)}`。\n\n")
            for source in evidence["sources"]:
                packet.write(f"- {source['title']}。{source['text']}\n")
            for label, (_, explanation) in zip("AB", candidates, strict=True):
                packet.write(f"\n### 讲解 {label}\n\n{explanation}\n")
                writer.writerow({"case_id": case_id, "candidate": label})
            packet.write("\n")
    (directory / "review-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "model-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def score(key, score_files):
    expected = {(case, label) for case, labels in key["cases"].items() for label in labels}
    if len({path.resolve() for path in score_files}) != len(score_files):
        raise ValueError("Each review file must come from a different reviewer.")
    reviewers = []
    for file in score_files:
        records = {}
        with file.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                pair = row["case_id"], row["candidate"]
                if pair not in expected or pair in records:
                    raise ValueError(f"Unknown or duplicate review pair in {file.name}: {pair}")
                values = tuple(row[dimension].strip() for dimension in DIMENSIONS)
                if any(value not in ("0", "1", "2") for value in values):
                    raise ValueError(f"Scores must be complete and within 0–2 in {file.name}: {pair}")
                records[pair] = tuple(map(int, values))
        if records.keys() != expected:
            raise ValueError(f"Incomplete review: {file.name}")
        reviewers.append(records)
    totals = Counter()
    differences = []
    for case, labels in key["cases"].items():
        by_strategy = {strategy: [mean(records[case, label][index] for records in reviewers)
                                  for index in range(len(DIMENSIONS))] for label, strategy in labels.items()}
        delta = sum(by_strategy["p1"]) - sum(by_strategy["p0"])
        totals["p1_win" if delta > 0 else "p0_win" if delta < 0 else "tie"] += 1
        differences.append({"case_id": case, "p1_minus_p0": dict(zip(DIMENSIONS,
                            (b - a for a, b in zip(by_strategy["p0"], by_strategy["p1"], strict=True)), strict=True))})
    return {"reviewers": len(reviewers), "cases": len(differences), "paired_outcomes": dict(totals),
            "mean_p1_minus_p0": {name: mean(row["p1_minus_p0"][name] for row in differences) for name in DIMENSIONS},
            "by_case": differences}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--seed", type=int, default=20261113)
    build.add_argument("--concurrency", type=int, choices=(1, 2, 3), default=1)
    build.add_argument("--cases", type=Path, help="JSON rows with case_id, fixture_id, question and expected_focus.")
    review = commands.add_parser("score")
    review.add_argument("--key", type=Path, required=True)
    review.add_argument("--scores", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.output.exists():
            parser.error("Output directory already exists.")
        cases = CASES
        if args.cases:
            try:
                data = json.loads(args.cases.read_text(encoding="utf-8"))
                allowed_fixtures = {row[1] for row in CASES}
                allowed_focuses = {row[3] for row in CASES}
                cases = [(row["case_id"], row["fixture_id"], row["question"], row["expected_focus"]) for row in data]
                if (len(cases) < 2 or len({row[0] for row in cases}) != len(cases)
                        or any(not isinstance(case_id, str) or not case_id.isascii() or not case_id.replace("-", "").isalnum()
                               or fixture not in allowed_fixtures or focus not in allowed_focuses
                               or not isinstance(question, str) or not 1 <= len(question.strip()) <= 500
                               for case_id, fixture, question, focus in cases)):
                    raise ValueError("Expected unique case IDs and supported HAVING fixtures and focuses.")
            except (OSError, ValueError, TypeError, KeyError) as error:
                parser.error(str(error))
        prepare(asyncio.run(run(args, cases=cases)), args.output, args.seed)
    else:
        try:
            result = score(json.loads(args.key.read_text(encoding="utf-8")), args.scores)
        except (ValueError, KeyError) as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
