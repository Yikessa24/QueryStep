---
{
  "id": "grouping",
  "version": 2,
  "topic": "aggregate",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#resultset",
  "source_section": "2.4 Generation of the set of result rows",
  "reviewed_on": "2026-11-25"
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


## output-groups | GROUP BY 的输出行数通常是保留的组数
<!-- keywords: GROUP BY, 几组, 结果多少行, 聚合行数, 组数, 一组一行, 分组结果 -->
先按分组键把输入记录放进组里，再检查 HAVING 保留哪些组。每个保留的组贡献一条结果行。组内的 COUNT(*) 是该组的输入行数，可以与最终结果的组数不同。

```sql
WITH marks(color) AS (VALUES ('red'), ('red'), ('blue')) SELECT color, count(*) FROM marks GROUP BY color ORDER BY color;
```
