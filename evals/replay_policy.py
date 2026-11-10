"""Compare EpiKT and rule decisions on the same held-out prefixes and candidates."""

import argparse
from collections import Counter
import csv
from itertools import islice
import json
from pathlib import Path

from api.catalog import Catalog
from api.recommend import ACTION, CalibratedScorer, Recommender
from data_pipeline.preprocess import sha256, write_json
from kt.train import DEFAULT_DATA, read_json, verified_data


def replay(dataset: Path, catalog: Catalog, scorer: CalibratedScorer, limit: int | None) -> dict:
    by_source = {item.source_question_id: item for item in catalog.items.values()}
    inverse = {str(index): int(source) for source, index in scorer.model.mapping["questions"].items()}
    policy = Recommender(scorer)
    counts = Counter()
    squared_errors = Counter()
    example = None
    with (dataset / "test.csv").open(encoding="utf-8", newline="") as source:
        for row in islice(csv.DictReader(source), limit):
            if row["fold"] != "-1":
                raise ValueError("Replay only accepts held-out learners.")
            counts["learners"] += 1
            history = []
            for question, label, repeat in zip(
                    row["questions"].split(","), row["responses"].split(","),
                    row["is_repeat"].split(","), strict=True):
                if repeat != "0":
                    continue
                target = by_source.get(inverse[question])
                if len(history) >= 3:
                    counts["eligible_prefixes"] += 1
                    decision = policy.decide(catalog.items, history)
                    if decision and decision["source"] == "epikt":
                        counts["epikt_decisions"] += 1
                        trace = decision["trace"]
                        chosen = decision["item_id"]
                        rule = trace["rule_item_id"]
                        if chosen in {item.id for item, _ in history} or chosen not in trace["candidate_ids"]:
                            raise ValueError("A replayed decision violated the candidate constraints.")
                        if ACTION[catalog.items[chosen].level] == "advance":
                            recent = [ok for item, ok in history[-5:] if item.topic == history[-1][0].topic]
                            if sum(recent) < 2 or not 0.65 <= trace["epikt_scores"][chosen] <= 0.85:
                                raise ValueError("A replayed decision violated advancement constraints.")
                        if chosen != rule:
                            counts["changed_item"] += 1
                            if rule is None or catalog.items[chosen].level != catalog.items[rule].level:
                                counts["changed_action"] += 1
                            if example is None:
                                example = {"history_length": len(history), "chosen_item": chosen,
                                           "rule_item": rule, "candidate_count": len(trace["candidate_ids"])}
                        if target and target.id in trace["epikt_scores"]:
                            counts["observed_targets_in_candidates"] += 1
                            for method in ("epikt", "rule"):
                                squared_errors[method] += (trace[f"{method}_scores"][target.id] - int(label)) ** 2
                    else:
                        reason = decision["reason"] if decision else "no_decision"
                        counts[f"fallback_{reason}"] += 1
                if not target or label not in {"0", "1"}:
                    # Subsequent prefixes would omit a real event.
                    counts["learners_with_incompatible_history"] += 1
                    break
                history.append((target, label == "1"))

    observed = counts["observed_targets_in_candidates"]
    return {"counts": dict(counts), "example_of_changed_item": example,
            "brier_on_observed_targets": {method: squared_errors[method] / observed
                                          for method in ("epikt", "rule")} if observed else {}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--max-learners", type=int)
    parser.add_argument("--allow-smoke", action="store_true")
    args = parser.parse_args()
    if args.max_learners is not None and args.max_learners < 1:
        parser.error("--max-learners must be positive.")
    config = read_json(args.run / "config.json")
    if sha256(args.data / "manifest.json") != config["data_manifest_sha256"]:
        raise ValueError("Replay requires the same prepared dataset as training.")
    verified_data(args.data, ("test.csv",))
    catalog = Catalog.load(args.catalog)
    import torch

    torch.set_num_threads(min(torch.get_num_threads(), 4))
    scorer = CalibratedScorer(args.run, timeout=10, offline=True, allow_smoke=args.allow_smoke)
    try:
        report = replay(args.data, catalog, scorer, args.max_learners)
    finally:
        scorer.close()
    report.update({"smoke": config["params"]["smoke"], "model_version": scorer.version,
                   "catalog_revision": catalog.revision, "max_learners": args.max_learners,
                   "dataset_manifest_sha256": config["data_manifest_sha256"]})
    write_json(args.run / "policy_replay.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
