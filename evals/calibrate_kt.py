"""Fit probability calibration using the validation fold only."""

import argparse
import csv
from collections import Counter
from pathlib import Path

from data_pipeline.preprocess import write_json
from evals.question_window import predict
from kt.train import DEFAULT_DATA, read_json


def training_counts(data: Path, validation_fold: int):
    counts, positives = Counter(), Counter()
    with (data / "train_valid.csv").open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if int(row["fold"]) == validation_fold:
                continue
            for question, label, repeat in zip(row["questions"].split(","), row["responses"].split(","),
                                               row["is_repeat"].split(","), strict=True):
                if repeat == "0":
                    counts[int(question)] += 1
                    positives[int(question)] += int(label)
    return counts, positives


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--allow-smoke", action="store_true")
    args = parser.parse_args()

    import numpy as np
    from sklearn.linear_model import LogisticRegression

    record, results = predict(args.run, args.data, "validation", args.batch_size, args.allow_smoke)
    labels = results["labels"]
    raw = np.clip(results["final_scores"], 1e-6, 1 - 1e-6)
    logits = np.log(raw / (1 - raw))
    model = LogisticRegression().fit(logits.reshape(-1, 1), labels)
    coefficient = float(model.coef_[0, 0])
    if coefficient <= 0:
        raise ValueError("Validation calibration inverted the ranking. Do not enable this run.")
    training = read_json(args.run / "training_metrics.json")
    counts, _ = training_counts(args.data, record["params"]["fold"])
    mapping = read_json(args.run / "keyid2idx.json")["questions"]
    write_json(args.run / "calibration.json", {
        "method": "validation_logistic", "coefficient": coefficient,
        "intercept": float(model.intercept_[0]), "fold": record["params"]["fold"],
        "validation_targets": len(labels), "smoke": record["params"]["smoke"],
        "checkpoint_sha256": training["checkpoint_sha256"],
        "mapping_sha256": training["mapping_sha256"],
        "catalog_kcs_sha256": training["question_kcs_sha256"],
        "source_questions_with_training_support": [
            int(source) for source, mapped in mapping.items() if counts[mapped] > 0
        ],
    })
    print(f"Saved calibration from {len(labels)} validation targets.")


if __name__ == "__main__":
    main()
