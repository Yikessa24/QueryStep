"""Convert DBE-KT22 V1 into the six-line raw sequence format used by pyKT."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import csv
import io
from pathlib import Path
import re
from zipfile import ZipFile

_ONE_MILLISECOND = timedelta(milliseconds=1)


@dataclass(frozen=True)
class Attempt:
    learner_id: int
    question_id: int
    kc_ids: tuple[int, ...]
    correct: int
    started_ms: int
    ended_ms: int


def _read_csv(archive: ZipFile, name: str) -> list[dict[str, str]]:
    with io.TextIOWrapper(archive.open(name), encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _index(rows: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    index = {int(row["id"]): row for row in rows}
    if len(index) != len(rows):
        raise ValueError("DBE-KT22 contains duplicate primary keys.")
    return index


def _boolean(value: str) -> bool:
    if value not in {"true", "false"}:
        raise ValueError(f"Invalid DBE-KT22 boolean: {value!r}")
    return value == "true"


def _millis(value: str) -> int:
    time = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f %z")
    elapsed = time - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return elapsed // _ONE_MILLISECOND


def load_attempts(
    archive_path: Path, *, kc_scope: set[int] | None, exclude_external_images: bool
) -> tuple[list[Attempt], dict]:
    with ZipFile(archive_path) as archive:
        questions = _index(_read_csv(archive, "Questions.csv"))
        choices = _index(_read_csv(archive, "Question_Choices.csv"))
        concepts = _index(_read_csv(archive, "KCs.csv"))
        links = _read_csv(archive, "Question_KC_Relationships.csv")
        transactions = _read_csv(archive, "Transaction.csv")

    if kc_scope is not None and not kc_scope <= concepts.keys():
        raise ValueError("The SQL scope includes unknown source KC IDs.")
    question_kcs = defaultdict(set)
    for row in links:
        question = int(row["question_id"])
        concept = int(row["knowledgecomponent_id"])
        if question not in questions or concept not in concepts:
            raise ValueError("Broken DBE-KT22 question/KC link.")
        question_kcs[question].add(concept)

    correct_choices = Counter()
    for row in choices.values():
        question = int(row["question_id"])
        if question not in questions:
            raise ValueError("Broken DBE-KT22 option/question link.")
        if _boolean(row["is_correct"]):
            correct_choices[question] += 1

    scoped = {
        question for question, row in questions.items()
        if (kc_scope is None or question_kcs[question] & kc_scope)
        and (
            not exclude_external_images
            or not re.search(r"<img\b", row["question_rich_text"], flags=re.I)
        )
    }
    for question in scoped:
        if not question_kcs[question] or correct_choices[question] != 1:
            raise ValueError(f"Question {question} needs KCs and exactly one correct option.")

    attempts = []
    counts = Counter()
    parsed = []
    transaction_ids = set()
    raw_learners = set()
    for row in transactions:
        transaction_id = int(row["id"])
        if transaction_id in transaction_ids:
            raise ValueError(f"Duplicate transaction ID: {transaction_id}.")
        transaction_ids.add(transaction_id)
        learner = int(row["student_id"])
        raw_learners.add(learner)
        question = int(row["question_id"])
        if question not in questions:
            counts["unknown_question"] += 1
        elif question not in scoped:
            counts["out_of_scope"] += 1
        else:
            parsed.append(
                (learner, _millis(row["end_time"]), _millis(row["start_time"]),
                 transaction_id, question, row)
            )

    seen = set()
    last_end = {}
    for learner, ended, started, _, question, row in sorted(parsed):
        pair = (learner, question)
        if pair in seen:
            counts["repeat"] += 1
            continue
        # Mark the earliest completed attempt before filtering. A later try
        # must not become the first attempt when the original used a hint.
        seen.add(pair)
        if _boolean(row["is_hidden"]):
            counts["hidden"] += 1
            continue
        if _boolean(row["hint_used"]):
            counts["hint_used"] += 1
            continue
        if ended <= started:
            counts["invalid_duration"] += 1
            continue
        option = choices.get(int(row["answer_choice_id"]))
        if option is None or int(option["question_id"]) != question:
            counts["invalid_choice"] += 1
            continue
        correct = _boolean(row["answer_state"])
        if correct != _boolean(option["is_correct"]):
            counts["answer_disagreement"] += 1
            continue
        if learner in last_end and started <= last_end[learner]:
            counts["overlap_or_equal_boundary"] += 1
            continue
        last_end[learner] = ended
        attempts.append(
            Attempt(learner, question, tuple(sorted(question_kcs[question])), int(correct),
                    started, ended)
        )

    return attempts, {
        "raw_attempts": len(transactions),
        "raw_learners": len(raw_learners),
        "raw_questions": len(questions),
        "raw_kcs": len(concepts),
        "scope_questions": len(scoped),
        "retained_attempts": len(attempts),
        "excluded_attempts_by_reason": dict(counts),
    }


def write_pykt_raw(path: Path, attempts: list[Attempt], min_length: int = 3) -> dict:
    learners = defaultdict(list)
    for attempt in attempts:
        learners[attempt.learner_id].append(attempt)

    retained_questions = set()
    retained_attempts = 0
    retained_learners = 0
    with path.open("w", encoding="utf-8") as output:
        for learner, history in sorted(learners.items()):
            if len(history) < min_length:
                continue
            retained_learners += 1
            retained_attempts += len(history)
            retained_questions.update(event.question_id for event in history)
            lines = (
                f"{learner},{len(history)}",
                ",".join(str(event.question_id) for event in history),
                ",".join("_".join(map(str, event.kc_ids)) for event in history),
                ",".join(str(event.correct) for event in history),
                ",".join(str(event.ended_ms) for event in history),
                ",".join(str(event.ended_ms - event.started_ms) for event in history),
            )
            output.write("\n".join(lines) + "\n")
    return {
        "learners": retained_learners,
        "attempts": retained_attempts,
        "questions": len(retained_questions),
    }
