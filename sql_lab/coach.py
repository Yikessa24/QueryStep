"""Stateless coach tools. Student and application state stay outside this process."""

from course_content.diagnosis_cards import search as reviewed_search
from course_content.sql_fixtures import JOIN_FIXTURE, JOIN_VARIANT, grouping
from sql_lab.executor import compare, execute, execute_fixture


def experiment(request):
    if request.experiment == "having_boundary":
        threshold = request.threshold
        boundary = request.scenario == "boundary"
        fixture_id = f"coach_having_{request.scenario}_{threshold}@1"
        counts = (threshold + 2, threshold + 1, threshold, threshold - 1) if boundary else (
            threshold + 2, threshold + 1, threshold + 1, threshold - 1
        )
        fixture = grouping(fixture_id, tuple(max(0, count) for count in counts))
        parameters = {"min_count": threshold}
        before = execute_fixture(fixture, "having_gte", parameters)
        after = execute_fixture(fixture, "having_gt", parameters)
    else:
        fixture_id = JOIN_FIXTURE if request.scenario == "boundary" else JOIN_VARIANT
        before_id, after_id = (("join_on", "join_where") if request.experiment == "join_filter"
                               else ("join_count_all", "join_count_matched"))
        before = execute(fixture_id, before_id, {})
        after = execute(fixture_id, after_id, {})
    fields = ("sql", "parameters", "columns", "rows", "row_count")
    difference = compare(before, after) if request.experiment != "join_count" else {}
    return {**request.model_dump(), "fixture": fixture_id,
            "before": {key: before[key] for key in fields}, "after": {key: after[key] for key in fields},
            "same": before["rows"] == after["rows"],
            **{key: difference.get(key, []) for key in ("removed_keys", "added_keys", "changed_keys")}}


def search(request, index):
    if index is not None:
        return index.search(request.query, request.topic, request.top_k, request.mode)
    cards = [{
        "id": row["id"], "title": row["title"], "parent": row["section"], "text": row["text"],
        "keywords": "", "experiment": None, "version": row["version"], "topic": row["topic"],
        "dialect": "sql", "source_url": row["url"], "source_section": row["section"], "reviewed_on": "",
    } for row in reviewed_search(request.query, request.topic, request.top_k) if row["match_score"] > 0]
    return {"cards": cards, "mode": "reviewed_cards", "corpus": "reviewed-cards-v1", "elapsed_ms": 0.0}
