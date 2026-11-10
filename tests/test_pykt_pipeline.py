"""Verify pyKT window and split invariants on the generated DBE-KT22 dataset."""

import csv
import unittest

from kt.train import DEFAULT_DATA, read_json


class PyKTArtifactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (DEFAULT_DATA / "manifest.json").is_file():
            raise unittest.SkipTest("Run python -m data_pipeline.preprocess first.")

    def test_learners_do_not_cross_holdout(self):
        with (DEFAULT_DATA / "train_valid.csv").open() as source:
            train_valid = list(csv.DictReader(source))
        with (DEFAULT_DATA / "test.csv").open() as source:
            test = list(csv.DictReader(source))
        training_users = {row["uid"] for row in train_valid}
        testing_users = {row["uid"] for row in test}
        self.assertEqual(len(training_users), len(train_valid))
        self.assertEqual(len(testing_users), len(test))
        self.assertFalse(training_users & testing_users)
        self.assertEqual({row["fold"] for row in train_valid}, set("01234"))
        self.assertEqual({row["fold"] for row in test}, {"-1"})

    def test_raw_history_does_not_overlap(self):
        lines = (DEFAULT_DATA / "data.txt").read_text().splitlines()
        for index in range(0, len(lines), 6):
            count = int(lines[index].split(",")[1])
            fields = [row.split(",") for row in lines[index + 1:index + 6]]
            self.assertTrue(all(len(field) == count for field in fields))
            self.assertEqual(len(set(fields[0])), count)
            ends = list(map(int, fields[3]))
            durations = list(map(int, fields[4]))
            self.assertTrue(all(duration > 0 for duration in durations))
            self.assertTrue(all(previous < end - duration for previous, end, duration
                                in zip(ends, ends[1:], durations[1:])))

    def test_target_kcs_share_only_prior_question_history(self):
        maxlen = read_json(DEFAULT_DATA / "manifest.json")["maxlen"]
        for name in ("train_valid_question_window_sequences.csv",
                     "test_question_window_sequences.csv"):
            with (DEFAULT_DATA / name).open() as source:
                for row in csv.DictReader(source):
                    qidx = row["qidxs"].split(",")
                    mask = row["selectmasks"].split(",")
                    self.assertEqual(len(qidx), maxlen)
                    self.assertEqual(len(mask), maxlen)
                    seen = set()
                    for index, (question, selected) in enumerate(zip(qidx, mask)):
                        if selected == "1":
                            if index == 0 or question in seen:
                                self.fail(f"Invalid target history in {name}")
                        seen.add(question)


if __name__ == "__main__":
    unittest.main()
