from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.catalog import Catalog
from api.db import TutorTurn
from api.main import create_app
from api.recommend import Recommender
from tutor.agent import TutorAgent


class TestScorer:
    version = "test-injected"

    @staticmethod
    def supports(_):
        return True

    @staticmethod
    def score(_, items):
        return {item.id: 0.43 if item.level == 2 else 0.76 for item in items}


class PracticeAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        url = os.environ.get("QUERYSTEP_TEST_DATABASE_URL") or (
            f"sqlite:///{Path(self.temp.name) / 'test.sqlite3'}"
        )
        self.app = create_app(database_url=url, recommender=Recommender(TestScorer()))
        self.client = self.enterContext(TestClient(self.app))

    def present(self, client=None):
        client = client or self.client
        response = client.post("/api/practice/next", json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def answer(self, decision, option, client=None):
        client = client or self.client
        return client.post(f"/api/practice/{decision}/answer",
                           json={"option": option, "idempotency_key": decision})

    def test_history_review_restores_saved_feedback_without_advancing(self):
        self.client.post("/api/session", json={}).raise_for_status()
        initial = self.present()
        answer = self.answer(initial["decision_id"], 1).raise_for_status().json()
        turn = self.client.post(f"/api/practice/{initial['decision_id']}/tutor",
                               json={"message": "我想回顾这道题。"}).raise_for_status().json()
        pending = self.present()
        progress = self.client.get("/api/practice/progress").json()
        history = self.client.get("/api/practice/history/1").raise_for_status().json()
        self.assertEqual(history, {"presentation": initial, "feedback": answer, "turns": [turn]})
        self.assertEqual(self.client.get("/api/practice/history/2").status_code, 404)
        self.assertEqual(self.client.get("/api/practice/progress").json(), progress)
        self.assertEqual(self.present(), pending)
        self.client.post("/api/session?restart=true", json={}).raise_for_status()
        self.assertEqual(self.client.get("/api/practice/history/1").status_code, 404)

    def test_full_flow_resume_tutor_and_scoring_trace(self):
        self.assertEqual(self.client.get("/api/practice/progress").status_code, 401)
        self.assertEqual(self.client.post("/api/session", json={}).status_code, 200)
        for index, option in enumerate((0, 1, 0)):
            payload = self.present()
            item = payload["item"]
            self.assertNotIn("correct_option", item)
            self.assertEqual(self.present()["decision_id"], payload["decision_id"])
            self.assertEqual(payload["source"], "rule")
            decision = payload["decision_id"]
            result = self.answer(decision, option)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["event_seq"], index + 1)
            self.assertEqual(result.json(), self.answer(decision, option).json())

        tutor = self.client.post(f"/api/practice/{decision}/tutor", json={"message": "WHERE 是什么？"})
        self.assertEqual(tutor.status_code, 200, tutor.text)
        self.assertEqual(tutor.json()["source"], "template")
        resumed = self.client.get("/api/practice/progress").json()
        self.assertEqual((resumed["total"], resumed["correct"]), (3, 2))
        self.assertEqual(resumed["last"]["turns"][0]["message"], "WHERE 是什么？")

        selected = self.present()
        self.assertEqual(selected["source"], "epikt")
        self.assertEqual(self.client.post(f"/api/practice/{decision}/tutor",
                                          json={"message": "继续"}).status_code, 409)
        replay = self.client.get(f"/api/practice/{selected['decision_id']}/replay").json()
        self.assertEqual(replay["comparison"]["model_version"], "test-injected")
        self.assertNotEqual(replay["chosen_item_id"], replay["comparison"]["rule_item_id"])

        with TestClient(create_app(database_url=str(self.app.state.practice.db.engine.url))) as other:
            other.post("/api/session", json={})
            self.assertEqual(other.get(f"/api/practice/{selected['decision_id']}/replay").status_code, 404)
            self.assertEqual(self.answer(selected["decision_id"], 0, other).status_code, 404)

    def test_concurrent_retry_only_advances_history_once(self):
        self.client.post("/api/session", json={})
        with ThreadPoolExecutor(max_workers=2) as pool:
            same_decisions = list(pool.map(lambda _: self.present()["decision_id"], range(2)))
            self.assertEqual(same_decisions[0], same_decisions[1])
            first, second = list(pool.map(lambda option: self.answer(same_decisions[0], option), (0, 1)))
        self.assertEqual(sorted((first.status_code, second.status_code)), [200, 409])
        self.assertEqual(self.client.get("/api/practice/progress").json()["total"], 1)

    def test_rule_fallback_on_timeout(self):
        class SlowScorer(TestScorer):
            @staticmethod
            def score(_, items):
                raise TimeoutError()

        self.app.state.practice.recommender = Recommender(SlowScorer())
        self.client.post("/api/session", json={})
        for _ in range(3):
            self.assertEqual(self.answer(self.present()["decision_id"], 0).status_code, 200)
        result = self.present()
        self.assertEqual((result["source"], result["reason"]), ("rule", "model_timeout"))

    def test_catalog_revision_rejects_stale_grading_and_allows_restart(self):
        self.client.post("/api/session", json={})
        original = self.app.state.practice.catalog
        pending = self.present()
        decision = pending["decision_id"]
        changed = [
            replace(item, correct_option=(item.correct_option + 1) % len(item.options))
            if item.id == pending["item"]["id"] else item
            for item in original.items.values()
        ]
        self.app.state.practice.catalog = Catalog(original.version, changed)
        stale = self.answer(decision, 0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["code"], "catalog_changed")
        progress = self.client.get("/api/practice/progress")
        self.assertEqual(progress.status_code, 409)
        self.assertEqual(progress.headers["Cache-Control"], "no-store")
        self.app.state.practice.catalog = original
        self.assertEqual(self.client.get("/api/practice/progress").json()["total"], 0)
        self.app.state.practice.catalog = Catalog(original.version, changed)
        self.client.post("/api/session?restart=true", json={})
        self.assertNotEqual(self.present()["decision_id"], decision)
        self.assertEqual(self.answer(decision, 0).status_code, 404)

    def test_ineligible_remaining_items_are_not_reported_as_complete(self):
        practice = self.app.state.practice
        original = practice.catalog
        practice.catalog = Catalog("advanced-only", [
            replace(item, level=1 if item.id <= 3 else 3) for item in original.items.values()
        ])
        self.client.post("/api/session", json={})
        for _ in range(3):
            payload = self.present()
            item = practice.catalog.items[payload["item"]["id"]]
            wrong = (item.correct_option + 1) % len(item.options)
            self.assertEqual(self.answer(payload["decision_id"], wrong).status_code, 200)
        self.assertEqual(self.present(), {"status": "blocked", "remaining": len(original.items) - 3})

    def test_invalid_provider_config_keeps_practice_available(self):
        env = {"QUERYSTEP_LLM_BASE_URL": "http://example.invalid/v1",
               "QUERYSTEP_LLM_API_KEY": "dummy-test-key", "QUERYSTEP_LLM_MODEL": "mock",
               "QUERYSTEP_LLM_ALLOW_INSECURE_HTTP": "0"}
        url = str(self.app.state.practice.db.engine.url)
        with patch.dict("os.environ", env), TestClient(create_app(database_url=url)) as client:
            health = client.get("/healthz").json()
            self.assertFalse(health["tutor_ready"])
            self.assertEqual(health["tutor_status"], "llm_invalid_configuration")
            client.post("/api/session", json={})
            decision = self.present(client)["decision_id"]
            self.assertEqual(self.answer(decision, 1, client).status_code, 200)
            turn = client.post(f"/api/practice/{decision}/tutor", json={"message": "看不懂。"}).json()
            self.assertEqual(turn["source"], "template")
            self.assertEqual(turn["fallback_reason"], "llm_invalid_configuration")

    def test_late_tutor_turn_is_discarded_after_student_moves_on(self):
        started = Event()
        release = Event()

        class PausedTutor(TutorAgent):
            def respond(self, item, message, prior):
                started.set()
                if not release.wait(3):
                    raise RuntimeError("Test did not release tutor.")
                return super().respond(item, message, prior)

        self.app.state.practice.tutor = PausedTutor()
        self.client.post("/api/session", json={})
        decision = self.present()["decision_id"]
        self.assertEqual(self.answer(decision, 1).status_code, 200)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.client.post, f"/api/practice/{decision}/tutor",
                                  json={"message": "能给个例子吗？"})
            try:
                self.assertTrue(started.wait(3))
                self.assertNotEqual(self.present()["decision_id"], decision)
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=3).status_code, 409)
        with self.app.state.practice.db.transaction() as db:
            self.assertIsNone(db.scalar(select(TutorTurn).where(TutorTurn.decision_id == decision)))
