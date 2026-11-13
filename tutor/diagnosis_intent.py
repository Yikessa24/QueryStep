"""Map clear questions to reviewed SQL experiments and ask about ambiguous ones."""

from dataclasses import dataclass
import re
from unicodedata import normalize


@dataclass(frozen=True)
class ExperimentIntent:
    query_id: str | None
    min_count: int | None = None
    clarification: str | None = None


COMPARATOR = r">=|<=|<>|!=|>|<|=|≥|≤|严格大于|大于等于|大于或等于|大于|至少|不少于|不超过|小于等于|小于|等于"
NUMBER = r"[+\-−]?\s*\d+(?:[.,]\d+)?"
SQL_CONDITION = re.compile(rf"(?:\bhaving\b\s*(?:count\s*\(\s*\*\s*\)\s*)?|\bcount\s*\(\s*\*\s*\)\s*)"
                           rf"(?P<operator>{COMPARATOR})\s*(?P<number>{NUMBER})?(?!\s*[0-9])")
WORD_CONDITION = re.compile(rf"(?P<operator>严格大于|大于等于|大于或等于|大于|至少|不少于)\s*(?P<number>{NUMBER})")
ALTERNATIVE_CONDITION = re.compile(rf"(?:还是|或(?:者)?|\bor\b|与|对比|比较)\s*"
                                   rf"(?P<operator>{COMPARATOR})\s*(?P<number>{NUMBER})?")
UNSUPPORTED_SQL = re.compile(r"\bhaving\s+(?:sum|avg|min|max|count)\s*\((?!\s*\*\s*\))|"
                             r"\bcount\s*\((?!\s*\*\s*\))[^)]*\)\s*(?:[<>!=]|≥|≤)|"
                             r"\bhaving\s+(?:count\s*\(\s*\*\s*\)\s*)?(?:between\b|is\b|not\b|[!<>=]{3,}|=>|==|=<|>>)")
COMPOUND = re.compile(r"^\s*(?:and\b|or\b|&&|\|\||且|并且|或者|或|以及)")
JOIN_SCOPE = re.compile(r"\b(?:inner|right|full|cross)\s+(?:outer\s+)?join\b|内连接|右连接|全外连接|交叉连接")


def _thresholds(matches, text):
    conditions = set()
    for match in matches:
        operator = match["operator"]
        number = (match["number"] or "").replace(" ", "")
        suffix = text[match.end():]
        if (not number.isdecimal() or len(number) > 2 or int(number) > 50 or COMPOUND.match(suffix)
                or re.match(r"\s*(?:[<>!=+*/%]|-\s*\d)", suffix)):
            return None
        if operator in (">", "大于", "严格大于"):
            conditions.add(("having_gt", int(number)))
        elif operator in (">=", "≥", "大于等于", "大于或等于", "至少", "不少于"):
            conditions.add(("having_gte", int(number)))
        else:
            return None
    return conditions


def route_experiment(message: str, topic: str) -> ExperimentIntent:
    text = normalize("NFKC", message).casefold().replace("`", "")
    if topic == "join":
        named_positions = re.search(r"\bon\b", text) and re.search(r"\bwhere\b", text)
        moves_order_filter = re.search(r"订单|付款", text) and re.search(r"移动|移到|改到|条件位置", text)
        compares_left_join = (re.search(r"\bleft\s+(?:outer\s+)?join\b|左连接", text)
                              and re.search(r"对比条件位置|比较条件位置", text))
        filters = re.findall(r"(?:status\b|状态)\s*([<>!=]+|为|\bis\b|\bin\b)\s*['\"]?([\w-]*)", text)
        unsupported_filter = any(operator not in ("=", "为") or value != "paid" for operator, value in filters)
        if (named_positions or moves_order_filter or compares_left_join) and not (JOIN_SCOPE.search(text) or unsupported_filter):
            return ExperimentIntent("join_where")
        return ExperimentIntent(None, clarification="是否用示例对比 LEFT JOIN 的付款条件放在 ON 和 WHERE 时的差异？")

    clarification = ExperimentIntent(None, clarification="请选择一个 COUNT(*) 筛选条件，并填写 0 到 50 的整数阈值。")
    sql_conditions = _thresholds(SQL_CONDITION.finditer(text), text)
    word_conditions = _thresholds(WORD_CONDITION.finditer(text), text)
    alternatives = _thresholds(ALTERNATIVE_CONDITION.finditer(text), text)
    if (sql_conditions is None or word_conditions is None or alternatives is None or UNSUPPORTED_SQL.search(text)
            or re.search(r"不(?:严格)?大于|(?:不要|别|取消)\s*(?:执行|运行|用)\s*(?:having\b|count\b|(?:严格)?大于)", text)):
        return clarification
    choices = sql_conditions | word_conditions
    if len(choices) == 1 and alternatives <= choices:
        query, min_count = choices.pop()
        return ExperimentIntent(query, min_count)
    return clarification
