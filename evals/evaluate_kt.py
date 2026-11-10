"""Evaluate on pyKT's held-out question windows with late_mean."""

import argparse
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from data_pipeline.preprocess import sha256, write_json
from evals.kt_baselines import compare_windows
from evals.question_window import predict
from kt.release import BASELINE_NAMES, GATE_VERSION, meets_scoring_gate
from kt.scoring import load_calibration
from kt.train import DEFAULT_DATA, read_json


def reliability(labels, probabilities) -> list[dict]:
    assignments = np.minimum((probabilities * 10).astype(int), 9)
    bins = []
    for index in range(10):
        subset = assignments == index
        if subset.any():
            bins.append({"bin": index, "n": int(subset.sum()),
                         "observed": float(labels[subset].mean()),
                         "predicted": float(probabilities[subset].mean())})
    return bins


def measure(labels, probabilities) -> dict:
    bins = reliability(labels, probabilities)
    return {
        "auc": float(roc_auc_score(labels, probabilities)) if len(np.unique(labels)) == 2 else None,
        "acc": float(accuracy_score(labels, probabilities >= 0.5)),
        "brier": float(brier_score_loss(labels, probabilities)),
        "nll": float(log_loss(labels, probabilities, labels=[0, 1])),
        "ece": sum(row["n"] * abs(row["observed"] - row["predicted"]) for row in bins) / len(labels),
    }


def paired_brier_interval(labels, predictions, reference, learners) -> list[float]:
    _, group = np.unique(learners, return_inverse=True)
    sizes = np.bincount(group)
    difference = (predictions - labels) ** 2 - (reference - labels) ** 2
    sums = np.bincount(group, weights=difference)
    sample = np.random.default_rng(3407).integers(0, len(sizes), size=(1000, len(sizes)))
    bootstrap = sums[sample].sum(axis=1) / sizes[sample].sum(axis=1)
    return np.quantile(bootstrap, [0.025, 0.975]).tolist()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--allow-smoke", action="store_true")
    args = parser.parse_args()

    record, results = predict(args.run, args.data, "test", args.batch_size, args.allow_smoke)
    labels = results["labels"]
    probabilities = results["final_scores"]
    fold = record["params"]["fold"]
    baseline = compare_windows(args.data, fold, results)
    supported = baseline["supported"]
    length = baseline["history_length"]
    coverage = supported & (length >= 3)
    raw = measure(labels, probabilities)
    metrics = {"protocol": "pykt_question_window_late_mean", "fold": fold,
               "smoke": record["params"]["smoke"], "question_targets": len(labels),
               "question_auc": raw["auc"], "question_acc": raw["acc"], "question_brier": raw["brier"],
               "question_prior_brier": float(brier_score_loss(labels, baseline["question_prior"])),
               "data_manifest_sha256": record["data_manifest_sha256"],
               "scoring_gate_version": GATE_VERSION, "supported_targets": int(supported.sum()),
               "covered_targets": int(coverage.sum()),
               "passes_scoring_gate": False}

    predictors = {name: baseline[name] for name in BASELINE_NAMES}
    predictors["epikt_raw"] = probabilities
    path = args.run / "calibration.json"
    if path.exists():
        training = read_json(args.run / "training_metrics.json")
        calibration = load_calibration(args.run, record, training)
        bounded = np.clip(probabilities, 1e-6, 1 - 1e-6)
        logit = np.log(bounded / (1 - bounded))
        adjusted = calibration["coefficient"] * logit + calibration["intercept"]
        calibrated = 1 / (1 + np.exp(-np.clip(adjusted, -60, 60)))
        full = measure(labels, calibrated)
        predictors["epikt_calibrated"] = calibrated
        metrics.update({"calibrated_brier": full["brier"], "calibrated_ece": full["ece"],
                        "calibration_sha256": sha256(path)})

    if coverage.any():
        common = {name: measure(labels[coverage], values[coverage]) for name, values in predictors.items()}
        strongest = min(BASELINE_NAMES, key=lambda name: common[name]["brier"])
        metrics.update({"common_coverage": common, "strongest_baseline": strongest,
                        "reliability": {name: reliability(labels[coverage], values[coverage])
                                        for name, values in predictors.items()}})
        if "epikt_calibrated" in predictors:
            metrics["paired_brier_delta_95"] = paired_brier_interval(
                labels[coverage], calibrated[coverage], predictors[strongest][coverage],
                baseline["learners"][coverage],
            )
    if supported.any():
        strata = {"short_history": length < 3, "established_history": length >= 3,
                  "single_kc": baseline["kc_count"] == 1, "multi_kc": baseline["kc_count"] > 1}
        metrics["strata"] = {}
        for name, mask in strata.items():
            mask = mask & supported
            if mask.any():
                metrics["strata"][name] = {"n": int(mask.sum()), "metrics": {
                    method: measure(labels[mask], values[mask]) for method, values in predictors.items()
                }}
    metrics["passes_scoring_gate"] = meets_scoring_gate(metrics)
    write_json(args.run / "test_metrics.json", metrics)
    print({key: metrics[key] for key in (
        "question_targets", "covered_targets", "question_auc", "question_acc", "passes_scoring_gate"
    )} | {"strongest_baseline": metrics.get("strongest_baseline")})


if __name__ == "__main__":
    main()
