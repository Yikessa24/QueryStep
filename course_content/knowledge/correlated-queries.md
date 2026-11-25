---
{
  "id": "correlated-queries",
  "version": 1,
  "topic": "subquery",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_expr.html#correlated_subqueries",
  "source_section": "8. IN and NOT IN, 10. EXISTS and 12. Correlated Subqueries",
  "reviewed_on": "2026-11-25"
}
---
# 相关子查询与反查

## outer-key | 相关子查询用当前外层行的键查是否匹配
<!-- keywords: 相关子查询, 外层别名, 当前外层行, 从哪张表数, 调换内外表, EXISTS 单行多匹配 -->
先确定外层 FROM 决定要检查哪批行，再把当前外层行的键代入内层条件。内层有多条命中时，EXISTS 仍只返回一个真假判断。调换两张表的内外位置后，需要重新数外层行。

```sql
WITH a(k) AS (VALUES (1), (2)), b(k) AS (VALUES (1), (1)) SELECT count(*) FROM a WHERE EXISTS (SELECT 1 FROM b WHERE b.k = a.k);
```

## anti-exists | NOT EXISTS 找没有匹配的外层行
<!-- keywords: NOT EXISTS, 找不到匹配, 反查, 未登记, 无关联, 外层记录, 没有对应 -->
对于每条外层记录，先用关联键找内层记录。内层返回零行时 NOT EXISTS 成立。最终输出列由外层 SELECT 决定。

```sql
WITH a(k) AS (VALUES (4), (5)), b(k) AS (VALUES (4)) SELECT a.k FROM a WHERE NOT EXISTS (SELECT 1 FROM b WHERE b.k = a.k);
```

## filtered-membership | IN 子查询可以先筛内层再匹配外层
<!-- keywords: IN 子查询, 内层过滤, 成员检查, 筛选范围, 子查询重复值, 匹配列表 -->
先用内层 WHERE 缩小目标范围，再从内层 SELECT 取出要匹配的一列。IN 对每条外层记录检查一个值是否落在这列中。内层相同值出现多次也只影响真假判断。

```sql
WITH a(k) AS (VALUES (4), (5)), b(k, active) AS (VALUES (4, 0), (5, 1), (5, 1)) SELECT a.k FROM a WHERE a.k IN (SELECT b.k FROM b WHERE active = 1);
```

## not-in-null | NOT IN 遇到 NULL 时要检查三值逻辑
<!-- keywords: NOT IN, NULL, 未知, 三值逻辑, 不在列表, 反查陷阱 -->
如果目标值没有匹配而右侧含 NULL，NOT IN 可以得到未知结果。WHERE 仅保留真值。需要表达关联行是否缺失时，可单独比较带关联条件的 NOT EXISTS 结果。

```sql
SELECT 3 NOT IN (1, NULL), 1 NOT IN (1, NULL);
```
