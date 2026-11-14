---
{
  "id": "where-after-join",
  "version": 1,
  "topic": "join",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#whereclause",
  "source_section": "2.3 WHERE clause filtering",
  "reviewed_on": "2026-11-14"
}
---
# 连接条件与结果筛选

## predicate-placement | 右表条件放在 ON 或 WHERE
<!-- keywords: ON, WHERE, LEFT JOIN, 挪条件, 行消失, 外连接 -->
<!-- experiment: join_filter -->
连接条件在 ON 时，左连接会为找不到符合条件的右表记录的左表行补 NULL。把同一个右表等值条件放到 WHERE，筛选的是已经连好的结果。右表字段为 NULL 时，等值判断得到未知，WHERE 只保留条件为真的行，所以补出的行会消失。

## matching-only | 两种写法偶尔得到相同结果
<!-- keywords: LEFT JOIN, ON, WHERE, 相同, 反例, 对照 -->
<!-- experiment: join_filter -->
如果样例里左表每行都能配上符合条件的订单，两种写法可能刚好一样。可以换一组有读者没下单的样例作为反例，观察外连接补出的空值行在哪个写法里还能看到。
