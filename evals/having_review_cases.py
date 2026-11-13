"""Frozen developer-authored HAVING prompts, separate from the tuning suite."""

from course_content.sql_fixtures import GROUPING_FIXTURE, GROUPING_VARIANT


CASES = (
    ("having-01", GROUPING_FIXTURE, "请用 HAVING >= 2 演示。我想知道结果表中的每一行到底代表一个包裹还是一个类别。", "group_rows"),
    ("having-02", GROUPING_VARIANT, "用 HAVING > 2。A 有多条包裹，但结果只出现 A 一行，这是为什么？", "group_rows"),
    ("having-03", GROUPING_FIXTURE, "用 HAVING > 1。如果 B 和 C 的计数一样，查询会把两个类别合成一行吗？", "group_rows"),
    ("having-04", GROUPING_FIXTURE, "用 HAVING > 2。B 恰好有两条，我以为过了门槛。它为什么会被排除？", "threshold"),
    ("having-05", GROUPING_VARIANT, "用 HAVING >= 4。最大组的数量正好是 4，这样结果是空表吗？", "threshold"),
    ("having-06", GROUPING_VARIANT, "用 HAVING > 0。边界条件会把只有一条记录的分组过滤掉吗？", "threshold"),
    ("having-07", GROUPING_FIXTURE, "用 HAVING >= 2。我先用 WHERE 删除 B 的一条包裹，聚合是用删之前还是删之后的数量？", "where_having"),
    ("having-08", GROUPING_VARIANT, "用 HAVING > 1。WHERE 可以直接拿还没算好的 COUNT(*) 来筛吗？", "where_having"),
    ("having-09", GROUPING_FIXTURE, "用 HAVING > 3。我想先排除某些原始包裹，应该在哪个阶段过滤？", "where_having"),
)
