---
{
  "id": "left-join",
  "version": 1,
  "topic": "join",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#fromclause",
  "source_section": "2.1 Determination of input data",
  "reviewed_on": "2026-11-14"
}
---
# 左连接与匹配

## preserves-left | 保留没有匹配记录的左表行
<!-- keywords: LEFT JOIN, 外连接, 未匹配, 没借过书, 缺失记录 -->
<!-- experiment: join_filter -->
左连接让左表的每条记录至少产生一行结果。找不到满足 ON 的右表行时，SQLite 为右表输出列补上 NULL。比如以读者表为左表时，从来没借过书的人也可以出现在结果里。先区分左表这行是否存在，以及右表有没有匹配记录。

## match-condition | 连接条件决定什么算匹配
<!-- keywords: LEFT JOIN, ON, 等值连接, 配对, 一对多 -->
<!-- experiment: join_filter -->
ON 用来判断左右两条记录是否形成一对。它可以同时要求编号相等、右侧状态符合某值。右表一条都不符合时，左连接先保留左表行。右侧有多条匹配时，左表行可在结果里重复。
