---
{
  "id": "where-filter",
  "version": 2,
  "topic": "where",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#whereclause",
  "source_section": "2.3 WHERE clause filtering",
  "reviewed_on": "2026-11-25"
}
---
# 按行筛选

## matching | WHERE 只保留条件为真的行
<!-- keywords: WHERE, 筛选, 行, 条件, NULL, 先组合再筛选, 两表配对筛选, 连接后检查条件 -->
WHERE 对每条输入行单独判断。符合条件的行留下，条件为假或未知时被过滤。FROM 提供的输入也可以是两张表的配对，这时逐一筛掉不满足条件的配对。来源表本身仍保留原有记录。

## boundary | 试算一条恰好在阈值上的记录
<!-- keywords: WHERE, >=, >, 边界值, 大于等于 -->
比较大于和大于等于时先试算一个恰好等于阈值的值。比如气温门槛是 18，严格大于只接受比 18 高的记录。

## literal-equality | WHERE 等号对每条输入行比较
<!-- keywords: WHERE 等号, 精确匹配, 字符串常量, 单引号, 名称大小写, 默认比较, 区分大小写 -->
文字常量用单引号。按默认 BINARY 排序规则比较文本时，不同大小写的值不相等。若配置了其他排序规则或显式转换大小写，应按实际条件判断。

```sql
WITH labels(word) AS (VALUES ('map'), ('MAP')) SELECT count(*) FROM labels WHERE word = 'map';
```
