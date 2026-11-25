---
{
  "id": "join-types",
  "version": 1,
  "topic": "join",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#determination_of_input_data_from_clause_processing",
  "source_section": "2.1. FROM clause processing",
  "reviewed_on": "2026-11-25"
}
---
# 连接的输入和匹配

## cartesian | 逗号连接与笛卡尔积
<!-- keywords: 笛卡尔积, 逗号连接, CROSS JOIN, 交叉连接, 不写连接条件, 两表乘积 -->
两张表之间没有匹配条件时，每个左表行都与每个右表行配对。两行和三行会产生六个配对。逗号连接后仍可用 WHERE 筛掉不需要的配对。

```sql
WITH a(x) AS (VALUES (1), (2)), b(y) AS (VALUES (3), (4), (5)) SELECT count(*) FROM a, b;
```

## inner-matches | INNER JOIN 保留所有满足条件的配对
<!-- keywords: INNER JOIN, 内连接, 等值连接, 匹配元组, 一对多, 相同键, 匹配次数, ON -->
内连接只产生满足匹配条件的配对。一个左表键匹配两个右表行时，结果会出现两个配对。只匹配一次、没有匹配和重复命中要分别数。

```sql
WITH a(k) AS (VALUES (1), (2)), b(k) AS (VALUES (1), (1), (3)) SELECT count(*) FROM a INNER JOIN b ON a.k = b.k;
```

## natural-names | NATURAL JOIN 自动用全部同名列匹配
<!-- keywords: NATURAL JOIN, 自然连接, 同名列, 公共列, USING, 只按键, 自动匹配 -->
先列出两侧所有同名列。自然内连接要求这些列同时匹配。右侧的同名列在输出中不再额外出现。新增同名列会改变匹配条件，需控制条件时可显式写 ON 或 USING。

```sql
WITH a(k, flag) AS (VALUES (1, 'a')), b(k, flag) AS (VALUES (1, 'b')) SELECT count(*) FROM a NATURAL JOIN b;
```

## qualified-columns | 列名冲突时用表别名限定
<!-- keywords: 列名冲突, 同名字段, 表别名, qualified column, ambiguous column, SQL 别名 -->
普通连接中，两张表都提供同名列时，用表名或表别名指出要读哪一列。按列相等连接的 ON 条件和输出列的位置是两件事。

```sql
WITH p(k) AS (VALUES (7)), q(k) AS (VALUES (7)) SELECT p.k FROM p JOIN q ON p.k = q.k;
```
