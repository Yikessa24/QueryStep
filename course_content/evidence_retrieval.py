"""Track explicit course claims through a bounded retrieval pass."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import re
from unicodedata import normalize

from course_content.knowledge_index import OUT_OF_SCOPE

CANDIDATES_PER_QUERY = 6
FINAL_LIMIT = 3


@dataclass(frozen=True)
class Concept:
    topic: str
    title: str
    cue: str
    pattern: str
    passages: tuple[str, ...]


CONCEPTS = {
    "left_join_unmatched": Concept("join", "左连接保留未匹配行", "LEFT JOIN 未匹配的左表行 补 NULL",
        r"left\s+(?:outer\s+)?join|外连接|左连接|左表|未匹配|没配对|未配对", ("left-join/preserves-left", "left-join/match-condition")),
    "join_predicate": Concept("join", "右表条件放在 ON 与 WHERE 的区别", "LEFT JOIN ON WHERE 右表条件 补出的行被过滤",
        r"(?=.*(?:\bon\b|左连接|left\s+join|右表|右侧))(?=.*(?:\bwhere\b|挪|搬|移到|位置|筛选位置))", ("where-after-join/predicate-placement",)),
    "join_same_result": Concept("join", "两种连接条件何时给出相同结果", "ON WHERE 两种写法 相同 所有左表行都能匹配",
        r"相同|一致|没区别|没变|一样|相等", ("where-after-join/matching-only",)),
    "count_star": Concept("aggregate", "COUNT(*) 统计所有结果行", "COUNT(*) 所有输入行 补出的 NULL 行也计数",
        r"count\s*\(\s*\*\s*\)|星号计数|星号|总行数|总结果行|所有结果行|总人数|数行|数所有|多少.*(?:条|行)|统计.*总数", ("count/row-count",)),
    "count_column": Concept("aggregate", "COUNT(列) 跳过 NULL", "COUNT(列) COUNT(column) 只统计非空值 右表主键",
        r"count\s*\(\s*[^*)]+\)|主键.{0,8}计数|数.{0,8}(?:邮箱|编号|主键|\bid\b)|非空.{0,4}计数|传入.{0,10}列", ("count/column-count",)),
    "null_compare": Concept("null", "用 IS NULL 判断空值", "IS NULL 判断空值 等号比较 未知",
        r"is\s+null|=\s*null|等号|null.{0,6}比较|怎么比较|筛.{0,8}(?:null|空值|未知|没填|没有填)|条件.{0,8}未知|真正没有填", ("null/compare",)),
    "null_meaning": Concept("null", "NULL 与零或空字符串的区别", "NULL 表示缺失或未知 与 0 空字符串不同",
        r"空字符串|空文本|数字零|填了零|填.*(?:和|成)\s*0|\bnull\b.{0,6}意思|空和零", ("null/unknown",)),
    "group_count": Concept("aggregate", "GROUP BY 按组计数", "GROUP BY 分类 每组计数 一行代表一组",
        r"group\s+by|每类一行|每类有几条|每一行代表|每一组|分组计数|按.{0,10}(?:汇总|分别数|归到一起)", ("grouping/group-count",)),
    "group_filter_order": Concept("aggregate", "WHERE 与 HAVING 的筛选顺序", "WHERE 先筛输入行 HAVING 后筛聚合组",
        r"\bwhere\b|先.{0,14}(?:只看|挑|输入中|删掉)|两次筛选", ("grouping/filter-order",)),
    "having_boundary": Concept("aggregate", "HAVING 的严格与包含边界", "HAVING COUNT(*) > >= 恰好等于阈值",
        r">=|严格大于|大于等于|(?:恰好|刚好|正好|至少|超过|达到).{0,12}(?:[0-9]|[一二两三四五六七八九十]|门槛|等于)", ("having/strict-inclusive",)),
    "distinct_null": Concept("distinct", "DISTINCT 如何判定重复的 NULL", "DISTINCT 去重 两个 NULL 作为相同值",
        r"(?=.*(?:distinct|去重|判重))(?=.*(?:null|空值|空邮箱|缺失|空格子))", ("distinct/null",)),
    "distinct_rows": Concept("distinct", "DISTINCT 按整个输出行去重", "DISTINCT 比较输出行全部列 组合去重",
        r"distinct|去重|重复输出", ("distinct/whole-row",)),
    "projection_rows": Concept("select", "投影保留输入行", "普通 SELECT 投影 只选列 保留重复行 两条记录",
        r"\bselect\b|投影|输出只要|只选", ("select-projection/rows",)),
    "union": Concept("set_ops", "UNION 合并结果并去重", "UNION 合并两边 结果去重",
        r"\bunion\b|合并|合在一起", ("set-operations/union",)),
    "except": Concept("set_ops", "EXCEPT 只保留左侧独有的行", "EXCEPT 保留左侧有右侧没有的行 交换顺序",
        r"\bexcept\b|(?:只想查|只留|只看|也想看).{0,24}(?:没有|没开)|交换左右", ("set-operations/except",)),
    "exists": Concept("subquery", "EXISTS 检查是否有结果行", "EXISTS 子查询 至少返回一行 存在判断",
        r"\bexists\b|有没有.{0,7}(?:行|记|作品)|任意一条记录|有记录吗", ("subqueries/exists",)),
    "in": Concept("subquery", "IN 检查集合成员", "IN 子查询 判断值是否属于名单 集合成员",
        r"\bin\b|名单里|属于|名单中|放进.{0,10}名单", ("subqueries/in",)),
}

# Only recognized compositional pairs activate the feature. The two goals can be
# in the same sentence or in different clauses of the student question.
PAIRS = (
    ("join_same_result", "left_join_unmatched"),
    ("join_predicate", "count_star"),
    ("left_join_unmatched", "count_column"),
    ("left_join_unmatched", "count_star"),
    ("distinct_null", "null_compare"),
    ("null_compare", "null_meaning"),
    ("count_star", "count_column"),
    ("group_filter_order", "having_boundary"),
    ("group_count", "having_boundary"),
    ("projection_rows", "distinct_rows"),
    ("union", "except"),
    ("exists", "in"),
)

MUTATIONS = re.compile(r"\b(?:drop|delete|truncate|alter)\s+table\b")


def split_concepts(question):
    text = normalize("NFKC", question).casefold()
    if MUTATIONS.search(text) or OUT_OF_SCOPE.search(text):
        return ()
    matches = {key for key, concept in CONCEPTS.items() if re.search(concept.pattern, text)}
    for pair in PAIRS:
        if not set(pair) <= matches:
            continue
        if pair[0] == "join_same_result" and not matches & {"join_predicate", "left_join_unmatched"}:
            continue
        if pair == ("group_filter_order", "having_boundary") and "join_predicate" in matches:
            continue
        return pair
    return ()


def focus_query(question, concept):
    fragments = [piece.strip() for piece in re.split(r"[。？?；！!，,]", question) if piece.strip()]
    matching = [piece for piece in fragments if re.search(concept.pattern, piece, re.I)]
    return f"{concept.title} {' '.join(matching) if matching else question}"[:500]


def rank_union(results):
    cards, scores = {}, {}
    for result in results:
        for rank, card in enumerate(result["cards"], 1):
            identifier = card["id"]
            cards[identifier] = card
            scores[identifier] = scores.get(identifier, 0) + 1 / (60 + rank)
    return [cards[key] for key in sorted(cards, key=lambda key: (-scores[key], key))]


def retrieve_evidence(index, question, topic, mode="hybrid", *, strategy="targeted", goals=None):
    """Return a maximum of three cards and an auditable ledger of search passes."""
    goals = tuple(goals) if goals is not None else split_concepts(question)
    passes = []

    def search(query, hint, limit, goal=None, retry=False):
        result = index.search(query, hint, limit, mode)
        passes.append({"query": query, "topic": hint, "limit": limit, "goal": goal, "retry": retry,
                       "ids": [card["id"] for card in result["cards"]]})
        return result

    if strategy == "whole_budget":
        # Every query retains the entire question. Normalization and a domain hint
        # provide the extra full-query attempts with a total budget of 18 slots.
        normalized = normalize("NFKC", question).replace("`", "")
        queries = (question, f"SQLite SQL 查询规则 {normalized}"[:500], f"数据库查询 结果语义 {normalized}"[:500])
        results = [search(query, topic, CANDIDATES_PER_QUERY) for query in queries]
        return {**results[0], "cards": rank_union(results)[:FINAL_LIMIT], "coverage": [], "passes": passes}
    if strategy == "whole" or len(goals) != 2:
        result = search(question, topic, FINAL_LIMIT)
        return {**result, "coverage": [], "passes": passes}

    # Preserve pass ordering even when the lexical/vector queries finish in a different order.
    request = [(focus_query(question, CONCEPTS[key]), CONCEPTS[key].topic) for key in goals]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda job: index.search(*job, CANDIDATES_PER_QUERY, mode), request))
    for (query, hint), key, result in zip(request, goals, results, strict=True):
        passes.append({"query": query, "topic": hint, "limit": CANDIDATES_PER_QUERY, "goal": key, "retry": False,
                       "ids": [card["id"] for card in result["cards"]]})
    ranked = rank_union(results)

    def covered(key):
        known = CONCEPTS[key].passages
        return next((card for card in ranked if card["id"] in known), None)

    missing = [key for key in goals if covered(key) is None]
    if missing and strategy == "targeted":
        key = missing[0]
        concept = CONCEPTS[key]
        results.append(search(concept.cue, concept.topic, CANDIDATES_PER_QUERY, key, retry=True))
        ranked = rank_union(results)

    selected = {card["id"]: card for key in goals if (card := covered(key)) is not None}
    coverage = [{"goal": key, "title": CONCEPTS[key].title, "card_id": card["id"] if (card := covered(key)) else None}
                for key in goals]
    # Keep relevant context alongside matched claims. If both claims are missing,
    # let the caller report the evidence gap without presenting unrelated cards.
    if selected:
        for card in ranked:
            if len(selected) >= FINAL_LIMIT:
                break
            selected.setdefault(card["id"], card)
    return {**results[0], "cards": list(selected.values()), "coverage": coverage, "passes": passes}
