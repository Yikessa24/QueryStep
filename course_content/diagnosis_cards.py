"""Reviewed evidence cards for SQL diagnostics."""

import re


CARDS = (
    {
        "id": "aggregate-group-by",
        "version": 1,
        "topic": "aggregate",
        "title": "GROUP BY 形成分组",
        "section": "GROUP BY",
        "url": "https://www.postgresql.org/docs/18/tutorial-agg.html",
        "text": "GROUP BY 把分组键相同的行放进同一组，聚合函数对每组求值。每个保留的分组输出一行。",
    },
    {
        "id": "aggregate-having",
        "version": 1,
        "topic": "aggregate",
        "title": "HAVING 筛选分组",
        "section": "GROUP BY and HAVING",
        "url": "https://www.postgresql.org/docs/18/queries-table-expressions.html#QUERIES-GROUP",
        "text": "WHERE 在分组前筛选输入行，HAVING 在分组后筛选各组。COUNT(*) > 1 会排除只有一行的组。",
    },
    {
        "id": "aggregate-having-boundary",
        "version": 1,
        "topic": "aggregate",
        "title": "比较 HAVING 条件的边界",
        "section": "Aggregate Functions",
        "url": "https://www.postgresql.org/docs/18/tutorial-agg.html",
        "text": "先列出每组的计数，再检查严格大于和大于等于的边界。计数等于阈值的组只满足大于等于。",
    },
    {
        "id": "join-on-preserves-left",
        "version": 1,
        "topic": "join",
        "title": "LEFT JOIN 保留左表记录",
        "section": "Joined Tables",
        "url": "https://www.postgresql.org/docs/18/queries-table-expressions.html#QUERIES-JOIN",
        "text": "ON 决定哪些右表记录匹配。LEFT JOIN 为未匹配的左表行补上右表 NULL，仍保留左表行。",
    },
    {
        "id": "join-where-after",
        "version": 1,
        "topic": "join",
        "title": "WHERE 在连接之后筛选",
        "section": "The WHERE Clause",
        "url": "https://www.postgresql.org/docs/18/queries-table-expressions.html#QUERIES-WHERE",
        "text": "WHERE 在连接后只保留条件为真的结果行。右表字段是 NULL 时，等值比较不成立。",
    },
)


def search(query: str, topic: str, limit: int) -> list[dict]:
    terms = set(re.findall(r"[a-z_]+|[\u4e00-\u9fff]", query.lower()))
    ranked = []
    for card in CARDS:
        if card["topic"] != topic:
            continue
        title = set(re.findall(r"[a-z_]+|[\u4e00-\u9fff]", card["title"].lower()))
        body = set(re.findall(r"[a-z_]+|[\u4e00-\u9fff]", card["text"].lower()))
        score = 2 * len(terms & title) + len(terms & body)
        ranked.append({**card, "match_score": score})
    return sorted(ranked, key=lambda card: (-card["match_score"], card["id"]))[:limit]
