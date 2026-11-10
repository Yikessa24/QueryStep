"""Prepare an internal review catalog from an explicitly authorized DBE-KT22 release."""

import argparse
from collections import defaultdict
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from zipfile import ZipFile

from api.catalog import Catalog
from course_content.demo_context import with_demo_context
from course_content.lessons import NOTES
from data_pipeline.dbe_kt22 import _read_csv
from data_pipeline.preprocess import ARCHIVE, sha256, write_json
from kt.train import DEFAULT_DATA, source_question_kcs, verified_data


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "pre", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "pre", "li"}:
            self.parts.append("\n")


def _text(value: str) -> str:
    if re.search(r"<(?:p|div|br|span|code|pre|em|strong|b|i)\b", value, re.I):
        parser = _VisibleText()
        parser.feed(value)
        parser.close()
        return "".join(parser.parts).strip()
    return unescape(value).strip()


def _prompt(question: dict[str, str]) -> str:
    plain = unescape(question["question_text"]).strip()
    rich = question["question_rich_text"]
    if not rich.strip():
        return plain
    parser = _VisibleText()
    parser.feed(rich)
    parser.close()
    visible = "".join(parser.parts)
    if visible.split() != plain.split():
        raise ValueError(f"Question {question['id']} has different rich and plain text; review the source.")
    return "\n".join(line.strip() for line in visible.splitlines() if line.strip())


def _topic(kcs: list[int], text: str) -> str:
    skills = set(kcs)
    if skills & {9, 40}:
        return "set_ops"
    if 44 in skills or re.search(r"\(\s*select\b", text, re.I):
        return "subquery"
    if skills & {33, 41, 42, 43} or re.search(r"\bfrom\s+\w+\s*,\s*\w+", text, re.I):
        return "join"
    if 35 in kcs or re.search(r"\bselect\s+distinct\b", text, re.I):
        return "distinct"
    if skills & {36, 37, 38, 39} or re.search(r"\b(?:count|min|max|sum|avg)\s*\(", text, re.I):
        return "aggregate"
    if re.search(r"\bwhere\b.*\b(?:and|or)\b", text, re.I | re.S):
        return "conditions"
    if re.search(r"\bwhere\b", text, re.I):
        return "where"
    return "select"


def build(archive: Path, data: Path, destination: Path, *, demo_context: bool = False) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    _, manifest = verified_data(data, ("data.txt",))
    if manifest["scope"] != "sql-core" or manifest["source_archive_sha256"] != sha256(archive):
        raise ValueError("Use the matching SQL-core preparation and official source archive.")
    mapping = source_question_kcs(data / "data.txt")
    with ZipFile(archive) as source:
        questions = _read_csv(source, "Questions.csv")
        choices = _read_csv(source, "Question_Choices.csv")
    options = defaultdict(list)
    for choice in choices:
        options[choice["question_id"]].append(choice)

    items = []
    for question in sorted(questions, key=lambda row: int(row["id"])):
        source = question["id"]
        if source not in mapping:
            continue
        candidates = sorted(options[source], key=lambda row: int(row["id"]))
        if (re.search(r"<img\b", question["question_rich_text"], re.I)
                or any(re.search(r"<img\b", row["choice_text"], re.I) for row in candidates)):
            continue
        correct, = [i for i, row in enumerate(candidates) if row["is_correct"] == "true"]
        prompt = _prompt(question)
        topic = _topic(mapping[source], prompt)
        if demo_context:
            prompt = with_demo_context(int(source), prompt)
        items.append({
            "id": int(source), "source_question_id": int(source), "source_kcs": mapping[source],
            "title": _text(question["question_title"]), "prompt": prompt,
            "options": [_text(row["choice_text"]) for row in candidates],
            "correct_option": correct, "topic": topic, "level": int(question["difficulty"]),
            "hint": NOTES[topic],
        })
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Write to a private file and validate before exposing it as a catalog.
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(dir=destination.parent) as temp:
        path = Path(temp) / "catalog.json"
        path.touch(mode=0o600)
        kind = "demo" if demo_context else "review"
        write_json(path, {"version": f"dbe-v1-{sha256(data / 'manifest.json')[:12]}-{kind}",
                          "items": items})
        Catalog.load(path)
        path.replace(destination)
    print(f"Prepared {len(items)} catalog entries for {kind}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorized", action="store_true", help="Confirm this catalog use is authorized.")
    parser.add_argument("--demo-context", action="store_true", help="Attach labeled synthetic table rows.")
    args = parser.parse_args()
    if not args.authorized:
        parser.error("Confirm the permitted use of the catalog before importing.")
    build(args.archive, args.data, args.output, demo_context=args.demo_context)


if __name__ == "__main__":
    main()
