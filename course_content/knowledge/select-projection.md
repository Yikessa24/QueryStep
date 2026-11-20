---
{
  "id": "select-projection",
  "version": 2,
  "topic": "select",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html",
  "source_section": "2.4 Generation of the set of result rows; 4. The ORDER BY clause; 5. The LIMIT clause",
  "reviewed_on": "2026-11-20"
}
---
# 投影与结果表

## columns | SELECT 列表决定结果列及顺序
<!-- keywords: SELECT, SELECT *, AS, 投影, 列 -->
SELECT 中列出的表达式按书写顺序输出。星号按输入表结构展开列。AS 能给输出列取别名。只改 SELECT 列表一般改变的是列。

## rows | 普通投影保留已有行
<!-- keywords: SELECT, 行数, 列数, 投影, 重复 -->
普通 SELECT 选出指定列，输入表每行仍会产生一行。两条输入在选中的列上相同，输出仍可出现两行。

## ordered-limit | ORDER BY 与 LIMIT 决定前几行
<!-- keywords: ORDER BY, LIMIT, ASC, DESC, 排序, 并列, 前三, NULL -->
未写 ORDER BY 时，结果行的顺序没有保证。多个排序键从左到右依次比较；前一键相同才比较下一键，所有排序键都相同时先后仍未定义。SQLite 默认 ASC 升序且 NULL 在前，DESC 降序时 NULL 在后。LIMIT 限制返回行数，不能代替排序；要求并列时按标识排序，应明确写出这个次级排序键。
