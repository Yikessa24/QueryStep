import asyncio
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db import Attempt, Learner
from api.main import create_app
from api.recommend import Recommender
from api.workbench import SQLRun
from tutor.agent import TutorAgent


class WorkbenchAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.url = f"sqlite:///{Path(self.temp.name) / 'workbench.sqlite3'}"
        self.environment = self.enterContext(patch.dict("os.environ", {
            "QUERYSTEP_DIAGNOSTICS_ENABLED": "0", "QUERYSTEP_COACH_ENABLED": "0",
        }))
        self.app = self.make_app()
        self.client = self.enterContext(TestClient(self.app))
        self.client.post("/api/session").raise_for_status()
        self.assertTrue(self.client.get("/healthz").json()["sql_workbench_ready"])
        self.tasks = self.client.get("/api/sql/tasks").raise_for_status().json()["tasks"]
        self.task_id = self.tasks[0]["id"]
        self.path = f"/api/sql/tasks/{self.task_id}"
        public = self.client.get(self.path).raise_for_status().json()["task"]
        table = public["tables"][0]
        self.sql = f'SELECT "{table["columns"][0]}" FROM "{table["name"]}"'

    def make_app(self):
        return create_app(database_url=self.url, recommender=Recommender(), tutor=TutorAgent(None))

    def submit(self, key="request-0001", action="run", **kwargs):
        return self.client.post(self.path + "/runs", json={
            "sql": self.sql, "action": action, "message": "请验证边界条件", "idempotency_key": key, **kwargs,
        })

    def settled(self, identifier):
        deadline = monotonic() + 12
        while monotonic() < deadline:
            row = self.client.get(f"/api/sql/runs/{identifier}").raise_for_status().json()
            if row["status"] not in {"queued", "running"}:
                return row
            sleep(0.02)
        self.fail("SQL run did not settle")

    def test_catalog_hides_oracle_and_requires_session(self):
        self.assertGreaterEqual(len(self.tasks), 8)
        for task in self.tasks:
            detail = self.client.get(f'/api/sql/tasks/{task["id"]}').raise_for_status().json()
            self.assertNotIn("reference_sql", detail["task"])
            self.assertEqual(detail["draft"]["version"], 0)
            self.assertEqual(detail["runs"], [])
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/sql/tasks").status_code, 401)
        self.assertEqual(self.client.put(self.path + "/draft", json={"sql": "SELECT 1", "version": 0}).status_code, 401)

    def test_draft_version_conflict_retains_saved_sql(self):
        path = self.path + "/draft"
        self.assertEqual(self.client.put(path, json={"sql": self.sql, "version": 0}).json(),
                         {"sql": self.sql, "version": 1})
        conflict = self.client.put(path, json={"sql": "SELECT 2", "version": 0})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get(self.path).json()["draft"]["sql"], self.sql)
        self.client.put(path, json={"sql": "", "version": 1}).raise_for_status()
        self.assertEqual(self.client.get(self.path).json()["draft"], {"sql": "", "version": 2})

    def test_run_idempotency_does_not_change_formal_history(self):
        original = self.client.get("/api/practice/progress").json()
        first = self.submit().raise_for_status().json()
        duplicate = self.submit().raise_for_status().json()
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(self.submit(sql="SELECT 2").status_code, 409)
        result = self.settled(first["id"])
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["result"]["query"]["status"], "ok", result)
        self.assertIsNone(result["result"]["metrics"]["cost"])
        self.assertEqual(self.client.get("/api/practice/progress").json(), original)
        with self.app.state.practice.db.transaction() as db:
            self.assertEqual(len(list(db.scalars(select(SQLRun)))), 1)
            self.assertEqual(list(db.scalars(select(Attempt))), [])
            self.assertEqual(db.scalar(select(Learner.history_version)), 0)

    def test_request_limits_unknown_task_and_session_isolation(self):
        self.assertEqual(self.submit(sql="").status_code, 422)
        self.assertEqual(self.submit(sql="x" * 6001).status_code, 422)
        self.assertEqual(self.submit(action="delete").status_code, 422)
        self.assertEqual(self.client.get("/api/sql/tasks/missing").status_code, 404)
        first = self.submit().raise_for_status().json()
        self.settled(first["id"])
        self.client.post("/api/session?restart=true").raise_for_status()
        for suffix in ("", "/cancel", "/resume"):
            path = f'/api/sql/runs/{first["id"]}{suffix}'
            response = self.client.post(path, json={}) if suffix else self.client.get(path)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(self.path).json()["runs"], [])

    def test_malicious_query_rejected_without_worker_failure(self):
        first = self.submit(sql="ATTACH DATABASE '/tmp/should-not-be-created' AS disk").raise_for_status().json()
        result = self.settled(first["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["query"]["status"], "rejected")
        second = self.submit("request-0002").raise_for_status().json()
        self.assertEqual(self.settled(second["id"])["result"]["query"]["status"], "ok")

    def test_check_has_finite_verification_and_separate_ledger(self):
        first = self.submit(action="check").raise_for_status().json()
        result = self.settled(first["id"])
        self.assertEqual(result["status"], "completed", result)
        check = result["result"]["check"]
        self.assertIn(check["status"], {"passed", "mismatch"})
        self.assertGreater(check["total"], 0)
        self.assertEqual(self.client.get("/api/practice/progress").json()["total"], 0)

    def test_learning_context_uses_versioned_predictions_not_generated_task_ids(self):
        class Scorer:
            version = "context-test-model"
            def supports(self, item):
                return True
            def score(self, history, items):
                return {item.id: 0.6 for item in items}
        self.app.state.practice.recommender = Recommender(Scorer())
        for index in range(3):
            selected = self.client.post("/api/practice/next", json={}).raise_for_status().json()
            self.client.post(f'/api/practice/{selected["decision_id"]}/answer', json={
                "option": 0, "idempotency_key": f"formal-{index:03d}",
            }).raise_for_status()
        selected = self.client.post("/api/practice/next", json={}).raise_for_status().json()
        self.assertEqual(selected["source"], "epikt")
        first = self.submit().raise_for_status().json()
        self.settled(first["id"])
        with self.app.state.practice.db.transaction() as db:
            context = db.get(SQLRun, first["id"]).context
            self.assertEqual(len(context["recent_independent_attempts"]), 3)
            self.assertTrue(context["epikt"]["available"])
            self.assertEqual(context["epikt"]["model_version"], "context-test-model")
            self.assertEqual(context["epikt"]["snapshot_history_version"], 3)
            self.assertEqual(context["epikt"]["current_history_version"], 3)
            self.assertNotIn("mastery", context["epikt"])
        self.assertEqual(self.client.get("/api/practice/progress").json()["total"], 3)

    def test_cancel_stops_coach_and_keeps_checkpoint(self):
        entered = Event()
        async def waiting(task_id, sql, message, context, state, checkpoint, publish):
            await checkpoint({"completed_tools": ["sample"]})
            await publish({"type": "evidence", "data": {"retained": True}})
            entered.set()
            await asyncio.Event().wait()
        with patch.object(self.app.state.workbench, "_coach", waiting):
            first = self.submit(action="coach").raise_for_status().json()
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.submit("request-0002").status_code, 409)
            stopped = self.client.post(f'/api/sql/runs/{first["id"]}/cancel', json={}).raise_for_status().json()
            self.assertEqual(stopped["status"], "cancelled")
            self.assertTrue(any(event["type"] == "evidence" for event in stopped["events"]))
            self.assertEqual(self.client.post(f'/api/sql/runs/{first["id"]}/resume', json={}).status_code, 409)
            with self.app.state.practice.db.transaction() as db:
                self.assertEqual(db.get(SQLRun, first["id"]).state, {"completed_tools": ["sample"]})

    def test_cancel_signals_query_thread_and_preserves_cancelled_status(self):
        for action, function in (("run", "run_query"), ("check", "evaluate")):
            entered, stopped = Event(), Event()
            def waiting(task_id, sql, *, cancel_event):
                entered.set()
                if cancel_event.wait(5):
                    stopped.set()
                return {"message": "cancelled"}
            with self.subTest(action=action), patch(f"sql_lab.workbench.{function}", waiting):
                first = self.submit(f"cancel-{action}-0001", action=action).raise_for_status().json()
                self.assertTrue(entered.wait(5))
                result = self.client.post(f'/api/sql/runs/{first["id"]}/cancel', json={}).raise_for_status().json()
                self.assertTrue(stopped.wait(1))
                self.assertEqual(result["status"], "cancelled")
                self.assertEqual(self.settled(first["id"])["status"], "cancelled")

    def test_shared_mcp_lifecycle_reuses_worker_and_closes_cleanly(self):
        service = self.app.state.workbench
        first = self.client.portal.call(service._get_lab)
        self.assertIs(self.client.portal.call(service._get_lab), first)
        async def describe():
            return await first.call("workbench", "describe_sql_task", {"task_id": self.task_id})
        self.assertEqual(self.client.portal.call(describe)["id"], self.task_id)
        self.client.portal.call(service.close)
        self.assertTrue(service.lab_task.done())

    def test_unconfigured_coach_does_not_start_an_unused_tool_process(self):
        self.assertFalse(self.client.get("/healthz").json()["sql_coach_ready"])
        self.assertFalse(self.client.get("/api/sql/tasks").json()["coach_available"])
        first = self.submit(action="coach").raise_for_status().json()
        result = self.settled(first["id"])
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["result"]["mode"], "evidence_only")
        self.assertEqual(result["result"]["metrics"]["finish_reason"], "model_unavailable")
        self.assertEqual(result["result"]["metrics"]["model_calls"], 0)
        self.assertIsNone(self.app.state.workbench.lab_task)

    def test_retrieval_version_is_persisted_with_the_run(self):
        class Model:
            calls = 0
            async def reply_json(self, *args, **kwargs):
                self.calls += 1
                plan = ({"actions": [{"name": "search_course", "args": {"query": "COUNT NULL"}}]}
                        if self.calls == 1 else {"finish": {"kind": "insufficient"}})
                return {"content": json.dumps(plan)}
        service = self.app.state.workbench
        with patch.object(service, "coach_reason", None), patch.object(service.practice.tutor, "model", Model()):
            first = self.submit(action="coach").raise_for_status().json()
            result = self.settled(first["id"])
        self.assertEqual(result["status"], "completed")
        versions = [event for event in result["events"] if event["type"] == "retrieval_version"]
        self.assertEqual(len(versions), 1)
        self.assertIn(versions[0]["data"]["mode"], ("reviewed_cards", "keyword", "vector", "hybrid"))
        self.assertRegex(versions[0]["data"]["corpus"], r"^[a-f0-9]{64}$")
        self.assertEqual(set(versions[0]["data"]), {"mode", "corpus"})
        reloaded = self.client.get(f'/api/sql/runs/{first["id"]}').raise_for_status().json()
        self.assertEqual(reloaded["events"], result["events"])

    def test_missing_optional_dependencies_do_not_break_sql_runs(self):
        from api.workbench import Workbench
        with patch.object(self.app.state.practice.tutor, "model", object()), patch("api.workbench.find_spec", return_value=None):
            instance = Workbench(self.app.state.practice)
        self.assertEqual(instance.coach_reason, "dependencies_unavailable")
        result = self.client.portal.call(instance._coach, self.task_id, self.sql, "检查结果", {}, {}, None, None)
        self.assertEqual(result["metrics"]["finish_reason"], "dependencies_unavailable")
        self.assertEqual(result["metrics"]["model_calls"], 0)
        first = self.submit().raise_for_status().json()
        self.assertEqual(self.settled(first["id"])["result"]["query"]["status"], "ok")

    def test_resume_rejects_changed_task_or_deleted_memory(self):
        from api.learning_memory import LearningMemory

        first = self.submit().raise_for_status().json()
        self.settled(first["id"])
        with self.app.state.practice.db.transaction() as db:
            run = db.get(SQLRun, first["id"])
            run.status = "interrupted"
            run.task_version = "outdated"
        response = self.client.post(f'/api/sql/runs/{first["id"]}/resume', json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("版本", response.json()["detail"])
        LearningMemory.__table__.create(self.app.state.practice.db.engine, checkfirst=True)
        with self.app.state.practice.db.transaction() as db:
            run = db.get(SQLRun, first["id"])
            run.task_version = str(self.app.state.workbench.task(self.task_id)["version"])
            run.context = {"confirmed_notes": [{"id": "removed-note", "version": 1, "summary": "old"}]}
        response = self.client.post(f'/api/sql/runs/{first["id"]}/resume', json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("学习记忆", response.json()["detail"])
        self.assertEqual(self.client.get(f'/api/sql/runs/{first["id"]}').json()["status"], "interrupted")

    def test_interruption_can_resume_saved_state_after_restart(self):
        entered = Event()
        async def waiting(task_id, sql, message, context, state, checkpoint, publish):
            await checkpoint({"completed_tools": ["sample"], "model_calls": 1})
            entered.set()
            await asyncio.Event().wait()
        with patch.object(self.app.state.workbench, "_coach", waiting):
            first = self.submit(action="coach").raise_for_status().json()
            self.assertTrue(entered.wait(5))
            self.client.portal.call(self.app.state.workbench.close)
        self.assertEqual(self.client.get(f'/api/sql/runs/{first["id"]}').json()["status"], "interrupted")
        received = []
        async def recovered(task_id, sql, message, context, state, checkpoint, publish):
            received.append(deepcopy(state))
            return {"kind": "coach", "text": "已从保存的观察继续。", "mode": "evidence_only"}
        with TestClient(self.make_app()) as resumed:
            resumed.cookies.update(self.client.cookies)
            with patch.object(resumed.app.state.workbench, "_coach", recovered):
                response = resumed.post(f'/api/sql/runs/{first["id"]}/resume', json={}).raise_for_status()
                self.assertEqual(response.json()["id"], first["id"])
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    status = resumed.get(f'/api/sql/runs/{first["id"]}').json()
                    if status["status"] == "completed":
                        break
                    sleep(0.02)
                self.assertEqual(status["status"], "completed")
        self.assertEqual(received, [{"completed_tools": ["sample"], "model_calls": 1}])


if __name__ == "__main__":
    unittest.main()
