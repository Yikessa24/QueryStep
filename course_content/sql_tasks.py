"""Original, synthetic SQLite exercises; trusted answers stay server-side."""

from dataclasses import dataclass
from hashlib import sha256
import random


SCENARIOS = ("sample", "boundary", "empty", "duplicates")
VERSION = 1


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[tuple[str, str], ...]
    constraints: str

    @property
    def ddl(self) -> str:
        columns = ", ".join(f'"{name}" {kind}' for name, kind in self.columns)
        return f'CREATE TABLE "{self.name}" ({columns}, {self.constraints})'

    def view(self, rows: list[list]) -> dict:
        return {"name": self.name, "columns": [c[0] for c in self.columns],
                "types": [c[1] for c in self.columns], "rows": [list(row) for row in rows]}


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    topic: str
    concepts: tuple[str, ...]
    prompt: str
    starter_sql: str
    tables: tuple[Table, ...]
    reference_sql: str
    ordered: bool = False


_CUSTOMERS = Table("customers", (("customer_id", "INTEGER"), ("name", "TEXT")),
                   "PRIMARY KEY (customer_id), CHECK (name IS NOT NULL)")
_ORDERS = Table("orders", (("order_id", "INTEGER"), ("customer_id", "INTEGER"),
                           ("status", "TEXT"), ("amount", "INTEGER")),
                "PRIMARY KEY (order_id), FOREIGN KEY (customer_id) REFERENCES customers(customer_id), "
                "CHECK (customer_id IS NOT NULL), "
                "CHECK (status IS NOT NULL AND status IN ('paid','pending','cancelled')), "
                "CHECK (amount IS NOT NULL AND amount >= 0)")
_JOIN_RULES = ("customers.customer_id、orders.order_id 为主键；orders.customer_id 是非空外键。"
               "客户姓名可重复且非空；订单金额是非负整数；status 仅为 paid/pending/cancelled。")

_TASKS = {
    task.id: task for task in (
        Task("filter_paid", "筛选已付款订单", "where", ("select", "where", "conditions"),
             "返回已付款（status='paid'）且 amount >= 100 的订单，依次输出 order_id、amount。"
             "order_id 为主键；amount 是非空非负整数；status 非空且仅为 paid/pending/cancelled。"
             "不要求行顺序。",
             "SELECT order_id, amount FROM orders WHERE /* 补充条件 */;",
             (Table("orders", (("order_id", "INTEGER"), ("status", "TEXT"), ("amount", "INTEGER")),
                    "PRIMARY KEY (order_id), CHECK (amount IS NOT NULL AND amount >= 0), "
                    "CHECK (status IS NOT NULL AND status IN ('paid','pending','cancelled'))"),),
             "SELECT order_id, amount FROM orders WHERE status = 'paid' AND amount >= 100"),
        Task("null_contacts", "找出无联系方式的客户", "where", ("select", "where", "null"),
             "返回 email 和 phone 都是 NULL 的客户，依次输出 customer_id、name。"
             "customer_id 为主键；name 非空但可重复；email、phone 可为 NULL 或空字符串，"
             "空字符串不算 NULL。不要求行顺序。",
             "SELECT customer_id, name FROM customers WHERE /* 补充条件 */;",
             (Table("customers", (("customer_id", "INTEGER"), ("name", "TEXT"),
                                  ("email", "TEXT"), ("phone", "TEXT")),
                    "PRIMARY KEY (customer_id), CHECK (name IS NOT NULL)"),),
             "SELECT customer_id, name FROM customers WHERE email IS NULL AND phone IS NULL"),
        Task("distinct_cities", "城市名单保留未知项", "distinct", ("select", "distinct", "null"),
             "从 customers 输出一列 city，每个不同城市只出现一次；若存在 NULL，也保留一个 NULL。"
             "customer_id 为主键；city 可重复、可为 NULL 或空字符串，空字符串与 NULL 不同。"
             "不要求行顺序。",
             "SELECT /* 补充投影 */ FROM customers;",
             (Table("customers", (("customer_id", "INTEGER"), ("city", "TEXT")),
                    "PRIMARY KEY (customer_id)"),),
             "SELECT DISTINCT city FROM customers"),
        Task("group_counts", "统计各渠道访问次数", "aggregate", ("select", "aggregate", "null"),
             "按 channel 分组，依次输出 channel、访问行数 visit_count；包括 NULL 渠道组。"
             "visit_id 为主键；channel 是可重复、可为 NULL 的文本。计数每条访问，不是非空渠道数。"
             "不要求行顺序。",
             "SELECT channel, /* 补充计数 */ FROM visits GROUP BY channel;",
             (Table("visits", (("visit_id", "INTEGER"), ("channel", "TEXT")),
                    "PRIMARY KEY (visit_id)"),),
             "SELECT channel, COUNT(*) AS visit_count FROM visits GROUP BY channel"),
        Task("having_totals", "筛选募资总额达标小组", "aggregate", ("aggregate", "having", "null"),
             "按 team 汇总，保留 SUM(amount) 严格大于 100 的小组，依次输出 team、总额 total。"
             "pledge_id 为主键；team 为非空文本且可重复；amount 为非负整数或 NULL。"
             "重复金额也要累加，NULL 不参与求和；不要求行顺序。",
             "SELECT team, SUM(amount) AS total FROM pledges GROUP BY team HAVING /* 补充条件 */;",
             (Table("pledges", (("pledge_id", "INTEGER"), ("team", "TEXT"), ("amount", "INTEGER")),
                    "PRIMARY KEY (pledge_id), CHECK (team IS NOT NULL), CHECK (amount >= 0)"),),
             "SELECT team, SUM(amount) AS total FROM pledges GROUP BY team HAVING SUM(amount) > 100"),
        Task("inner_join_orders", "列出已付款订单的客户", "join", ("select", "join", "where"),
             "连接客户和订单，只返回 paid 订单，依次输出客户 name、订单 amount。"
             "每张符合条件的订单输出一行，重复结果也要保留；不要求行顺序。" + _JOIN_RULES,
             "SELECT c.name, o.amount FROM customers AS c JOIN orders AS o ON /* 补充条件 */;",
             (_CUSTOMERS, _ORDERS),
             "SELECT c.name, o.amount FROM customers c INNER JOIN orders o "
             "ON c.customer_id = o.customer_id WHERE o.status = 'paid'"),
        Task("left_join_counts", "保留零订单客户的计数", "join", ("join", "aggregate", "null"),
             "返回每位客户的 customer_id、订单数 order_count（所有状态都计数）。"
             "无订单客户也要返回，计数为 0；不要求行顺序。" + _JOIN_RULES,
             "SELECT c.customer_id, /* 补充计数 */ FROM customers c LEFT JOIN orders o "
             "ON c.customer_id = o.customer_id GROUP BY c.customer_id;",
             (_CUSTOMERS, _ORDERS),
             "SELECT c.customer_id, COUNT(o.order_id) AS order_count FROM customers c "
             "LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id"),
        Task("left_join_filter", "保留没有已付款订单的客户", "join", ("join", "where", "null"),
             "依次输出每位客户的 customer_id、其 paid 订单的 order_id。"
             "有多张 paid 订单时逐张输出；没有 paid 订单时仍输出一行且 order_id 为 NULL，"
             "包括只有未付款订单的客户。不要求行顺序。" + _JOIN_RULES,
             "SELECT c.customer_id, o.order_id FROM customers c LEFT JOIN orders o ON /* 补充条件 */;",
             (_CUSTOMERS, _ORDERS),
             "SELECT c.customer_id, o.order_id FROM customers c LEFT JOIN orders o "
             "ON c.customer_id = o.customer_id AND o.status = 'paid'"),
        Task("sum_totals", "汇总可空金额", "aggregate", ("select", "aggregate", "null"),
             "返回一行一列 total：line_items.amount 的 SUM。line_id 为主键；"
             "amount 为非负整数或 NULL，重复金额逐行相加；忽略 NULL；"
             "空表或全为 NULL 时结果是 NULL（不是 0）。不要求行顺序。",
             "SELECT /* 补充聚合 */ AS total FROM line_items;",
             (Table("line_items", (("line_id", "INTEGER"), ("amount", "INTEGER")),
                    "PRIMARY KEY (line_id), CHECK (amount >= 0)"),),
             "SELECT SUM(amount) AS total FROM line_items"),
        Task("order_top", "稳定选出评分前三产品", "select", ("select", "order", "limit", "null"),
             "依次输出 product_id、name、score，按 score 降序（NULL 放最后），"
             "同分时按 product_id 升序，最多返回前三行，严格遵守此行顺序。"
             "product_id 为主键；name 是非空可重复文本；score 为 0 到 100 的整数或 NULL。",
             "SELECT product_id, name, score FROM products ORDER BY /* 补充排序 */ LIMIT 3;",
             (Table("products", (("product_id", "INTEGER"), ("name", "TEXT"), ("score", "INTEGER")),
                    "PRIMARY KEY (product_id), CHECK (name IS NOT NULL), CHECK (score BETWEEN 0 AND 100)"),),
             "SELECT product_id, name, score FROM products ORDER BY score DESC, product_id ASC LIMIT 3",
             ordered=True),
    )
}


def _get_task(task_id: str) -> Task:
    if not isinstance(task_id, str) or task_id not in _TASKS:
        raise ValueError("unknown_task")
    return _TASKS[task_id]


def public_tasks() -> list[dict]:
    return [{"id": t.id, "title": t.title, "topic": t.topic, "concepts": list(t.concepts)}
            for t in _TASKS.values()]


def _validate_dataset_args(scenario: str, seed: int) -> None:
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise ValueError("invalid_scenario")
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("invalid_seed")


def _dataset(task_id: str, scenario: str = "sample", seed: int = 0) -> dict:
    task = _get_task(task_id)
    _validate_dataset_args(scenario, seed)
    rng = random.Random(int.from_bytes(sha256(f"{VERSION}:{task_id}:{seed}".encode()).digest(), "big"))
    rows: dict[str, list[list]] = {table.name: [] for table in task.tables}

    def fill(name: str, values: list[tuple]) -> None:
        keys = rng.sample(range(10, 100000), len(values))
        rows[name] = [[key, *value] for key, value in zip(keys, values)]

    high = rng.randint(130, 230)
    repeats = rng.randint(4, 8)
    if scenario != "empty":
        if task_id == "filter_paid":
            values = {
                "sample": [("paid", high), ("pending", high), ("paid", rng.randint(1, 90))],
                "boundary": [("paid", 99), ("paid", 100), ("paid", 101), ("paid", 0),
                             ("paid", high), ("cancelled", high), ("pending", 100)],
                "duplicates": [("paid", 100)] * repeats + [("pending", 100)] * 2 + [("paid", high)],
            }[scenario]
            fill("orders", values)
        elif task_id == "null_contacts":
            values = {
                "sample": [("林舟", None, None)] * (repeats % 3 + 1)
                          + [("青禾", "q@example.invalid", "100"), ("山岚", None, "200")],
                "boundary": [("林舟", None, None)] * (repeats % 3 + 1)
                            + [("青禾", "", None), ("山岚", None, ""),
                               ("空串", "", ""), ("单边", "a@example.invalid", None)],
                "duplicates": [("同名", None, None)] * repeats + [("同名", "", None)] * 2,
            }[scenario]
            fill("customers", values)
        elif task_id == "distinct_cities":
            extra_city = rng.choice(("松浦", "溪谷", "石湾"))
            cities = {
                "sample": ["青屿", "云港", "青屿", None] + [extra_city] * repeats,
                "boundary": [""] * repeats + [None, None, extra_city],
                "duplicates": ["青屿"] * repeats + [None] * repeats + [extra_city] * 2,
            }[scenario]
            fill("customers", [(city,) for city in cities])
        elif task_id == "group_counts":
            channels = {
                "sample": ["直访"] * repeats + ["邮件", "邮件", "伙伴"],
                "boundary": [None] * repeats + ["", "", "直访"],
                "duplicates": ["直访"] * (repeats * 3) + [None] * repeats + ["邮件"] * 2,
            }[scenario]
            fill("visits", [(channel,) for channel in channels])
        elif task_id == "having_totals":
            values = {
                "sample": [("潮声", high), ("潮声", 10), ("林间", 30), ("林间", 20)],
                "boundary": [("正好", 40), ("正好", 60), ("超出", 50), ("超出", 51),
                             ("未达", 99), ("未知", None), ("零元", 0), ("浮动", high)],
                "duplicates": [("同额", 60)] * repeats + [("未知", None)] * 2 + [("小额", 10)],
            }[scenario]
            fill("pledges", values)
        elif task_id in ("inner_join_orders", "left_join_counts", "left_join_filter"):
            fill("customers", [("同名" if scenario == "duplicates" else name,)
                               for name in ("林舟", "青禾", "山岚", "潮声")])
            ids = [row[0] for row in rows["customers"]]
            if scenario == "sample":
                # Every customer has a paid order here; the boundary reveals WHERE/ON mistakes.
                values = [(key, "paid", high + i * 7) for i, key in enumerate(ids)]
                values += [(ids[0], "paid", high)] * (repeats % 3 + 1)
                if task_id == "inner_join_orders":
                    values.append((ids[0], "pending", 40))
            elif scenario == "boundary":
                values = [(ids[0], "paid", 100), (ids[0], "paid", 0),
                          (ids[1], "pending", high), (ids[1], "cancelled", 10)]
                values += [(ids[0], "paid", high)] * (repeats % 3 + 1)
            else:
                values = [(ids[0], "paid", 60)] * repeats + [(ids[1], "paid", 60)] * 2
                values += [(ids[2], "pending", 60)] * repeats
            fill("orders", values)
        elif task_id == "sum_totals":
            amounts = {"sample": [high, rng.randint(1, 90), None, 0],
                       "boundary": [None] * repeats,
                       "duplicates": [60] * repeats + [None] * 2 + [0]}[scenario]
            fill("line_items", [(amount,) for amount in amounts])
        elif task_id == "order_top":
            scores = {"sample": [99, 80, 65, rng.randint(1, 60), None],
                      "boundary": [100] + [rng.randint(40, 80)] * repeats + [0, None],
                      "duplicates": [rng.randint(10, 70)] * repeats + [None] * 2}[scenario]
            fill("products", [("同款" if scenario == "duplicates" else f"原型{i}", score)
                              for i, score in enumerate(scores)])
        for table_rows in rows.values():
            rng.shuffle(table_rows)
    return {"task_id": task_id, "scenario": scenario, "seed": seed,
            "tables": [table.view(rows[table.name]) for table in task.tables]}


def task_view(task_id: str) -> dict:
    task = _get_task(task_id)
    return {"id": task.id, "title": task.title, "prompt": task.prompt, "topic": task.topic,
            "concepts": list(task.concepts), "starter_sql": task.starter_sql, "dialect": "sqlite",
            "version": VERSION, "tables": _dataset(task_id)["tables"], "ordered": task.ordered}
