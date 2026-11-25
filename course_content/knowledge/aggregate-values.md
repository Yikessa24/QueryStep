---
{
  "id": "aggregate-values",
  "version": 1,
  "topic": "aggregate",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_aggfunc.html",
  "source_section": "Built-in Aggregate Functions: count(X), min(X), max(X)",
  "reviewed_on": "2026-11-25"
}
---
# 聚合列值与去重计数

## min-null | MIN 忽略 NULL 并取得最小的非空值
<!-- keywords: MIN, 最小值, 最小分数, COUNT 加 MIN, 同时计算, 聚合结果列, 空值, 数值空着, 全空 -->
MIN 和 COUNT 可以在一个 SELECT 列表里各自返回一列。MIN 找最小的非空值，全部输入为空值时结果为 NULL。COUNT(列) 则返回非空值的数量。

```sql
WITH measures(v) AS (VALUES (NULL), (8), (2)) SELECT count(v), min(v) FROM measures;
```

## count-distinct | COUNT(DISTINCT 列) 统计不同的非空值
<!-- keywords: COUNT DISTINCT, 唯一人数, 唯一标识, 去重计数, 重复记录, 人头数 -->
如果一人可能有多条记录，COUNT(列) 会重复计入相同标识。COUNT(DISTINCT 列) 会合并相同的非空标识。选列前先确认要数的是人还是事件。

```sql
WITH visits(person) AS (VALUES (10), (10), (20), (NULL)) SELECT count(person), count(DISTINCT person) FROM visits;
```
