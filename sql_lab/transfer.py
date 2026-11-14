"""Build immutable exercise snapshots from reviewed SQL templates."""

import json
import re
from random import Random

from course_content.transfer_templates import HAVING_INCLUSIVE, QUESTION_TEMPLATES, fixture
from sql_lab.executor import LabError, select_fixture


def template_for(question_id, kcs, variant):
    mapping = QUESTION_TEMPLATES.get(question_id)
    if not mapping or mapping[0] != tuple(kcs):
        return None
    return HAVING_INCLUSIVE if question_id == 75 and variant == "inclusive" else mapping[1]


def _result(columns, rows, measure):
    if measure == "rows":
        return f"{len(rows)} 行"
    if measure == "shape":
        return f"{len(rows)} 行，{len(columns)} 列"
    if measure == "columns":
        return "、".join(columns)
    return "；".join(" / ".join("NULL" if value is None else str(value) for value in row)
                   for row in sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False))) or "无结果"


def build_transfer(question_id, kcs, seed, variant="standard"):
    template = template_for(question_id, kcs, variant)
    if template is None:
        raise LabError("unknown_transfer_mapping")
    rng = Random(seed)
    data = fixture(template.family, rng)
    tables = dict(zip("ab", data.tables))
    queries = [sql.format(**tables) for sql in (template.sql, *template.mistakes)]
    executed = select_fixture(data.tables, data.rows, [(sql, data.parameters) for sql in queries],
                              functions=frozenset({"count", "min", "max", "lower"}))
    options = [_result(columns, rows, template.measure) for columns, rows in executed]
    if len(set(options)) != 4:
        raise LabError("ambiguous_transfer_options")

    answer = options[0]
    rng.shuffle(options)
    contexts = {"rows": "这条查询会返回多少行？", "columns": "结果列按什么顺序显示？",
                "values": "查询会返回哪些值？下方选项按行列出结果，行之间用分号分隔。",
                "shape": "结果有多少行、多少列？"}

    def literal(match):
        value = data.parameters[match[1]]
        return "'" + value.replace("'", "''") + "'" if isinstance(value, str) else str(value)

    columns, rows = executed[0]
    return {"id": f"{template.concept}@2-{seed}", "concept": template.concept,
            "context": contexts[template.measure], "sql": re.sub(r":(\w+)", literal, queries[0]),
            "tables": [{"name": name, "columns": list(schema), "rows": list(map(list, data.rows[name]))}
                       for name, schema in data.tables.items()],
            "options": options, "correct_option": options.index(answer),
            "feedback": template.explanation, "result_columns": columns, "result_rows": rows}
