---
{
  "id": "count",
  "version": 1,
  "topic": "aggregate",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_aggfunc.html#count",
  "source_section": "Descriptions of built-in aggregate functions",
  "reviewed_on": "2026-11-14"
}
---
# 聚合计数

## row-count | COUNT(*) 统计输入结果行
<!-- keywords: COUNT(*), 行数, 总人数, 左连接, 没借过书, NULL -->
<!-- experiment: join_count -->
COUNT(*) 对输入结果中的每一行加一。左连接补出的行也会计入，即使这一行的右侧值都是 NULL。一对多连接还可能重复左表记录。要统计唯一读者，先确认每人是否只占一行，再考虑按唯一标识去重。

## column-count | COUNT(列) 只统计非空列值
<!-- keywords: COUNT(column), COUNT(列), 非空, 有单人数, NULL, 计数 -->
<!-- experiment: join_count -->
COUNT(列) 对指定列非 NULL 的每一行加一。以左连接后的右表主键计数，未匹配行的右表键为 NULL，因此跳过；匹配行的右表主键则会被计入。
