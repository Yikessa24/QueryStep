---
{
  "id": "where-filter",
  "version": 1,
  "topic": "where",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#whereclause",
  "source_section": "2.3 WHERE clause filtering",
  "reviewed_on": "2026-11-14"
}
---
# 按行筛选

## matching | WHERE 只保留条件为真的行
<!-- keywords: WHERE, 筛选, 行, 条件, NULL -->
WHERE 对每条输入行单独判断。符合条件的行留下，条件为假或未知时被过滤。只筛选输出数据，来源表本身仍保留这些记录。

## boundary | 试算一条恰好在阈值上的记录
<!-- keywords: WHERE, >=, >, 边界值, 大于等于 -->
比较大于和大于等于时先试算一个恰好等于阈值的值。比如气温门槛是 18，严格大于只接受比 18 高的记录。
