---
{
  "id": "subqueries",
  "version": 1,
  "topic": "subquery",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_expr.html#the_exists_operator",
  "source_section": "10. The EXISTS operator and 11. Subquery Expressions",
  "reviewed_on": "2026-11-14"
}
---
# 子查询与存在判断

## exists | EXISTS 检查是否至少返回一行
<!-- keywords: EXISTS, NOT EXISTS, 子查询, 相关, 存在 -->
把外层一行的键代进内层条件，看看是否有至少一行。EXISTS 只看有没有结果行。NOT EXISTS 在找不到匹配时为真。

## in | IN 查询一批可匹配值
<!-- keywords: IN, 子查询, 集合, 成员, NULL -->
先求子查询输出的一列，再确定外层值能否在其中找到。检查 NOT IN 时特别留意右侧是否包含 NULL，未知结果会影响筛选。
