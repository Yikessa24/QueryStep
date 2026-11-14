---
{
  "id": "conditions",
  "version": 1,
  "topic": "conditions",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_expr.html#binaryops",
  "source_section": "2. Operators and Parse-Affecting Attributes",
  "reviewed_on": "2026-11-14"
}
---
# 组合条件

## and-or | AND 与 OR 的去留
<!-- keywords: AND, OR, 至少, 同时, 复合条件 -->
在两个确定的真假条件中，AND 要求两项都成立，OR 在至少一项成立时就保留行。可以举一个只满足左侧条件的记录试算。

## precedence | 括号显式指定组合次序
<!-- keywords: AND, OR, 括号, 优先级 -->
SQLite 中 AND 的优先级高于 OR。写出括号可以让读者立即看到哪些条件先组合。先计算括号内的真假，再处理外部条件。
