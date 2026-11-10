"""Load immutable, reviewed practice items. Never expose the server answer key."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType

from kt.pykt_source import ROOT

DEFAULT_CATALOG = ROOT / "course_content/catalog.json"
GOAL = "sql-query"
TOPIC_NAMES = {
    "select": "SELECT 结果列",
    "where": "WHERE 行筛选",
    "conditions": "复合条件",
    "distinct": "DISTINCT 去重",
    "aggregate": "聚合与分组",
    "set_ops": "集合运算",
    "join": "连接入门",
    "subquery": "子查询",
}


@dataclass(frozen=True)
class Item:
    id: int
    title: str
    prompt: str
    options: tuple[str, ...]
    correct_option: int
    level: int
    topic: str
    hint: str
    source_question_id: int | None = None
    source_kcs: tuple[int, ...] = ()

    def public(self) -> dict:
        return {
            "id": self.id, "title": self.title, "prompt": self.prompt,
            "options": self.options, "level": self.level, "topic": TOPIC_NAMES[self.topic],
        }


class Catalog:
    def __init__(self, version: str, items: list[Item]):
        self.version = version
        self.items: Mapping[int, Item] = MappingProxyType({item.id: item for item in items})
        if not isinstance(version, str) or not version.strip() or len(self.items) != len(items) or len(items) < 4:
            raise ValueError("A catalog needs a version and at least four unique items.")
        sources = [item.source_question_id for item in items if item.source_question_id is not None]
        if len(sources) != len(set(sources)):
            raise ValueError("Model question IDs must be unique in the catalog.")
        for item in items:
            if (type(item.id) is not int or type(item.level) is not int or type(item.correct_option) is not int
                    or item.topic not in TOPIC_NAMES or item.level not in {1, 2, 3}
                    or not all(isinstance(value, str) and value.strip()
                               for value in (item.title, item.prompt, item.hint, *item.options))
                    or not 2 <= len(item.options) <= 21 or len(set(item.options)) != len(item.options)
                    or not 0 <= item.correct_option < len(item.options)
                    or (item.source_question_id is None) != (not item.source_kcs)
                    or (item.source_question_id is not None and type(item.source_question_id) is not int)
                    or any(type(kc) is not int for kc in item.source_kcs)
                    or tuple(sorted(set(item.source_kcs))) != item.source_kcs):
                raise ValueError(f"Invalid catalog item {item.id}.")
        snapshot = json.dumps(
            [version, [asdict(self.items[item_id]) for item_id in sorted(self.items)]],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        self.revision = sha256(snapshot.encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        items = []
        if not isinstance(data["items"], list):
            raise ValueError("Catalog items must be an array.")
        for entry in data["items"]:
            options = entry["options"]
            kcs = entry.get("source_kcs", [])
            if not isinstance(options, list) or not isinstance(kcs, list):
                raise ValueError("Catalog options and source KCs must be arrays.")
            items.append(Item(**{**entry, "options": tuple(options), "source_kcs": tuple(kcs)}))
        return cls(data["version"], items)
