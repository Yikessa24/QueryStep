---
{
  "id": "conditions",
  "version": 2,
  "topic": "conditions",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_expr.html#binaryops",
  "source_section": "2. Operators and Parse-Affecting Attributes",
  "reviewed_on": "2026-11-25"
}
---
# 组合条件

## and-or | AND 与 OR 的去留
<!-- keywords: AND, OR, 至少, 同时, 复合条件 -->
在两个确定的真假条件中，AND 要求两项都成立，OR 在至少一项成立时就保留行。可以举一个只满足左侧条件的记录试算。

## precedence | 括号显式指定组合次序
<!-- keywords: AND, OR, 括号, 优先级 -->
SQLite 中 AND 的优先级高于 OR。写出括号可以让读者立即看到哪些条件先组合。先计算括号内的真假，再处理外部条件。


## overlapping-or | 同一行同时满足两个 OR 条件也只保留一次
<!-- keywords: OR, 两个条件都成立, 只保留一次, 重叠条件, 重复行, 复合条件, AND -->
WHERE 将整个布尔表达式对每一行求值。即便一条输入同时满足 OR 两边，这条输入在筛选结果里也只保留一次。不同输入行可以分别满足相同条件。

```sql
WITH flags(x) AS (VALUES (1), (2), (3)) SELECT count(*) FROM flags WHERE x >= 2 OR x = 3;
```
