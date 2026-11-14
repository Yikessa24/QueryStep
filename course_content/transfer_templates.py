"""Reviewed synthetic SQL transfer templates. Each query has explicit wrong-query contrasts."""

from dataclasses import dataclass
from random import Random


@dataclass(frozen=True)
class Template:
    concept: str
    family: str
    sql: str
    mistakes: tuple[str, ...]
    measure: str
    explanation: str


@dataclass(frozen=True)
class Fixture:
    tables: dict
    rows: dict
    parameters: dict


def fixture(family: str, random: Random) -> Fixture:
    offset = random.choice((10, 20, 30, 40))
    if family == "orders":
        customer, order = random.choice((("libraries", "loans"), ("clubs", "registrations"), ("stores", "sales")))
        tables = {customer: {"site_id": "INTEGER", "zone": "TEXT"},
                  order: {"entry_id": "INTEGER", "site_id": "INTEGER", "zone": "TEXT", "period": "INTEGER"}}
        # Unmatched sites, an orphan entry, a second shared NATURAL JOIN key, and nonuniform multiplicity.
        rows = {customer: [(offset + 1, "east"), (offset + 2, "west"), (offset + 3, "east"), (offset + 4, "north")],
                order: [(offset+11, offset+1, "east", 1), (offset+12, offset+1, "west", 2),
                        (offset+13, offset+1, "east", 1), (offset+14, offset+2, "west", 1),
                        (offset+15, offset+2, "west", 2), (offset+16, offset+4, "north", 2), (offset+18, offset+2, "east", 2),
                        (offset+17, offset+9, "east", 1)]}
        if random.choice((False, True)):
            rows[customer].append((offset + 5, "south"))
        return Fixture(tables, rows, {"period": random.choice((1, 2)), "zone": "east"})
    table, first, second = random.choice((("tickets", "Mia", "Leo"), ("visits", "Ada", "Sam"), ("entries", "Eva", "Max")))
    tables = {table: {"entry_id": "INTEGER", "name": "TEXT", "category": "TEXT", "units": "INTEGER", "period": "INTEGER"}}
    rows = {table: [(offset+1, first, "A", offset+4, 1), (offset+2, first, "B", None, 1),
                    (offset+3, first.upper(), "A", offset+3, 2), (offset+4, second, "B", offset+1, 1),
                    (offset+5, second, "C", offset+2, 2), (offset+6, second.upper(), "B", offset+2, 2),
                    (offset+7, first.lower(), "B", offset+2, 1), (offset+8, first, "B", offset+3, 2)]}
    return Fixture(tables, rows, {"name": first, "other": second, "lower_name": first.lower(),
                                  "n": 2, "period": 1, "other_period": 2})


LEFT_JOIN = Template("left_join", "orders", "SELECT * FROM {a} a LEFT JOIN {b} b ON a.site_id=b.site_id",
                     ("SELECT * FROM {a} a INNER JOIN {b} b ON a.site_id=b.site_id",
                      "SELECT * FROM {a} a CROSS JOIN {b} b", "SELECT * FROM {a}"), "rows",
                     "LEFT JOIN 保留左表中没有匹配的记录，并为这样的记录补上右表 NULL。左表一条记录有多个匹配时，结果有多行。")

PROJECTION = Template("projection", "single", "SELECT name, category FROM {a}",
                      ("SELECT * FROM {a}", "SELECT name FROM {a}", "SELECT category, name FROM {a}"),
                      "columns", "SELECT 列表决定结果列及其顺序。")
STAR = Template("select_star", "single", "SELECT * FROM {a}",
                ("SELECT name, category FROM {a}", "SELECT entry_id FROM {a}", "SELECT units, period, name FROM {a}"),
                "columns", "星号展开为表的全部列，顺序按表结构。")
PROJECT_ROWS = Template("projection_rows", "single", "SELECT name, category FROM {a}",
                        ("SELECT DISTINCT name, category FROM {a}", "SELECT name, category FROM {a} WHERE period=:period",
                         "SELECT name, category FROM {a} GROUP BY category"),
                        "rows", "普通 SELECT 投影保留每条输入记录。选择列本身不会去重或筛行。")
EQUALITY = Template("equality", "single", "SELECT * FROM {a} WHERE name = :name",
                    ("SELECT * FROM {a} WHERE lower(name)=:lower_name", "SELECT * FROM {a} WHERE name=:lower_name", "SELECT * FROM {a}"),
                    "rows", "此处采用 SQLite 默认的文本比较。精确匹配区分大小写。")
CASE = Template("case_normalization", "single", "SELECT * FROM {a} WHERE lower(name)=:lower_name",
                ("SELECT * FROM {a} WHERE name=:name", "SELECT * FROM {a} WHERE name=:lower_name", "SELECT * FROM {a}"),
                "rows", "lower(name) 先把名称转成小写，比较时三种大小写写法都可匹配。")
DISTINCT = Template("distinct", "single", "SELECT DISTINCT category FROM {a}",
                    ("SELECT category FROM {a}", "SELECT DISTINCT category, period FROM {a}", "SELECT DISTINCT category FROM {a} WHERE period=:period"),
                    "rows", "DISTINCT 按一整条输出记录去重。这里只输出 category。")
LOGICAL_OR = Template("or_predicate", "single", "SELECT category FROM {a} WHERE name=:name OR period=:other_period",
                      ("SELECT category FROM {a} WHERE name=:name AND period=:other_period",
                       "SELECT category FROM {a} WHERE name=:name", "SELECT category FROM {a} WHERE period=:other_period"),
                      "rows", "OR 保留至少满足一个条件的输入行。")
COUNT = Template("count_rows", "single", "SELECT COUNT(*) FROM {a}",
                 ("SELECT COUNT(units) FROM {a}", "SELECT COUNT(DISTINCT category) FROM {a}", "SELECT COUNT(*) FROM {a} WHERE period=:period"),
                 "values", "COUNT(*) 统计所有输入行。COUNT(units) 只统计 units 非 NULL 的行。")
COUNT_MIN = Template("count_and_min", "single", "SELECT COUNT(units), MIN(units) FROM {a}",
                     ("SELECT COUNT(*), MIN(units) FROM {a}", "SELECT COUNT(units), MAX(units) FROM {a}", "SELECT MIN(units), COUNT(units) FROM {a}"),
                     "values", "COUNT(units) 跳过 NULL，MIN(units) 取最小的非 NULL 值。")
GROUP = Template("group_count", "single", "SELECT category, COUNT(*) FROM {a} GROUP BY category",
                 ("SELECT category, COUNT(*) FROM {a} GROUP BY name", "SELECT * FROM {a}", "SELECT COUNT(*) FROM {a}"),
                 "rows", "GROUP BY category 按类别分组，结果每组一行。")
HAVING = Template("having_count", "single", "SELECT category, COUNT(*) FROM {a} GROUP BY category HAVING COUNT(*) > :n",
                  ("SELECT category, COUNT(*) FROM {a} GROUP BY category HAVING COUNT(*) >= :n",
                   "SELECT category, COUNT(*) FROM {a} GROUP BY category",
                   "SELECT category, COUNT(*) FROM {a} GROUP BY category HAVING COUNT(*) > :n + 4"),
                  "rows", "HAVING 在分组后筛选。严格大于时，恰好等于阈值的组会被筛掉。")
HAVING_INCLUSIVE = Template("having_count", "single", HAVING.mistakes[0],
                            (HAVING.sql, HAVING.mistakes[1], HAVING.mistakes[2]), "rows",
                            "HAVING 在分组后筛选。大于等于时，恰好等于阈值的组也保留。")
UNION = Template("union", "single",
                 "SELECT category FROM {a} WHERE period=:period UNION SELECT category FROM {a} WHERE period=:other_period",
                 ("SELECT category FROM {a} WHERE period=:period UNION ALL SELECT category FROM {a} WHERE period=:other_period",
                  "SELECT category FROM {a} WHERE period=:period INTERSECT SELECT category FROM {a} WHERE period=:other_period",
                  "SELECT category FROM {a} WHERE period=:period EXCEPT SELECT category FROM {a} WHERE period=:other_period"),
                 "rows", "UNION 合并两侧结果，并去除重复行。")
EXCEPT = Template("except", "single",
                  "SELECT category FROM {a} WHERE period=:other_period EXCEPT SELECT category FROM {a} WHERE period=:period",
                  ("SELECT category FROM {a} WHERE period=:period EXCEPT SELECT category FROM {a} WHERE period=:other_period",
                   "SELECT category FROM {a} WHERE period=:other_period INTERSECT SELECT category FROM {a} WHERE period=:period",
                   "SELECT category FROM {a} WHERE period=:other_period UNION SELECT category FROM {a} WHERE period=:period"),
                  "rows", "EXCEPT 保留左侧有、右侧没有的行。交换顺序会改变含义。")
INNER = Template("inner_join", "orders", LEFT_JOIN.mistakes[0],
                 (LEFT_JOIN.sql, LEFT_JOIN.mistakes[1], "SELECT * FROM {a} a JOIN {b} b ON a.site_id=b.site_id AND a.zone=b.zone"),
                 "rows", "INNER JOIN 只保留满足连接条件的行对。每个匹配行对产生一行。")
CROSS = Template("cartesian_product", "orders", LEFT_JOIN.mistakes[1],
                 (INNER.sql, LEFT_JOIN.sql, "SELECT * FROM {a}"), "rows",
                 "CROSS JOIN 组合两张表的所有行对，结果行数是两表行数的乘积。")
NATURAL = Template("natural_join", "orders", "SELECT * FROM {a} NATURAL JOIN {b}",
                   (INNER.sql, LEFT_JOIN.sql, CROSS.sql), "rows",
                   "NATURAL JOIN 使用所有同名列匹配。这里 site_id 和 zone 都必须相等。")
JOIN_FILTER = Template("join_with_filter", "orders",
                       "SELECT * FROM {a} a, {b} b WHERE a.site_id=b.site_id AND b.period=:period",
                       (INNER.sql, "SELECT * FROM {a} a, {b} b WHERE b.period=:period", CROSS.sql), "rows",
                       "先识别键匹配的行对，再检查这些行对是否满足期次条件。")
EXISTS_MATCH = Template("exists_matching_entry", "orders",
                        "SELECT * FROM {b} b WHERE EXISTS (SELECT 1 FROM {a} a WHERE a.site_id=b.site_id)",
                        ("SELECT * FROM {b} b WHERE EXISTS (SELECT 1 FROM {a})",
                         "SELECT * FROM {b} b WHERE NOT EXISTS (SELECT 1 FROM {a} a WHERE a.site_id=b.site_id)",
                         "SELECT DISTINCT site_id FROM {b} b WHERE EXISTS (SELECT 1 FROM {a} a WHERE a.site_id=b.site_id)"),
                        "rows", "EXISTS 对外层的每条记录检查是否有匹配，保留原外层记录。")
EXISTS_SITE = Template("exists_matching_site", "orders",
                       "SELECT * FROM {a} a WHERE EXISTS (SELECT 1 FROM {b} b WHERE b.site_id=a.site_id)",
                       (INNER.sql, "SELECT * FROM {a} a WHERE EXISTS (SELECT 1 FROM {b})",
                        "SELECT * FROM {a} a WHERE NOT EXISTS (SELECT 1 FROM {b} b WHERE b.site_id=a.site_id)"),
                       "rows", "EXISTS 只检查是否有至少一个匹配。同一个站点即使有多个匹配也只输出一行。")
IN_QUERY = Template("in_subquery", "orders",
                    "SELECT * FROM {b} b WHERE b.site_id IN (SELECT a.site_id FROM {a} a WHERE a.zone=:zone)",
                    ("SELECT * FROM {b} b WHERE b.zone=:zone", "SELECT * FROM {b} b",
                     "SELECT * FROM {b} b WHERE b.site_id NOT IN (SELECT a.site_id FROM {a} a WHERE a.zone=:zone)"),
                    "rows", "子查询先给出符合区域条件的站点 ID，外层 IN 根据这批 ID 筛选记录。")
NOT_EXISTS = Template("not_exists", "orders",
                      "SELECT * FROM {a} a WHERE NOT EXISTS (SELECT 1 FROM {b} b WHERE b.site_id=a.site_id)",
                      (EXISTS_SITE.sql, "SELECT * FROM {a}", INNER.sql), "shape",
                      "NOT EXISTS 保留没有匹配的站点。SELECT * 输出外层表的全部列。")
FILTER_GROUP = Template("filter_then_group", "orders",
                        "SELECT site_id, COUNT(*) FROM {b} WHERE period=:period GROUP BY site_id",
                        ("SELECT site_id, COUNT(*) FROM {b} WHERE period=:period GROUP BY entry_id",
                         "SELECT site_id, COUNT(*) FROM {b} GROUP BY site_id",
                         "SELECT zone, COUNT(*) FROM {b} WHERE period=:period GROUP BY zone"),
                        "values", "WHERE 先保留指定期次的数据，GROUP BY 再按站点计算记录数。")

# Source KC tuples are reviewed together with the original SQL and question wording.
QUESTION_TEMPLATES = {
    57: ((29,), PROJECTION), 62: ((28, 33), INNER), 63: ((29,), STAR),
    64: ((29,), COUNT), 68: ((29,), PROJECT_ROWS), 69: ((29,), EQUALITY),
    70: ((29,), CASE), 71: ((35,), DISTINCT), 72: ((29,), LOGICAL_OR),
    73: ((29, 37, 38), COUNT_MIN), 74: ((29, 36, 37), GROUP), 75: ((29, 36, 39), HAVING),
    76: ((9, 29), UNION), 77: ((29, 40), EXCEPT), 78: ((29,), CROSS),
    79: ((29, 41), INNER), 80: ((29, 42), NATURAL), 81: ((29, 43), LEFT_JOIN),
    82: ((29,), JOIN_FILTER), 83: ((29, 44), EXISTS_MATCH), 84: ((29, 44), EXISTS_SITE),
    85: ((29, 32), IN_QUERY), 86: ((29, 32, 44), NOT_EXISTS), 87: ((29, 36), FILTER_GROUP),
}
