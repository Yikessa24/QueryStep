import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from unittest.mock import AsyncMock, patch

from course_content.sql_fixtures import GROUPING_FIXTURE, GROUPING_VARIANT, JOIN_FIXTURE, JOIN_VARIANT
from tutor.diagnosis_intent import ExperimentIntent, route_experiment


class ToolModel:
    model = "synthetic-test"

    def __init__(self, *, fail_course=False):
        self.fail_course = fail_course
        self.filter_choices = []
        self.learning_notes = []

    def reply(self, messages, tools, timeout, **options):
        if tools and tools[0]["function"]["name"] == "retrieve_course_notes":
            if messages[-1]["role"] != "tool":
                context = json.loads(messages[1]["content"])["course_context"]
                self.learning_notes.append(context.get("confirmed_learning_notes", []))
                return self.call("retrieve_course_notes", "tutor-course", {})
            source = json.loads(messages[-1]["content"])
            return {"content": json.dumps({"action": "give_hint", "text": "先列出各组的计数。",
                                           "source_ids": [source["id"]]})}
        if not tools:
            data = json.loads(messages[-1]["content"])
            comparison = data["comparison"]
            rule = "join_on_where" if data["sources"][0]["topic"] == "join" else "strict_threshold"
            return {"content": json.dumps({"rule": rule,
                     "source_ids": [data["sources"][0]["id"]],
                     "observation_ids": [comparison["before_id"], comparison["after_id"]]})}
        context = json.loads(messages[1]["content"])
        self.learning_notes.append(context["confirmed_learning_notes"])
        if tools[0]["function"]["name"] == "search_course_notes":
            if self.fail_course:
                raise TimeoutError
            return self.call("search_course_notes", "course", {"query": "HAVING" if context["topic"] == "aggregate" else "LEFT JOIN"})
        if context["topic"] == "join":
            return self.call("run_example_query", "filter", {"query_id": "join_where"})
        observation = json.loads(messages[-1]["content"])["baseline_observation"]
        threshold = 1 if any(row[1] == 2 for row in observation["rows"]) else 2
        self.filter_choices.append(threshold)
        return self.call("run_example_query", "filter", {"query_id": "having_gt", "min_count": threshold})

    @staticmethod
    def call(name, call_id, args):
        return {"tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": name, "arguments": json.dumps(args),
        }}]}


class ExperimentIntentTest(unittest.TestCase):
    def test_only_one_supported_condition_is_executed(self):
        for question, expected in (
            ("运行 HAVING COUNT(*) ＞＝ ２。", ExperimentIntent("having_gte", 2)),
            ("严格大于 1，也就是 HAVING > 1。", ExperimentIntent("having_gt", 1)),
            ("至少 0 条。", ExperimentIntent("having_gte", 0)),
            ("用 COUNT(*) > 50。", ExperimentIntent("having_gt", 50)),
        ):
            with self.subTest(question=question):
                self.assertEqual(route_experiment(question, "aggregate"), expected)

    def test_invalid_and_ambiguous_requests_require_confirmation(self):
        for question in (
            "为什么少了一组？", "HAVING > 1 还是 HAVING >= 1？", "HAVING > 51", "HAVING >= -1",
            "HAVING > 1.5", "HAVING >= abc", "HAVING > 1 + 2", "HAVING > 1 AND score < 5",
            "HAVING SUM(amount) > 2", "HAVING COUNT(amount) > 2", "HAVING COUNT(*) = 2",
            "不要执行 HAVING > 1", "不大于 1", "HAVING >> 1", "HAVING COUNT(*) BETWEEN 1 AND 2",
        ):
            with self.subTest(question=question):
                self.assertIsNotNone(route_experiment(question, "aggregate").clarification)
        for question in ("条件位置会影响什么？", "请对比 INNER JOIN 的 ON 和 WHERE",
                         "用 status = 1 比较 ON 和 WHERE", "用 status != 'paid' 比较 ON 和 WHERE"):
            with self.subTest(question=question):
                self.assertIsNotNone(route_experiment(question, "join").clarification)


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "Install diagnostics dependencies.")
class DiagnosisGraphTest(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_explanation_selects_only_verified_evidence(self):
        from tutor.diagnosis import Diagnosis
        from tutor.diagnosis_explanation import explain

        evidence = await Diagnosis(None).run("用 HAVING >= 1 验证。", strategy="evidence_first")
        model = AsyncMock()
        model.reply_json.return_value = {"content": '{"focus":"threshold","source":1,"note":1}'}
        notes = [{"memory_id": "hidden-id", "summary": "我常忘记等号，email example@example.com"}]
        result = await explain(model, "test", "我不懂恰好等于的情况", evidence, notes)
        self.assertEqual((result["status"], result["focus"], result["memory_ids"]), ("ready", "threshold", ["hidden-id"]))
        self.assertIn("满足当前条件", result["text"])
        prompt = str(model.reply_json.call_args.args[0])
        self.assertNotIn("hidden-id", prompt)
        self.assertNotIn("example@example.com", prompt)
        self.assertIn("我常忘记等号", prompt)
        model.reply_json.assert_awaited_once()
        model.reply_json.return_value = {"content": '{"focus":"same_result","source":4,"note":1}'}
        invalid = await explain(model, "test", "用 HAVING >= 1", evidence, [])
        self.assertEqual((invalid["status"], invalid["reason"]), ("fallback", "invalid_response"))

    async def test_explanation_deadline_cancels_provider_request(self):
        from tutor.diagnosis import Diagnosis
        from tutor.diagnosis_explanation import explain

        evidence = await Diagnosis(None).run("用 HAVING > 1 验证。", strategy="evidence_first")
        cancelled = asyncio.Event()

        async def wait(*args, **kwargs):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

        model = AsyncMock()
        model.reply_json.side_effect = wait
        result = await explain(model, "test", "请解释", evidence, [], timeout=0.01)
        self.assertEqual(result["reason"], "timeout")
        self.assertTrue(cancelled.is_set())
        self.assertEqual(evidence["mode"], "full")

    async def test_evidence_first_uses_real_mcp_without_provider(self):
        from tutor.diagnosis import Diagnosis

        result = await Diagnosis(None).run("用 HAVING >= 1 验证。", fixture_id=GROUPING_FIXTURE,
                                           strategy="evidence_first")
        self.assertEqual((result["mode"], result["model_calls"]), ("full", 0))
        self.assertEqual(result["comparison"]["after_row_count"], 4)
        self.assertTrue(result["sources"])
        self.assertIn("4 组变为 4 组", result["summary"])
        self.assertEqual(result["trace"]["course"][0]["source"], "intent_router")

    async def test_evidence_first_never_replaces_an_ambiguous_query(self):
        from tutor.diagnosis import Diagnosis

        result = await Diagnosis(None).run("HAVING > 1 还是 >= 1？", strategy="evidence_first")
        self.assertEqual((result["mode"], result["model_calls"]), ("clarify", 0))
        self.assertEqual(result["trace"]["experiment"], [])
        self.assertTrue(result["sources"])

    async def test_real_mcp_observation_changes_next_tool_parameters(self):
        from tutor.diagnosis import Diagnosis

        model = ToolModel()
        started = set()
        both_started = asyncio.Event()

        async def progress(branch, status):
            if status == "running":
                started.add(branch)
                if len(started) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=2)

        engine = Diagnosis(model)
        first = await engine.run("测试聚合", progress=progress)
        second = await engine.run("测试聚合", fixture_id=GROUPING_VARIANT)
        self.assertEqual(model.filter_choices, [1, 2])
        self.assertEqual(first["mode"], "full")
        self.assertEqual(first["comparison"]["removed_keys"], ["D"])
        self.assertEqual(second["comparison"]["removed_keys"], ["B", "C", "D"])

    async def test_course_failure_retains_experiment_evidence(self):
        from tutor.diagnosis import Diagnosis

        result = await Diagnosis(ToolModel(fail_course=True)).run("测试聚合")
        self.assertEqual(result["mode"], "partial")
        self.assertEqual(result["branches"], {"course": "failed", "experiment": "ok"})
        self.assertEqual(result["comparison"]["after_row_count"], 3)

    async def test_join_diagnosis_and_memory_ablation(self):
        from tutor.diagnosis import Diagnosis

        model = ToolModel()
        engine = Diagnosis(model)
        memory = {"memory_id": "confirmed", "summary": "上次没有区分 ON 和 WHERE。"}
        for fixture, expected in ((JOIN_FIXTURE, ["2", "3"]), (JOIN_VARIANT, [])):
            model.learning_notes.clear()
            with_memory = await engine.run("条件位置对结果有什么影响？", fixture_id=fixture, memories=[memory])
            self.assertEqual(with_memory["comparison"]["removed_keys"], expected)
            self.assertEqual(with_memory["memory_ids"], [memory["memory_id"]])
            self.assertEqual(model.learning_notes, [[memory["summary"]], [memory["summary"]]])
            model.learning_notes.clear()
            without_memory = await engine.run("条件位置对结果有什么影响？", fixture_id=fixture)
            self.assertEqual(without_memory["comparison"]["removed_keys"], expected)
            self.assertEqual(model.learning_notes, [[], []])

    async def test_single_and_parallel_use_same_reviewed_tools(self):
        from tutor.diagnosis import Diagnosis

        engine = Diagnosis(ToolModel())
        results = [await engine.run("比较 HAVING 前后", strategy=strategy) for strategy in ("single", "parallel")]
        self.assertEqual([result["model_calls"] for result in results], [3, 3])
        self.assertEqual([result["comparison"]["removed_keys"] for result in results], [["D"], ["D"]])

    async def test_memory_recall_scope_matrix(self):
        from api.db import Attempt, Database, Decision, Learner
        from api.diagnostics import migrate, now
        from api.learning_memory import LearningMemory, active_memories
        from evals.diagnosis_cases import MEMORY_CASES

        with TemporaryDirectory() as temp:
            database = Database(f"sqlite:///{temp}/memories.db")
            self.addCleanup(database.engine.dispose)
            database.initialize()
            migrate(database.engine)
            migrate(database.engine)
            with database.transaction() as db:
                db.add_all([Learner(id="learner-a"), Learner(id="learner-b")])
                db.flush()
                db.add(Decision(id="decision", learner_id="learner-a", history_version=0,
                                catalog_version="test", item_id=75, source="rule", reason="test", trace={}))
                db.flush()
                db.add(Attempt(decision_id="decision", learner_id="learner-a", event_seq=1, item_id=75,
                               option=0, correct=False, idempotency_key="memory-matrix"))
            for case, remembered_topic, current_topic, owner, reader, deleted, expected in MEMORY_CASES:
                with self.subTest(case=case), database.transaction() as db:
                    record = LearningMemory(id=case, learner_id=owner, proposal_id=case,
                                            decision_id="decision", topic=remembered_topic, summary="复习点",
                                            evidence_refs=[], created_at=now(), updated_at=now(),
                                            deleted_at=now() if deleted else None)
                    db.add(record)
                    db.flush()
                    rows = list(db.scalars(active_memories(reader).where(LearningMemory.topic == current_topic)))
                    self.assertEqual(any(row.id == case for row in rows), expected)


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "Install diagnostics dependencies.")
class DiagnosisApiTest(unittest.TestCase):
    def test_formal_epikt_diagnosis_preserves_ledger_and_enforces_scope(self):
        from fastapi.testclient import TestClient

        from api.catalog import Catalog
        from api.main import create_app
        from api.recommend import CalibratedScorer, Recommender
        from tutor.agent import TutorAgent

        run_dir = Path("artifacts/epikt-dbe-fold0")
        catalog_path = Path("artifacts/dbe-sql-approved.json")
        if not (run_dir / "test_metrics.json").is_file() or not catalog_path.is_file():
            self.skipTest("Formal EpiKT checkpoint and authorized catalog are required.")
        scorer = CalibratedScorer(run_dir, timeout=5)
        self.addCleanup(scorer.close)
        model = ToolModel()
        with TemporaryDirectory() as temp, patch.dict(os.environ, {
            "QUERYSTEP_DIAGNOSTICS_ENABLED": "1",
            "QUERYSTEP_DIAGNOSIS_CHECKPOINTS": f"{temp}/checkpoints.db",
        }):
            database_url = os.environ.get("QUERYSTEP_TEST_DATABASE_URL", f"sqlite:///{temp}/test.db")
            app = create_app(database_url=database_url, catalog=Catalog.load(catalog_path),
                             recommender=Recommender(scorer), tutor=TutorAgent(model, allow_mapped_items=True))
            with TestClient(app) as client:
                self.assertTrue(client.get("/healthz").json()["diagnostics_ready"])
                client.post("/api/session").raise_for_status()
                for index, option in enumerate((1, 0, 0, 0)):
                    current = client.post("/api/practice/next").raise_for_status().json()
                    path = f"/api/practice/{current['decision_id']}"
                    client.post(path + "/answer", json={"option": option, "idempotency_key": f"initial-{index}"}).raise_for_status()
                replay = client.get(path + "/replay").raise_for_status().json()
                self.assertEqual((replay["source"], replay["chosen_item_id"], replay["comparison"]["rule_item_id"]),
                                 ("epikt", 75, 69))
                self.assertTrue(client.get(path + "/diagnosis").json()["available"])
                clarify = client.post(path + "/diagnosis", json={
                    "message": "为什么不是三组？", "idempotency_key": "clarify-test",
                }).raise_for_status().json()
                clarify_path = f"/api/diagnosis/{clarify['run_id']}"
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    clarification = client.get(clarify_path).raise_for_status().json()
                    if clarification["status"] == "completed":
                        break
                    sleep(0.05)
                self.assertEqual(clarification["result"]["mode"], "clarify")
                self.assertIsNone(clarification["proposal"])
                self.assertFalse(clarification["result"]["observations"])
                experiment_input = {"query_id": "having_gte", "min_count": 1, "idempotency_key": "experiment-1"}
                self.assertEqual(client.post(clarify_path + "/experiment", json=experiment_input)
                                 .raise_for_status().json()["comparison"]["after_row_count"], 4)
                payload = {"message": "用 HAVING > 1 验证。", "idempotency_key": "diagnosis-test"}
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first, duplicate = list(pool.map(lambda _: client.post(
                        path + "/diagnosis", json=payload,
                    ).raise_for_status().json(), range(2)))
                self.assertEqual(first["run_id"], duplicate["run_id"])
                self.assertEqual(client.post(path + "/diagnosis", json={**payload, "message": "另一个问题"}).status_code, 409)
                run_path = f"/api/diagnosis/{first['run_id']}"
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    report = client.get(run_path).raise_for_status().json()
                    if report["status"] == "waiting_confirmation":
                        break
                    sleep(0.05)
                self.assertEqual(report["status"], "waiting_confirmation")
                self.assertEqual(report["result"]["mode"], "full")
                self.assertEqual(report["result"]["model_calls"], 0)
                self.assertEqual(model.learning_notes, [])
                transfer_path = run_path + "/transfer"
                self.assertEqual(client.get(transfer_path).json(), {"available": True, "exercise": None, "feedback": None})
                self.assertEqual(client.post(transfer_path + "/answer", json={"option": 2}).status_code, 409)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    offered, duplicate_offer = list(pool.map(lambda _: client.post(transfer_path).raise_for_status().json(), range(2)))
                self.assertEqual(offered, duplicate_offer)
                self.assertEqual(offered["exercise"]["id"], "library-branches-gte@1")
                self.assertNotIn("correct_option", offered["exercise"])
                self.assertIsNone(offered["feedback"])
                with ThreadPoolExecutor(max_workers=2) as pool:
                    submitted, duplicate_answer = list(pool.map(lambda _: client.post(
                        transfer_path + "/answer", json={"option": 2},
                    ).raise_for_status().json(), range(2)))
                self.assertEqual(submitted, duplicate_answer)
                self.assertTrue(submitted["feedback"]["correct"])
                self.assertEqual(client.post(transfer_path + "/answer", json={"option": 0}).status_code, 409)
                stream = client.get(run_path + "/events").raise_for_status()
                events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: {")]
                events = [event for event in events if "seq" in event]
                self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
                self.assertEqual(events[-1]["type"], "waiting_for_confirmation")
                resumed = client.get(run_path + "/events", headers={"Last-Event-ID": str(events[-2]["seq"])})
                self.assertNotIn("branch_started", resumed.raise_for_status().text)
                self.assertIn("waiting_for_confirmation", resumed.text)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    experiment, duplicate = list(pool.map(lambda _: client.post(
                        run_path + "/experiment", json=experiment_input,
                    ).raise_for_status().json(), range(2)))
                self.assertEqual(experiment["comparison"]["after_row_count"], 4)
                self.assertEqual(duplicate, experiment)
                self.assertEqual(client.post(run_path + "/experiment", json=experiment_input).json(), experiment)
                self.assertEqual(client.post(run_path + "/experiment", json={**experiment_input, "min_count": 2}).status_code, 409)
                self.assertEqual(client.get("/api/practice/progress").json()["total"], 4)
                choice = {"proposal_id": report["proposal"]["proposal_id"], "action": "edit",
                          "summary": "我需要检查聚合后的筛选。", "idempotency_key": "confirm-test"}
                with patch("api.diagnostics.resume_confirmation", new=AsyncMock(side_effect=RuntimeError)):
                    self.assertEqual(client.post(run_path + "/confirmation", json=choice).status_code, 503)
                self.assertEqual(client.get("/api/learning-memories").json(), [])
                cookies = dict(client.cookies)
            with TestClient(app, cookies=cookies) as client:
                self.assertEqual(client.get(transfer_path).raise_for_status().json(), submitted)
                report = client.get(run_path).raise_for_status().json()
                self.assertEqual(report["status"], "waiting_confirmation")
                self.assertEqual(report["pending_confirmation"], {"action": "edit", "summary": choice["summary"]})
                choice = {**choice, "idempotency_key": "new-browser-key"}
                with ThreadPoolExecutor(max_workers=2) as pool:
                    confirmed, duplicate = list(pool.map(lambda _: client.post(
                        run_path + "/confirmation", json=choice,
                    ).raise_for_status().json(), range(2)))
                self.assertEqual(duplicate, confirmed)
                self.assertEqual(client.post(run_path + "/confirmation", json=choice).raise_for_status().json(), confirmed)
                self.assertEqual(client.post(run_path + "/confirmation", json={**choice, "summary": "其他"}).status_code, 409)
                memories = client.get("/api/learning-memories").raise_for_status().json()
                self.assertEqual(len(memories), 1)
                self.assertEqual(memories[0]["summary"], choice["summary"])
                memory_path = f"/api/learning-memories/{confirmed['memory_id']}"
                self.assertEqual(client.patch(memory_path, json={"summary": "更新", "version": 1}).raise_for_status().json()["version"], 2)
                self.assertEqual(client.patch(memory_path, json={"summary": "旧写入", "version": 1}).status_code, 409)
                learner_id = app.state.practice.learner(cookies["querystep_session"])
                self.assertEqual(app.state.diagnostics.relevant_memories(learner_id, "aggregate")[0]["summary"], "更新")
                self.assertEqual(app.state.diagnostics.relevant_memories(learner_id, "select"), [])
                self.assertEqual(client.post(run_path + "/cancel").json()["status"], "completed")
                next_item = client.post("/api/practice/next").raise_for_status().json()
                self.assertEqual(next_item["item"]["id"], 74)
                self.assertEqual(client.post(run_path + "/experiment", json=experiment_input).status_code, 409)
                self.assertEqual(client.post(transfer_path + "/answer", json={"option": 2}).status_code, 409)
                next_path = f"/api/practice/{next_item['decision_id']}"
                self.assertFalse(client.post(next_path + "/answer", json={
                    "option": 0, "idempotency_key": "memory-recall-graded",
                }).raise_for_status().json()["correct"])
                recalled = client.post(next_path + "/tutor", json={"message": "帮我回顾分组。"}).raise_for_status().json()
                self.assertEqual(recalled["memory_ids"], [confirmed["memory_id"]])
                self.assertEqual(model.learning_notes[-1], ["更新"])
                client.delete(memory_path).raise_for_status()
                self.assertEqual(client.get("/api/learning-memories").raise_for_status().json(), [])
                recalled = client.post(next_path + "/tutor", json={"message": "再讲一下。"}).raise_for_status().json()
                self.assertNotIn("memory_ids", recalled)
                self.assertEqual(model.learning_notes[-1], [])
                client.post("/api/session?restart=true").raise_for_status()
                self.assertEqual(client.get(run_path).status_code, 404)
                self.assertEqual(client.get(transfer_path).status_code, 404)
                self.assertEqual(client.get(run_path + "/events").status_code, 404)
                self.assertEqual(client.delete(memory_path).status_code, 404)
                for item_id, option in zip((57, 62, 63, 69, 78), (0, 1, 0, 2, 0), strict=True):
                    question = client.post("/api/practice/next").raise_for_status().json()
                    self.assertEqual(question["item"]["id"], item_id)
                    client.post(f"/api/practice/{question['decision_id']}/answer", json={
                        "option": option, "idempotency_key": f"join-graded-{item_id}",
                    }).raise_for_status()
                question = client.post("/api/practice/next").raise_for_status().json()
                self.assertEqual((question["source"], question["item"]["id"]), ("epikt", 81))
                join_path = f"/api/practice/{question['decision_id']}"
                self.assertFalse(client.post(join_path + "/answer", json={
                    "option": 0, "idempotency_key": "join-diagnosis-graded",
                }).raise_for_status().json()["correct"])
                self.assertEqual(client.get(join_path + "/diagnosis").json()["topic"], "join")
                with patch("api.diagnostics.Diagnostics._claim", return_value=None):
                    cancelled = client.post(join_path + "/diagnosis", json={
                        "message": "取消测试", "idempotency_key": "cancel-diagnosis",
                    }).raise_for_status().json()
                    cancelled_path = f"/api/diagnosis/{cancelled['run_id']}"
                    self.assertEqual(client.post(cancelled_path + "/cancel").json()["status"], "cancelled")
                join_run = client.post(join_path + "/diagnosis", json={
                    "message": "ON 和 WHERE 有什么区别？", "idempotency_key": "join-diagnosis",
                }).raise_for_status().json()
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    report = client.get(f"/api/diagnosis/{join_run['run_id']}").raise_for_status().json()
                    if report["status"] == "waiting_confirmation":
                        break
                    sleep(0.05)
                self.assertEqual(report["status"], "waiting_confirmation")
                self.assertEqual(report["result"]["comparison"]["removed_keys"], ["2", "3"])
                client.post("/api/practice/next").raise_for_status()
                self.assertEqual(client.get(f"/api/diagnosis/{join_run['run_id']}").json()["status"], "stale")
                self.assertEqual(client.post(f"/api/diagnosis/{join_run['run_id']}/confirmation", json={
                    "proposal_id": report["proposal"]["proposal_id"], "action": "confirm",
                    "idempotency_key": "confirm-stale",
                }).status_code, 409)

    def test_explanation_is_published_after_evidence_and_dropped_on_next_item(self):
        from threading import Event

        from fastapi.testclient import TestClient

        from api.catalog import Catalog
        from api.main import create_app
        from api.recommend import CalibratedScorer, Recommender
        from tutor.agent import TutorAgent

        run_dir = Path("artifacts/epikt-dbe-fold0")
        catalog_path = Path("artifacts/dbe-sql-approved.json")
        if not (run_dir / "test_metrics.json").is_file() or not catalog_path.is_file():
            self.skipTest("Formal EpiKT checkpoint and authorized catalog are required.")
        scorer = CalibratedScorer(run_dir, timeout=5)
        self.addCleanup(scorer.close)
        model = ToolModel()
        started, release, replied = Event(), Event(), Event()

        async def reply(*args, **kwargs):
            started.set()
            await asyncio.to_thread(release.wait, 2)
            replied.set()
            return {"content": '{"focus":"threshold","source":1,"note":0}'}

        model.reply_json = AsyncMock(side_effect=reply)
        with TemporaryDirectory() as temp, patch.dict(os.environ, {
            "QUERYSTEP_DIAGNOSTICS_ENABLED": "1", "QUERYSTEP_EXPLANATION_MODEL": "test",
        }):
            app = create_app(database_url=f"sqlite:///{temp}/p1.db", catalog=Catalog.load(catalog_path),
                             recommender=Recommender(scorer), tutor=TutorAgent(model, allow_mapped_items=True))
            with TestClient(app) as client:
                client.post("/api/session").raise_for_status()
                for index, option in enumerate((1, 0, 0, 0)):
                    item = client.post("/api/practice/next").raise_for_status().json()
                    path = f"/api/practice/{item['decision_id']}"
                    client.post(path + "/answer", json={"option": option, "idempotency_key": f"p1-answer-{index}"}).raise_for_status()
                run = client.post(path + "/diagnosis", json={"message": "HAVING > 1", "idempotency_key": "p1-diagnosis"}).raise_for_status().json()
                self.assertTrue(started.wait(3))
                run_path = f"/api/diagnosis/{run['run_id']}"
                before = client.get(run_path).raise_for_status().json()["result"]
                self.assertEqual((before["mode"], before["explanation"]["status"]), ("full", "pending"))
                self.assertEqual(before["comparison"]["removed_keys"], ["D"])
                client.post("/api/practice/next").raise_for_status()
                release.set()
                self.assertTrue(replied.wait(2))
                after = client.get(run_path).raise_for_status().json()["result"]
                self.assertEqual(after, before)
                self.assertEqual(client.get("/api/practice/progress").json()["total"], 4)
