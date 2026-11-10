import unittest

from api.policy import Candidate, choose_next


class PolicyTest(unittest.TestCase):
    def test_rule_and_model_probabilities_can_choose_different_items(self):
        base = Candidate(1, "foundation", 0.76)
        self.assertEqual(
            choose_next([base, Candidate(2, "consolidate", 0.43)], can_advance=False), base
        )
        consolidate = Candidate(2, "consolidate", 0.64)
        self.assertEqual(choose_next([base, consolidate], can_advance=False), consolidate)

    def test_prerequisite_and_bad_probability(self):
        self.assertIsNone(choose_next([Candidate(1, "advance", 0.75)], can_advance=False))
        with self.assertRaises(ValueError):
            choose_next([Candidate(1, "advance", float("nan"))], can_advance=True)
