"""Online release criteria shared by evaluation and service startup."""

from pathlib import Path

from data_pipeline.preprocess import sha256
from kt.train import read_json

BASELINE_NAMES = ("question_prior", "recent_kc", "bkt")
GATE_VERSION = 2


def meets_scoring_gate(report: dict) -> bool:
    if (report.get("scoring_gate_version") != GATE_VERSION or report.get("smoke") is not False
            or report.get("protocol") != "pykt_question_window_late_mean"
            or not 0 < report.get("covered_targets", 0) <= report["question_targets"]):
        return False
    metrics = report.get("common_coverage", {})
    if not metrics.get("epikt_calibrated") or not all(name in metrics for name in BASELINE_NAMES):
        return False
    calibrated = metrics["epikt_calibrated"]
    scores = [metrics[name]["brier"] for name in BASELINE_NAMES]
    return (all(0 <= score <= 1 for score in scores)
            and 0 <= calibrated["brier"] <= min(scores)
            and 0 <= calibrated["ece"] <= 0.08)


def require_release_report(run: Path, config: dict) -> None:
    report = read_json(run / "test_metrics.json")
    if (report.get("passes_scoring_gate") is not True
            or report["fold"] != config["params"]["fold"]
            or report["data_manifest_sha256"] != config["data_manifest_sha256"]
            or report["calibration_sha256"] != sha256(run / "calibration.json")
            or not meets_scoring_gate(report)):
        raise ValueError("Run has not passed the calibrated held-out scoring gate.")
