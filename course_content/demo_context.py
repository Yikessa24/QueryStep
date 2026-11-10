"""Synthetic relation rows for DBE-KT22 questions with missing table context."""

STUDY = (
    ("StudentID", "Name", "CourseNo", "Units"),
    (101, "Tom", "COMP2400", 6),
    (102, "Mei", "COMP2400", 6),
    (102, "Mei", "STAT2001", 6),
    (103, "Lin", "COMP2400", 4),
    (103, "Lin", "HIST1010", 6),
    (104, "TOM", "STAT2001", 6),
)

COURSE = (
    ("CourseNo", "CourseName"),
    ("COMP2400", "Relational Databases"),
    ("STAT2001", "Statistics"),
    ("HIST1010", "World History"),
    ("LING1010", "Linguistics"),
)

ENROL = (
    ("StudentID", "CourseNo", "Year"),
    (101, "COMP2400", 2018),
    (102, "COMP2400", 2019),
    (101, "STAT2001", 2018),
    (103, "STAT2001", 2019),
    (104, "STAT2001", 2019),
    (102, "HIST1010", 2018),
    (104, "HIST1010", 2019),
)


def demo_tables(question_id: int) -> dict:
    if 68 <= question_id <= 77:
        return {"Study": STUDY}
    if 78 <= question_id <= 86:
        return {"Course": COURSE, "Enrol": ENROL}
    return {}


def with_demo_context(question_id: int, prompt: str) -> str:
    tables = demo_tables(question_id)
    if not tables:
        return prompt
    if question_id == 85:
        prompt = prompt.translate(str.maketrans("‘’", "''"))
    parts = [prompt, "演示用表数据（合成）"]
    for name, rows in tables.items():
        parts.append("\n".join([name, *(" | ".join(map(str, row)) for row in rows)]))
    return "\n\n".join(parts)
