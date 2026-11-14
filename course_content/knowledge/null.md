---
{
  "id": "null",
  "version": 1,
  "topic": "null",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_expr.html#binaryops",
  "source_section": "2. Operators and Parse-Affecting Attributes",
  "reviewed_on": "2026-11-14"
}
---
# SQL 空值

## unknown | NULL 表示未知或缺失
<!-- keywords: NULL, 空值, 未知, 缺失, 0, 空字符串 -->
NULL 用来表示缺失或未知。数字 0 和空字符串都是具体的值。外连接补出的 NULL 表示这条输出记录里缺少右侧的匹配数据。

## compare | 判断空值使用 IS NULL
<!-- keywords: NULL, IS NULL, WHERE, 等于, 未知, 空值判断 -->
普通的等号和 NULL 比较时结果通常是未知，即使两边都是 NULL。要找右侧为空的行，用 WHERE 右表主键 IS NULL。以右表的非空键为判断字段，可以避免把原表中已存在但某个可空字段为空的匹配行误算作未匹配。
