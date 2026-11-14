"""Verify reviewed answer keys against independent SQLite execution."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from course_content.transfer import TRANSFER_ITEMS
from course_content.transfer_templates import QUESTION_TEMPLATES
from sql_lab.transfer import build_transfer, template_for


class TransferItemTest(unittest.TestCase):
    def test_answer_keys_match_executed_queries(self):
        for item in TRANSFER_ITEMS.values():
            with self.subTest(item=item.id), closing(sqlite3.connect(":memory:")) as db:
                table = re.search(r"\bFROM (\w+)", item.sql)[1]
                key, value = item.columns
                db.execute(f"CREATE TABLE {table} ({key} TEXT, {value} TEXT)")
                db.executemany(f"INSERT INTO {table} VALUES (?, ?)", item.rows)
                result = {row[0] for row in db.execute(item.sql)}
                groups = [set(re.findall(r"[^、和]+", option.removeprefix("仅"))) for option in item.options]
                self.assertEqual([index for index, group in enumerate(groups) if group == result], [item.correct_option])

    def test_each_reviewed_mapping_generates_distinct_options(self):
        self.assertEqual(set(QUESTION_TEMPLATES), {57, 62, 63, 64, *range(68, 88)})
        for question_id, (kcs, _) in QUESTION_TEMPLATES.items():
            variants = ("standard", "inclusive") if question_id == 75 else ("standard",)
            for variant in variants:
                with self.subTest(question_id=question_id, variant=variant):
                    for seed in range(200):
                        item = build_transfer(question_id, kcs, seed, variant)
                        self.assertEqual(len(set(item["options"])), 4)
                    self.assertIsNone(template_for(question_id, (-1,), variant))

    def test_left_join_counts_unmatched_and_one_to_many(self):
        kcs, _ = QUESTION_TEMPLATES[81]
        sizes = set()
        for seed in range(12):
            item = build_transfer(81, kcs, seed)
            sites, entries = item["tables"]
            matched = sum(site[0] == entry[1] for site in sites["rows"] for entry in entries["rows"])
            unmatched = sum(not any(site[0] == entry[1] for entry in entries["rows"]) for site in sites["rows"])
            expected = matched + unmatched
            sizes.add(expected)
            self.assertEqual(item["options"][item["correct_option"]], f"{expected} 行")
            self.assertEqual(len(item["result_rows"]), expected)
            self.assertEqual(sum(row[2] is None for row in item["result_rows"]), unmatched)
            self.assertEqual(set(item["options"]), {f"{size} 行" for size in (
                matched, expected, len(sites["rows"]), len(sites["rows"]) * len(entries["rows"]),
            )})
        self.assertEqual(sizes, {8, 9})


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install diagnostics dependencies.")
class TransferScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_transfer_scope_rejects_raw_sql_and_other_roles(self):
        from course_content.sql_fixtures import JOIN_FIXTURE
        from sql_lab.client import open_lab
        from sql_lab.contracts import TRANSFER_SCOPE, TRANSFER_TOOL
        from sql_lab.executor import LabError

        payload = {"question_id": 81, "kcs": [29, 43], "seed": 37, "variant": "standard"}
        async with open_lab(TRANSFER_SCOPE) as lab:
            self.assertEqual([tool.name for tool in (await lab.session.list_tools()).tools], [TRANSFER_TOOL])
            with self.assertRaisesRegex(LabError, "invalid_parameters"):
                await lab.call("transfer", TRANSFER_TOOL, {**payload, "sql": "SELECT 1"})
            with self.assertRaisesRegex(LabError, "mcp_tool_failed"):
                await lab.call("transfer", TRANSFER_TOOL, {**payload, "kcs": [29]})
            with self.assertRaisesRegex(LabError, "tool_not_allowed"):
                await lab.call("experiment", TRANSFER_TOOL, payload)
        async with open_lab(JOIN_FIXTURE) as lab:
            with self.assertRaisesRegex(LabError, "tool_not_allowed"):
                await lab.call("transfer", TRANSFER_TOOL, payload)


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "Install diagnostics dependencies.")
class TransferApiTest(unittest.TestCase):
    def test_formal_catalog_transfers_with_real_mcp(self):
        from fastapi.testclient import TestClient

        from api.catalog import Catalog
        from api.db import Decision
        from api.main import create_app
        from api.recommend import Recommender
        from tutor.agent import TutorAgent

        catalog_path = Path("artifacts/dbe-sql-approved.json")
        if not catalog_path.is_file():
            self.skipTest("Authorized SQL Core catalog is required.")
        catalog = Catalog.load(catalog_path)
        self.assertEqual({item.source_question_id for item in catalog.items.values()}, set(QUESTION_TEMPLATES))
        with TemporaryDirectory() as directory, patch.dict(os.environ, {
            "QUERYSTEP_DIAGNOSTICS_ENABLED": "1", "QUERYSTEP_EXPLANATION_MODEL": "",
            "QUERYSTEP_DIAGNOSIS_CHECKPOINTS": f"{directory}/checkpoints.db",
        }):
            app = create_app(database_url=f"sqlite:///{directory}/practice.db", catalog=catalog,
                             recommender=Recommender(), tutor=TutorAgent(None))
            with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
                self.assertTrue(client.get("/healthz").json()["diagnostics_ready"])
                for item in catalog.items.values():
                    with self.subTest(item=item.id):
                        client.cookies.clear()
                        client.post("/api/session").raise_for_status()
                        practice = app.state.practice
                        learner_id = practice.learner_id(next(iter(client.cookies.values())))
                        decision_id = f"transfer-{item.id}"
                        with practice.db.transaction() as db:
                            db.add(Decision(id=decision_id, learner_id=learner_id, history_version=0,
                                            catalog_version=catalog.revision, item_id=item.id,
                                            source="rule", reason="test", trace={}))
                        path = f"/api/practice/{decision_id}"
                        transfer = path + "/transfer"
                        self.assertFalse(client.get(transfer).raise_for_status().json()["available"])
                        option = (item.correct_option + 1) % len(item.options)
                        client.post(path + "/answer", json={"option": option, "idempotency_key": decision_id}).raise_for_status()
                        self.assertTrue(client.get(transfer).raise_for_status().json()["available"])
                        self.assertEqual(client.post(transfer + "/answer", json={"option": 0}).status_code, 409)
                        if item.source_question_id == 81:
                            offered, duplicate = pool.map(lambda _: client.post(transfer).raise_for_status().json(), range(2))
                            self.assertEqual(duplicate, offered)
                        else:
                            offered = client.post(transfer).raise_for_status().json()
                        self.assertIsNone(offered["feedback"])
                        public = offered["exercise"]
                        self.assertEqual(set(public), {"id", "context", "sql", "tables", "options"})
                        expected = build_transfer(item.source_question_id, item.source_kcs,
                                                  int(public["id"].rsplit("-", 1)[1]),
                                                  "inclusive" if item.source_question_id == 75 else "standard")
                        self.assertEqual(public["options"], expected["options"])
                        correct_option = expected["correct_option"]
                        response = client.post(transfer + "/answer", json={"option": correct_option}).raise_for_status().json()
                        self.assertTrue(response["feedback"]["correct"])
                        self.assertEqual(response["feedback"]["result_rows"], expected["result_rows"])
                        self.assertEqual(client.post(transfer + "/answer", json={"option": correct_option}).json(), response)
                        self.assertEqual(client.post(transfer + "/answer", json={"option": (correct_option + 1) % 4}).status_code, 409)
                        self.assertEqual(client.get("/api/practice/progress").json()["total"], 1)
                        client.post("/api/practice/next").raise_for_status()
                        self.assertEqual(client.get(transfer).raise_for_status().json(), response)
                        self.assertEqual(client.post(transfer + "/answer", json={"option": correct_option}).status_code, 409)
                        client.cookies.clear()
                        client.post("/api/session").raise_for_status()
                        self.assertEqual(client.get(transfer).status_code, 404)
