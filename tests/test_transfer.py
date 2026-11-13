"""Verify reviewed answer keys against independent SQLite execution."""

from contextlib import closing
import re
import sqlite3
import unittest

from course_content.transfer import TRANSFER_ITEMS


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
