---
{
  "id": "having",
  "version": 1,
  "topic": "aggregate",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#resultset",
  "source_section": "2.4 Generation of the set of result rows",
  "reviewed_on": "2026-11-14"
}
---
# HAVING 与计数边界

## filter-groups | HAVING 根据聚合结果筛选分组
<!-- keywords: HAVING, COUNT(*), 分组, 阈值, 聚合条件 -->
<!-- experiment: having_boundary -->
HAVING COUNT(*) > 2 的意思是，只保留输入记录多于两条的组。先为每个组计算 COUNT(*)，再决定哪些组出现在结果里。

## strict-inclusive | 严格大于与大于等于
<!-- keywords: HAVING, >, >=, COUNT(*), 阈值, 恰好等于, 至少, 相同, 多于 -->
<!-- experiment: having_boundary -->
比较 HAVING COUNT(*) > 2 和 HAVING COUNT(*) >= 2 时，只有刚好两条记录的组在两种写法中的去留不同。如果当前没有这样的组，结果可能相同；加入一个计数正好为 2 的组即可观察差异。
