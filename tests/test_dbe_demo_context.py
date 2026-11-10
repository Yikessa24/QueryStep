"""Validate the displayed reference rows against the official answer keys."""

import re
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from api.catalog import Catalog
from course_content.demo_context import demo_tables
from course_content.import_dbe import build
from data_pipeline.preprocess import ARCHIVE
from kt.train import DEFAULT_DATA


class DBEDemoContextTest(unittest.TestCase):
    @unittest.skipUnless(ARCHIVE.is_file() and (DEFAULT_DATA / "manifest.json").is_file(),
                         "Requires the private DBE-KT22 archive and prepared SQL Core.")
    def test_displayed_queries_match_all_context_dependent_answer_keys(self):
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "demo.json"
            build(ARCHIVE, DEFAULT_DATA, destination, demo_context=True)
            catalog = Catalog.load(destination)
        self.assertEqual(len(catalog.items), 24)
        context_items = [item for item in catalog.items.values() if "演示用表数据（合成）" in item.prompt]
        self.assertEqual(len(context_items), 19)
        for item in context_items:
            with self.subTest(item=item.id):
                question, _ = item.prompt.split("\n\n演示用表数据（合成）", 1)
                sql = re.search(r"(?im)^SELECT\b[\s\S]*$", question)
                self.assertIsNotNone(sql)
                connection = sqlite3.connect(":memory:")
                self.addCleanup(connection.close)
                for name, (columns, *rows) in demo_tables(item.id).items():
                    types = ["INTEGER" if isinstance(value, int) else "TEXT" for value in rows[0]]
                    schema = ", ".join(f"{column} {dtype}"
                                       for column, dtype in zip(columns, types, strict=True))
                    connection.execute(f"CREATE TABLE {name} ({schema})")
                    placeholders = ", ".join("?" for _ in columns)
                    connection.executemany(f"INSERT INTO {name} VALUES ({placeholders})", rows)
                connection.execute("PRAGMA query_only = ON")
                cursor = connection.execute(sql[0])
                rows = cursor.fetchall()
                if item.id == 73:
                    actual = rows[0]
                elif item.id == 86:
                    actual = (len(rows), len(cursor.description))
                else:
                    actual = (len(rows),)
                answers = [tuple(int(value.strip()) for value in option.split(","))
                           for option in item.options]
                self.assertEqual(actual, answers[item.correct_option])
                self.assertEqual(answers.count(actual), 1)
