"""Reviewed SQL snippets keyed by the server's course topics."""

NOTES = {
    "select": "SELECT 后的表达式决定结果列，FROM 指定数据来源。",
    "where": "WHERE 对每一行检查条件，只保留条件为真的行。先用边界值试算。",
    "conditions": "AND 要求两项同时成立，OR 只要求至少一项成立。用括号明确分组。",
    "distinct": "DISTINCT 对整个结果行去重。选择多列时，逐列相同才算重复。",
    "aggregate": "先确定每组有哪些行。聚合函数为每组求值，HAVING 按聚合条件筛选组。",
    "set_ops": "先分别求两个查询的结果。UNION 合并并去重，EXCEPT 保留只在左侧出现的行。",
    "join": "JOIN 根据连接条件组合两张表的行。先区分匹配和未匹配的情况。",
    "subquery": "先用一行外层记录试算子查询。EXISTS 检查是否至少返回一行，IN 检查值是否出现在结果中。",
}

EXAMPLES = {
    "select": "水果表有 name 和 weight 两列。只选 name 时，结果里只有一列。",
    "where": "三个气温值是 12、18、20。筛选严格低于 18 的记录时，只保留 12。",
    "conditions": "记录甲只满足第一个条件，记录乙同时满足两个。AND 留下乙，OR 两条都留下。",
    "distinct": "三个结果行是 (蓝, 大)、(蓝, 大)、(蓝, 小)。去重后有两个结果行。",
    "aggregate": "果篮 A 有三条记录，果篮 B 有一条。按果篮分组后，HAVING COUNT(*) > 1 只保留 A 组。",
    "set_ops": "左侧结果是 1、2，右侧结果是 2、3。UNION 得到 1、2、3，EXCEPT 得到 1。",
    "join": "两张独立表的键分别是 1、2 和 2、3。等值内连接只有键 2 能匹配。",
    "subquery": "两种商品的编号是 1、2，订单里只有编号 2。对每种商品查询匹配订单时，只有 2 满足 EXISTS。",
}

DOCS = {
    "select": "tutorial-select.html",
    "where": "tutorial-select.html",
    "conditions": "functions-logical.html",
    "distinct": "queries-select-lists.html#QUERIES-DISTINCT",
    "aggregate": "tutorial-agg.html",
    "set_ops": "queries-union.html",
    "join": "tutorial-join.html",
    "subquery": "functions-subquery.html",
}


def retrieve_note(topic: str) -> dict:
    return {"id": f"note-{topic}", "title": "课程规则", "text": NOTES[topic],
            "url": f"https://www.postgresql.org/docs/18/{DOCS[topic]}"}
