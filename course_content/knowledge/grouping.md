---
{
  "id": "grouping",
  "version": 1,
  "topic": "aggregate",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#resultset",
  "source_section": "2.4 Generation of the set of result rows",
  "reviewed_on": "2026-11-14"
}
---
# 分组与聚合

## group-count | GROUP BY 为每组产生一个计数
<!-- keywords: GROUP BY, 分组, 每组, 聚合函数, 计数 -->
<!-- experiment: having_boundary -->
按类别分组后，COUNT(*) 分别统计每个类别里有多少条记录。结果中的一行表示一组。想知道筛选前的组数，可以先写 GROUP BY 并显示每组计数。

## filter-order | WHERE 先筛原始行，HAVING 再筛组
<!-- keywords: WHERE, HAVING, GROUP BY, 行筛选, 分组筛选, 先后 -->
WHERE 改变进入聚合的记录。HAVING 检查分组后的结果。比如先保留今年借阅的行，再判断哪些类别有至少三条今年的借阅记录。
