"""Check real model causality and online aggregation using a local smoke run."""

from itertools import groupby
from importlib.util import find_spec
import csv
from pathlib import Path
from shutil import copytree
from statistics import fmean
from tempfile import TemporaryDirectory
import unittest

from data_pipeline.preprocess import sha256, write_json
from evals.question_window import _QuestionBatches
from kt.pykt_source import ROOT, epikt_analysis
from kt.scoring import EpiKTScorer, GradedAttempt
from kt.train import DEFAULT_DATA, read_json

RUN = ROOT / "artifacts/epikt-smoke"


class EpiKTScoringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
        except ImportError:
            raise unittest.SkipTest("Install the kt dependencies first.")
        if find_spec("einops") is None:
            raise unittest.SkipTest("Install the kt dependencies first.")
        if not (RUN / "training_metrics.json").is_file():
            raise unittest.SkipTest("Train the local smoke checkpoint first.")
        torch.set_num_threads(2)
        cls.torch = torch
        cls.scorer = EpiKTScorer(RUN, allow_smoke=True)
        question_kcs = cls.scorer.question_kcs
        cls.target = int(next(question for question, kcs in question_kcs.items() if len(kcs) > 1))
        cls.history = [GradedAttempt(int(question), i % 2) for i, question
                       in enumerate(q for q in question_kcs if q != str(cls.target))][:3]

    def tensor(self, history, target_kc, label, suffix):
        lookup = self.scorer.mapping
        triples = [
            (lookup["concepts"][str(kc)], event.correct,
             lookup["questions"][str(event.question_id)])
            for event in history
            for kc in self.scorer.question_kcs[str(event.question_id)]
        ]
        triples.append((lookup["concepts"][str(target_kc)], label,
                        lookup["questions"][str(self.target)]))
        target_index = len(triples) - 1
        triples.extend(suffix)
        return self.torch.tensor([triples], dtype=self.torch.long, device=self.scorer.device), target_index

    def direct(self, history, target_kc, label=0, suffix=()):
        data, position = self.tensor(history, target_kc, label, suffix)
        with self.torch.inference_mode():
            preds, _ = self.scorer.model(data[:, :, 0], data[:, :, 1], data[:, :, 2])
        return float(preds[0, position])

    def test_placeholder_future_padding_and_aggregation(self):
        kcs = self.scorer.question_kcs[str(self.target)]
        for count in (1, 2, 3):
            history = self.history[:count]
            reference = []
            for kc in kcs:
                baseline = self.direct(history, kc)
                reference.append(baseline)
                self.assertAlmostEqual(self.direct(history, kc, label=1), baseline, delta=1e-5)
                self.assertAlmostEqual(
                    self.direct(history, kc, suffix=((0, 1, 0), (0, 0, 0))), baseline, delta=1e-5
                )
            actual = self.scorer.score(history, [self.target])[self.target]
            self.assertAlmostEqual(actual, sum(reference) / len(reference), delta=1e-5)

    def test_unknown_id_is_not_silently_scored(self):
        with self.assertRaises(KeyError):
            self.scorer.score(self.history, [-1])

    def test_online_scoring_matches_pykt_heldout_question_windows(self):
        from pykt.datasets.data_loader import KTDataset

        inverse = {str(mapped): int(source) for source, mapped in
                   self.scorer.mapping["questions"].items()}
        with (DEFAULT_DATA / "test_question_window_sequences.csv").open(newline="") as source:
            reader = csv.DictReader(source)
            _, windows = next(groupby(reader, key=lambda row: row["uid"]))
            rows = list(windows)
            fields = reader.fieldnames
        with TemporaryDirectory() as temp:
            filename = Path(temp) / "heldout_sample.csv"
            with filename.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            dataset = KTDataset(str(filename), ["questions", "concepts"], {-1}, qtest=True)
            loader = self.torch.utils.data.DataLoader(dataset, batch_size=8)
            offline = epikt_analysis().evaluate_question_window_late_mean(
                self.scorer.model, _QuestionBatches(loader), self.scorer.device
            )

        cases = {}
        for row in rows:
            events = []
            columns = ("questions", "responses", "is_repeat", "selectmasks", "qidxs")
            for question, response, repeat, selected, qidx in zip(
                    *(row[key].split(",") for key in columns), strict=True):
                if question == "-1":
                    break
                source_question = inverse[question]
                if selected == "1":
                    case = (events.copy(), source_question)
                    self.assertEqual(cases.setdefault(int(qidx), case), case)
                if repeat == "0":
                    events.append(GradedAttempt(source_question, int(response)))
        online = {group: self.scorer.score(events, [target])[target]
                  for group, (events, target) in cases.items()}
        self.assertGreater(len(online), 1)
        self.assertEqual(set(online), set(offline["question_ids"]))
        raw_by_group = {}
        for group, score in zip(offline["raw_question_ids"], offline["raw_final_scores"], strict=True):
            raw_by_group.setdefault(group, []).append(float(score))
        for group, score in zip(offline["question_ids"], offline["final_scores"], strict=True):
            raw = fmean(raw_by_group[group])
            self.assertAlmostEqual(online[group], raw, delta=1e-5)
            self.assertEqual(round(raw, 4), score)

    def test_over_window_scoring_keeps_only_whole_confirmed_events(self):
        history = self.history * self.scorer.maxlen
        sizes = [len(self.scorer.question_kcs[str(event.question_id)]) for event in history]
        total = sum(sizes)
        first = 0
        while total >= self.scorer.maxlen:
            total -= sizes[first]
            first += 1
        actual = self.scorer.score(history, [self.target])[self.target]
        expected = fmean(self.direct(history[first:], kc)
                         for kc in self.scorer.question_kcs[str(self.target)])
        self.assertAlmostEqual(actual, expected, delta=1e-5)

    def test_smoke_weights_require_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "smoke checkpoint"):
            EpiKTScorer(RUN)

    def test_rejects_config_that_changed_after_training(self):
        with TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            copytree(RUN, run)
            config_path = run / "config.json"
            metrics_path = run / "training_metrics.json"
            write_json(metrics_path, {**read_json(metrics_path), "config_sha256": sha256(config_path)})
            config = read_json(config_path)
            config["data_config"]["maxlen"] -= 1
            write_json(config_path, config)
            with self.assertRaisesRegex(ValueError, "configuration differs"):
                EpiKTScorer(run, allow_smoke=True)


if __name__ == "__main__":
    unittest.main()
