"""Regressions for targeted course evidence and its coaching integration."""

import importlib.util
import json
import unittest

from course_content.evidence_retrieval import CONCEPTS, retrieve_evidence, split_concepts
from course_content.knowledge_index import load_lessons


QUESTION = "外连接后，没下单的顾客还在吗？COUNT(*) 会把那一行算进去吗？"


class MissingEvidenceIndex:
    def __init__(self, missing_forever=False):
        self.missing_forever = missing_forever
        self.cards = load_lessons()

    def search(self, query, topic, top_k, mode):
        ids = ["left-join/preserves-left", "where-after-join/predicate-placement"]
        if query == CONCEPTS["count_star"].cue and not self.missing_forever:
            ids = ["count/row-count"]
        return {"cards": [self.cards[key] for key in ids], "mode": mode,
                "corpus": "test-corpus", "elapsed_ms": 1.0}


class EvidenceRetrievalTest(unittest.TestCase):
    def test_retry_targets_only_the_missing_claim(self):
        result = retrieve_evidence(MissingEvidenceIndex(), QUESTION, "join")
        self.assertEqual([step["goal"] for step in result["passes"]],
                         ["left_join_unmatched", "count_star", "count_star"])
        self.assertEqual([step["retry"] for step in result["passes"]], [False, False, True])
        self.assertEqual(sum(step["limit"] for step in result["passes"]), 18)
        self.assertEqual([item["card_id"] for item in result["coverage"]],
                         ["left-join/preserves-left", "count/row-count"])
        self.assertLessEqual(len(result["cards"]), 3)

    def test_missing_remains_visible_when_retry_fails(self):
        result = retrieve_evidence(MissingEvidenceIndex(missing_forever=True), QUESTION, "join")
        self.assertEqual(result["coverage"][1]["card_id"], None)
        self.assertEqual(len(result["passes"]), 3)

    def test_single_or_out_of_scope_question_is_not_split(self):
        self.assertFalse(split_concepts("LEFT JOIN 是什么意思？"))
        self.assertFalse(split_concepts("MySQL JSON_TABLE 里的 COUNT(*) 和 LEFT JOIN 怎么用？"))
        result = retrieve_evidence(MissingEvidenceIndex(), "LEFT JOIN 是什么意思？", "join")
        self.assertEqual(len(result["passes"]), 1)


@unittest.skipUnless(importlib.util.find_spec("langgraph") and importlib.util.find_spec("mcp"),
                     "Install diagnostics extras.")
class CoachingEvidenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_final_citations_keep_both_verified_claims(self):
        from sql_lab.coach import search
        from sql_lab.contracts import KnowledgeRequest
        from tutor.coach import Coach

        class Lab:
            async def call(self, role, name, arguments, **options):
                return search(KnowledgeRequest.model_validate(arguments), MissingEvidenceIndex())

        class Planner:
            async def reply_json(self, messages, *options, **kwargs):
                state = json.loads(messages[-1]["content"])
                if not state["evidence"]:
                    plan = {"finish": "continue", "actions": [{"kind": "search", "query": state["question"]}]}
                else:
                    plan = {"finish": "hint", "references": ["e1"]}
                return {"content": json.dumps(plan)}

        published = []

        async def publish(event):
            published.append(event)

        result = await Coach(Planner(), "test", Lab()).run(QUESTION, "join", publish=publish)
        self.assertEqual(result["status"], "hint")
        cited = [item["data"]["id"] for item in result["evidence"] if item["id"] in result["citations"]]
        self.assertEqual(cited, ["left-join/preserves-left", "count/row-count"])
        self.assertTrue(next(event for event in published if event["type"] == "coverage")["retried"])
        self.assertEqual(result["tool_calls"], 1)
