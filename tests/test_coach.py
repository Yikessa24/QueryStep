import asyncio
import importlib.util
import json
import unittest

from course_content.knowledge_index import lexical_terms, load_lessons


class CurriculumTest(unittest.TestCase):
    def test_source_and_sql_tokens(self):
        chunks = load_lessons()
        self.assertIn("having/strict-inclusive", chunks)
        self.assertIn("where-after-join/predicate-placement", chunks)
        self.assertEqual(lexical_terms("COUNT(*) >= 2"), ["sqlcountstar", "sqlgte", "2"])
        self.assertEqual(lexical_terms("COUNT(*) > 2"), ["sqlcountstar", "sqlgt", "2"])
        self.assertTrue({"select", "where", "conditions", "distinct", "aggregate", "set_ops", "join", "subquery"}
                        <= {chunk["topic"] for chunk in chunks.values()})


class SamplePlanner:
    async def reply_json(self, messages, *args, **kwargs):
        state = json.loads(messages[-1]["content"])
        experiments = [item for item in state["evidence"] if "same" in item]
        action = {"kind": "experiment", "experiment": "join_filter", "scenario": state["default_scenario"]}
        if state["topic"] == "aggregate":
            action.update(experiment="having_boundary", threshold=2)
        if not experiments:
            return self.plan("continue", [action, {"kind": "search", "query": state["question"]}])
        if experiments[-1]["same"]:
            return self.plan("continue", [{**action, "scenario": "boundary"}])
        citations = [item["id"] for item in state["evidence"] if "title" in item][:1]
        return self.plan("hint", [], [*citations, experiments[-1]["id"]])

    @staticmethod
    def plan(finish, actions, references=()):
        return {"content": "```json\n" + json.dumps({"finish": finish, "actions": actions,
                                                      "references": list(references)}) + "\n```"}


@unittest.skipUnless(importlib.util.find_spec("langgraph") and importlib.util.find_spec("mcp"),
                     "Install diagnostics extras.")
class CoachTest(unittest.IsolatedAsyncioTestCase):
    async def test_replans_only_when_first_observation_has_no_boundary(self):
        from sql_lab.client import open_lab
        from sql_lab.contracts import COACH_SCOPE
        from tutor.coach import Coach

        async with open_lab(COACH_SCOPE) as lab:
            coach = Coach(SamplePlanner(), "test", lab)
            questions = {"join": "LEFT JOIN 把右表条件移到 WHERE 为什么会丢行？",
                         "aggregate": "HAVING COUNT(*) > 2 和 >= 2 为什么可能一样？"}
            for topic, question in questions.items():
                for initial, expected in (("matching", [True, False]), ("boundary", [False])):
                    with self.subTest(topic=topic, initial=initial):
                        result = await coach.run(question, topic, scenario=initial)
                        self.assertEqual(result["status"], "hint")
                        self.assertEqual([event["same"] for event in result["trace"] if "same" in event], expected)
                        self.assertEqual(result["model_calls"], len(expected) + 1)
                        self.assertEqual(result["tool_calls"], len(expected) + 1)
                        observation = [row["data"] for row in result["evidence"] if row["kind"] == "experiment"][-1]
                        self.assertEqual(observation["removed_keys"], ["2", "3"] if topic == "join" else ["C"])

    async def test_guards_tool_parameters_and_forged_references(self):
        from sql_lab.client import open_lab
        from sql_lab.contracts import COACH_EXPERIMENT_TOOL, COACH_SCOPE
        from sql_lab.executor import LabError
        from tutor.coach import Coach

        class Forgery:
            async def reply_json(self, *args, **kwargs):
                return SamplePlanner.plan("hint", [], ["outside-run"])

        async with open_lab(COACH_SCOPE) as lab:
            with self.assertRaisesRegex(LabError, "invalid_parameters"):
                await lab.call("coach", COACH_EXPERIMENT_TOOL,
                               {"experiment": "join_filter", "scenario": "matching", "sql": "SELECT 1"})
            result = await Coach(Forgery(), "test", lab).run("解释 LEFT JOIN", "join")
            self.assertEqual((result["reason"], result["citations"], result["tool_calls"]), ("invalid_reference", [], 0))

    async def test_having_runs_parameterized_boundaries_and_retains_threshold(self):
        from sql_lab.client import open_lab
        from sql_lab.contracts import COACH_EXPERIMENT_TOOL, COACH_SCOPE
        from tutor.coach import Coach

        async with open_lab(COACH_SCOPE) as lab:
            for threshold in (0, 1, 8, 50):
                found = await lab.call("coach", COACH_EXPERIMENT_TOOL, {
                    "experiment": "having_boundary", "scenario": "boundary", "threshold": threshold,
                })
                self.assertEqual(found["removed_keys"], ["C"] if threshold else [])
                self.assertEqual(found["same"], threshold == 0)
            result = await Coach(SamplePlanner(), "test", lab).run("HAVING COUNT(*) >= 8 和 > 8", "aggregate")
            self.assertEqual([entry["arguments"]["threshold"] for entry in result["trace"]
                              if entry.get("tool") == COACH_EXPERIMENT_TOOL], [8, 8])

    async def test_deadline_preserves_already_displayed_evidence(self):
        from sql_lab.contracts import KNOWLEDGE_TOOL
        from tutor.coach import Coach

        class SlowPlanner:
            async def reply_json(self, messages, *args, **kwargs):
                if json.loads(messages[-1]["content"])["evidence"]:
                    await asyncio.sleep(10)
                return SamplePlanner.plan("continue", [{"kind": "search", "query": "LEFT JOIN"}])

        class Lab:
            async def call(self, role, name, arguments, **kwargs):
                assert name == KNOWLEDGE_TOOL
                return {"cards": [next(iter(load_lessons().values()))], "mode": "hybrid",
                        "corpus": "test", "elapsed_ms": 1}

        result = await Coach(SlowPlanner(), "test", Lab(), budget=0.10).run("LEFT JOIN", "join")
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(result["citations"], ["e1"])
