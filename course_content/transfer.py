"""Original HAVING transfer items. Versioned IDs keep existing attempts reproducible."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TransferItem:
    id: str
    context: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, str], ...]
    sql: str
    options: tuple[str, ...]
    correct_option: int
    feedback: str

    def public(self) -> dict:
        return {"id": self.id, "context": self.context, "columns": self.columns, "rows": self.rows,
                "sql": self.sql, "options": self.options}


EVENTS = TransferItem(
    "event-venues-gt@1", "活动表中，每行是一场活动。运行以下查询后，哪组场馆会出现在结果中？",
    ("venue", "event"), (("北馆", "讲座"), ("东馆", "展览"), ("北馆", "导览"), ("南馆", "比赛"),
                        ("东馆", "工作坊"), ("北馆", "演出")),
    "SELECT venue FROM events\nGROUP BY venue\nHAVING COUNT(*) > 2",
    ("北馆和东馆", "仅北馆", "仅东馆", "北馆、东馆和南馆"), 1,
    "北馆有 3 场活动，东馆有 2 场，南馆有 1 场。严格大于 2 只保留北馆。",
)

LOANS = TransferItem(
    "library-branches-gte@1", "借阅表中，每行是一条借阅记录。运行以下查询后，哪组分馆会出现在结果中？",
    ("branch", "book"), (("河西", "植物志"), ("城南", "观星手册"), ("河西", "地理图册"), ("城北", "海洋图鉴"),
                         ("城南", "古城地图"), ("城南", "自然笔记")),
    "SELECT branch FROM loans\nGROUP BY branch\nHAVING COUNT(*) >= 2",
    ("仅城南", "河西和城北", "河西和城南", "河西、城南和城北"), 2,
    "河西有 2 条借阅，城南有 3 条，城北有 1 条。大于等于 2 同时保留河西和城南。",
)

TRANSFER_ITEMS = {item.id: item for item in (EVENTS, LOANS)}
