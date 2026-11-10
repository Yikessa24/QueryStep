"""Training-fold item priors, recent KC accuracy and no-forgetting BKT."""

import csv
from collections import defaultdict, deque
from pathlib import Path
from statistics import fmean

import numpy as np
from scipy.optimize import minimize

from evals.calibrate_kt import training_counts
from kt.release import BASELINE_NAMES

INITIAL = (0.4, 0.2, 0.25, 0.15)
BOUNDS = ((0.001, 0.999), (0.001, 0.8), (0.01, 0.45), (0.01, 0.45))


def bkt_update(mastered, correct, params):
    _, learn, guess, slip = params
    correct_chance = mastered * (1 - slip) + (1 - mastered) * guess
    observed = np.where(correct, correct_chance, 1 - correct_chance)
    joint = mastered * np.where(correct, 1 - slip, slip)
    posterior = joint / observed
    return posterior + (1 - posterior) * learn, observed


def fit_bkt(sequences: list[list[int]]) -> tuple[float, ...]:
    answers = np.full((len(sequences), max(map(len, sequences))), -1, dtype=np.int8)
    for index, sequence in enumerate(sequences):
        answers[index, :len(sequence)] = sequence

    def loss(params):
        state = np.full(len(sequences), params[0])
        total = 0.0
        for column in answers.T:
            valid = column >= 0
            state, likelihood = bkt_update(state, column == 1, params)
            total -= np.log(likelihood[valid]).sum()
        return total

    fit = minimize(loss, INITIAL, method="L-BFGS-B", bounds=BOUNDS)
    if not fit.success or not np.isfinite(fit.fun):
        raise ValueError("BKT fitting failed on the training fold.")
    return tuple(map(float, fit.x))


def kc_training_sequences(data: Path, validation_fold: int) -> dict[int, list[list[int]]]:
    by_kc = defaultdict(list)
    with (data / "train_valid.csv").open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            fold = int(row["fold"])
            if fold < 0:
                raise ValueError("Held-out data must not be used to fit KC baselines.")
            if fold == validation_fold:
                continue
            learner = defaultdict(list)
            for kc, label in zip(row["concepts"].split(","), row["responses"].split(","), strict=True):
                learner[int(kc)].append(int(label))
            for kc, sequence in learner.items():
                by_kc[kc].append(sequence)
    return by_kc


def compare_windows(data: Path, validation_fold: int, results: dict) -> dict:
    counts, positives = training_counts(data, validation_fold)
    sequences = kc_training_sequences(data, validation_fold)
    bkt = {kc: fit_bkt(rows) for kc, rows in sequences.items()}
    kc_prior = {kc: (1 + sum(map(sum, rows))) / (2 + sum(map(len, rows)))
                for kc, rows in sequences.items()}

    columns = ("raw_sequence_indices", "raw_positions", "raw_question_ids",
               "raw_target_questions", "raw_target_concepts", "raw_labels")
    raw_targets = iter(zip(*(results[key] for key in columns), strict=True))
    grouped = defaultdict(dict)
    metadata = {}
    keys = ("questions", "concepts", "responses", "selectmasks", "qidxs")
    with (data / "test_question_window_sequences.csv").open(encoding="utf-8", newline="") as source:
        for row_number, row in enumerate(csv.DictReader(source)):
            if int(row["fold"]) != -1:
                raise ValueError("Only held-out windows may enter the test report.")
            recent = defaultdict(lambda: deque(maxlen=5))
            states = {}
            history = set()
            for position, (question, kc, label, mask, group) in enumerate(zip(
                    *(map(int, row[key].split(",")) for key in keys), strict=True)):
                if question < 0:
                    break
                params = bkt.get(kc)
                if mask == 1:
                    expected = (row_number, position, group, question, kc, label)
                    if group in history or next(raw_targets, None) != expected:
                        raise ValueError("Baseline target differs from the causal pyKT window.")
                    signature = (row["uid"], question, len(history), label)
                    if metadata.setdefault(group, signature) != signature or kc in grouped[group]:
                        raise ValueError("A question group contains inconsistent targets or repeated KCs.")
                    item_prior = (positives[question] + 1) / (counts[question] + 2)
                    kc_recent = recent[kc]
                    prior = kc_prior.get(kc, item_prior)
                    recent_score = (3 * prior + sum(kc_recent)) / (3 + len(kc_recent))
                    if params:
                        initial, _, guess, slip = params
                        current = states.get(kc, initial)
                        bkt_score = current * (1 - slip) + (1 - current) * guess
                    else:
                        bkt_score = item_prior
                    grouped[group][kc] = (item_prior, recent_score, bkt_score)
                recent[kc].append(label)
                if params:
                    state, _ = bkt_update(states.get(kc, params[0]), label == 1, params)
                    states[kc] = float(state)
                history.add(group)
    if next(raw_targets, None) is not None or set(grouped) != set(results["question_ids"]):
        raise ValueError("Baseline groups differ from pyKT question targets.")

    aligned = defaultdict(list)
    for group, label in zip(results["question_ids"], results["labels"], strict=True):
        rows = grouped[group]
        uid, question, size, raw_label = metadata[group]
        if raw_label != label:
            raise ValueError("The fused question label differs from the window label.")
        aligned["learners"].append(uid)
        aligned["history_length"].append(size)
        aligned["kc_count"].append(len(rows))
        aligned["supported"].append(bool(counts[question]) and all(kc in bkt for kc in rows))
        for name, scores in zip(BASELINE_NAMES, zip(*rows.values(), strict=True), strict=True):
            aligned[name].append(fmean(scores))
    return {name: np.asarray(values) for name, values in aligned.items()}
