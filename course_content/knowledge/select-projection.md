---
{
  "id": "select-projection",
  "version": 1,
  "topic": "select",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#resultset",
  "source_section": "2.4 Generation of the set of result rows",
  "reviewed_on": "2026-11-14"
}
---
# 投影与结果表

## columns | SELECT 列表决定结果列及顺序
<!-- keywords: SELECT, SELECT *, AS, 投影, 列 -->
SELECT 中列出的表达式按书写顺序输出。星号按输入表结构展开列。AS 能给输出列取别名。只改 SELECT 列表一般改变的是列。

## rows | 普通投影保留已有行
<!-- keywords: SELECT, 行数, 列数, 投影, 重复 -->
普通 SELECT 选出指定列，输入表每行仍会产生一行。两条输入在选中的列上相同，输出仍可出现两行。
