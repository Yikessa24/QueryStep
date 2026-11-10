"""Regression checks for matching held-out targets and release criteria."""

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from evals.kt_baselines import bkt_update, compare_windows, fit_bkt, kc_training_sequences
from kt.release import GATE_VERSION, meets_scoring_gate


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


class KTBaselineTest(unittest.TestCase):
    def test_bkt_updates_only_after_observing_answer(self):
        params = (0.4, 0.2, 0.25, 0.15)
        correct, likelihood = bkt_update(params[0], True, params)
        wrong, _ = bkt_update(params[0], False, params)
        self.assertAlmostEqual(likelihood, 0.49)
        self.assertAlmostEqual(correct, 0.2 + 0.8 * 0.34 / 0.49)
        self.assertGreater(correct, wrong)
        fit = fit_bkt([[0, 1, 1], [0, 0, 1], [1, 1], [1, 0, 1]])
        self.assertTrue(all(0 < probability < 1 for probability in fit))

    def test_matching_targets_never_use_current_result_or_validation_rows(self):
        with TemporaryDirectory() as directory:
            data = Path(directory)
            write_rows(data / "train_valid.csv", [
                {"fold": 1, "questions": "0,1,2", "concepts": "0,1,0",
                 "responses": "1,0,0", "is_repeat": "0,0,0"},
                {"fold": 0, "questions": "1,2", "concepts": "1,0",
                 "responses": "1,1", "is_repeat": "0,0"},
            ])
            self.assertEqual(kc_training_sequences(data, 0), {0: [[1, 0]], 1: [[0]]})

            def scored(label):
                write_rows(data / "test_question_window_sequences.csv", [
                    {"fold": -1, "uid": "held-out", "questions": "0,1,2",
                     "concepts": "0,0,0", "responses": f"1,{label},1",
                     "selectmasks": "-1,1,1", "qidxs": "0,1,2"},
                    {"fold": -1, "uid": "held-out", "questions": "0,1",
                     "concepts": "0,1", "responses": f"1,{label}",
                     "selectmasks": "-1,1", "qidxs": "0,1"},
                ])
                result = {"raw_sequence_indices": [0, 0, 1], "raw_positions": [1, 2, 1],
                          "raw_question_ids": [1, 2, 1], "raw_target_questions": [1, 2, 1],
                          "raw_target_concepts": [0, 0, 1], "raw_labels": [label, 1, label],
                          "question_ids": [1, 2], "labels": [label, 1]}
                with patch("evals.kt_baselines.fit_bkt", return_value=(0.4, 0.2, 0.25, 0.15)):
                    return compare_windows(data, 0, result)

            right, wrong = scored(1), scored(0)
            self.assertEqual(right["kc_count"].tolist(), [2, 1])
            self.assertEqual(right["history_length"].tolist(), [1, 2])
            self.assertEqual(right["supported"].tolist(), [True, True])
            for method in ("question_prior", "recent_kc", "bkt"):
                self.assertEqual(right[method][0], wrong[method][0])
            self.assertGreater(right["recent_kc"][1], wrong["recent_kc"][1])
            self.assertGreater(right["bkt"][1], wrong["bkt"][1])

    def test_gate_requires_all_comparators_and_beats_the_strongest(self):
        report = {
            "scoring_gate_version": GATE_VERSION, "smoke": False,
            "protocol": "pykt_question_window_late_mean", "covered_targets": 100,
            "question_targets": 100, "common_coverage": {
                "question_prior": {"brier": 0.20}, "recent_kc": {"brier": 0.18},
                "bkt": {"brier": 0.17}, "epikt_calibrated": {"brier": 0.175, "ece": 0.05},
            },
        }
        self.assertFalse(meets_scoring_gate(report))
        report["common_coverage"]["epikt_calibrated"]["brier"] = 0.17
        self.assertTrue(meets_scoring_gate(report))
        self.assertFalse(meets_scoring_gate({**report, "smoke": True}))
        self.assertFalse(meets_scoring_gate({**report, "scoring_gate_version": 1}))
        del report["common_coverage"]["bkt"]
        self.assertFalse(meets_scoring_gate(report))
