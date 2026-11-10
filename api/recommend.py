"""Rule and EpiKT scoring feed the same deterministic teaching policy."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from collections.abc import Mapping
from math import exp, log
from pathlib import Path
from threading import Lock

from api.catalog import TOPIC_NAMES, Item
from api.policy import Candidate, choose_next
from kt.release import require_release_report
from kt.scoring import EpiKTScorer, GradedAttempt, load_calibration, question_mapping_issue
from kt.train import read_json

TOPICS = tuple(TOPIC_NAMES)
PRIOR = {1: 0.76, 2: 0.64, 3: 0.51}
ACTION = {1: "foundation", 2: "consolidate", 3: "advance"}


def rule_scores(history: list[tuple[Item, bool]], candidates: list[Item]) -> dict[int, float]:
    scores = {}
    for item in candidates:
        recent = [correct for past, correct in history if past.topic == item.topic][-5:]
        scores[item.id] = (3 * PRIOR[item.level] + sum(recent)) / (3 + len(recent))
    return scores


def choose_item(candidates: list[Item], scores: dict[int, float], can_advance: bool) -> int | None:
    options = [Candidate(item.id, ACTION[item.level], scores[item.id]) for item in candidates]
    selected = choose_next(options, can_advance=can_advance)
    if selected:
        return selected.item_id
    return None


class CalibratedScorer:
    """Keep one in-flight forward per process and fail fast under contention."""

    def __init__(self, run: Path, timeout: float = 0.8, *,
                 offline: bool = False, allow_smoke: bool = False):
        if allow_smoke and not offline:
            raise ValueError("Smoke checkpoints may only be scored offline.")
        config = read_json(run / "config.json")
        training = read_json(run / "training_metrics.json")
        checkpoint_id = training["checkpoint_sha256"]
        calibration = load_calibration(run, config, training)
        if not offline:
            require_release_report(run, config)
        self.model = EpiKTScorer(run, allow_smoke=allow_smoke)
        self.calibration = calibration
        self.supported = set(calibration["source_questions_with_training_support"])
        self.version = checkpoint_id[:12]
        self.timeout = timeout
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.busy = Lock()

    def supports(self, item: Item) -> bool:
        return question_mapping_issue(
            item.source_question_id, item.source_kcs, self.model.mapping["questions"],
            self.model.question_kcs, self.supported,
        ) is None

    def score(self, history: list[tuple[Item, bool]], candidates: list[Item]) -> dict[int, float]:
        if not self.busy.acquire(blocking=False):
            raise TimeoutError("EpiKT is busy.")
        try:
            task = self.worker.submit(
                self.model.score,
                [GradedAttempt(item.source_question_id, int(correct)) for item, correct in history],
                [item.source_question_id for item in candidates],
            )
        except BaseException:
            self.busy.release()
            raise
        task.add_done_callback(lambda _: self.busy.release())
        raw = task.result(timeout=self.timeout)
        return {item.id: self._calibrate(raw[item.source_question_id]) for item in candidates}

    def _calibrate(self, probability: float) -> float:
        # pyKT late_mean rounds the KC average before fitting calibration.
        probability = round(probability, 4)
        probability = min(1 - 1e-6, max(1e-6, probability))
        logit = log(probability / (1 - probability))
        value = self.calibration["coefficient"] * logit + self.calibration["intercept"]
        return 1 / (1 + exp(-min(60, max(-60, value))))

    def close(self):
        self.worker.shutdown(wait=True, cancel_futures=True)


class Recommender:
    def __init__(self, scorer=None, unavailable: str = "model_unconfigured"):
        self.scorer = scorer
        self.unavailable = unavailable

    def decide(self, items: Mapping[int, Item], history: list[tuple[Item, bool]]) -> dict | None:
        seen = {item.id for item, _ in history}
        remaining = [item for item in items.values() if item.id not in seen]
        if not remaining:
            return None
        if len(history) < 3:
            item = min((item for item in remaining if item.level < 3),
                       key=lambda item: (item.level, item.id), default=None)
            if item is None:
                return None
            return {"item_id": item.id, "source": "rule", "reason": "cold_start", "trace": {}}

        current, last_correct = history[-1]
        current_topic = TOPICS.index(current.topic)
        recent = [correct for item, correct in history[-5:] if item.topic == current.topic]
        can_advance = sum(recent) >= 2
        candidates = [
            item for item in remaining
            if (item.level < 3 or can_advance)
            and (last_correct or item.topic == current.topic
                 or (item.level == 1 and TOPICS.index(item.topic) <= current_topic))
        ]
        if not candidates:
            candidates = [item for item in remaining if item.level < 3 or can_advance]
        if not candidates:
            return None
        candidates = sorted(candidates, key=lambda item: (item.topic != current.topic, item.id))[:12]
        rule = rule_scores(history, candidates)
        rule_item = choose_item(candidates, rule, can_advance)
        reason = self.unavailable
        scorer = self.scorer
        compatible = scorer and all(scorer.supports(item) for item, _ in history)
        supported = [item for item in candidates if compatible and scorer.supports(item)]
        # Compare the two score sources over exactly the same authorized candidates.
        if supported and len(supported) == len(candidates):
            try:
                scores = scorer.score(history, candidates)
                decision = choose_item(candidates, scores, can_advance)
                if decision is not None:
                    return {
                        "item_id": decision, "source": "epikt", "reason": ACTION[items[decision].level],
                        "trace": {"model_version": scorer.version,
                                  "candidate_ids": [item.id for item in candidates],
                                  "epikt_scores": scores, "rule_scores": rule,
                                  "rule_item_id": rule_item},
                    }
                reason = "model_no_eligible_item"
            except TimeoutError:
                reason = "model_timeout"
            except (KeyError, RuntimeError, TypeError, ValueError):
                reason = "model_error"
        elif scorer:
            reason = "unmapped_catalog_or_history"
        if rule_item is None:
            return None
        return {"item_id": rule_item, "source": "rule", "reason": reason,
                "trace": {"candidate_ids": list(rule), "rule_scores": rule, "rule_item_id": rule_item}}
