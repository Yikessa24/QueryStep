---
{
  "id": "set-operations",
  "version": 2,
  "topic": "set_ops",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#compound",
  "source_section": "3. Compound Select Statements",
  "reviewed_on": "2026-11-25"
}
---
# 合并和比较查询结果

## union | UNION 合并并去重
<!-- keywords: UNION, UNION ALL, 集合, 合并, 去重 -->
先看两侧各自返回了哪些行。UNION 合并它们并去掉重复结果，UNION ALL 保留全部记录。两个查询要返回同样多的列。

## except | EXCEPT 查只在左侧出现的行
<!-- keywords: EXCEPT, INTERSECT, 差集, 交集, 顺序 -->
EXCEPT 返回左侧存在、右侧没有的行，交换顺序可能改变结果。INTERSECT 返回两边都出现的行。


## union-all | UNION ALL 保留重复结果行
<!-- keywords: UNION ALL, UNION 区别, 保留重复, 两批记录, 并集, 合并, 不去重 -->
两个查询产生相同结果行时，UNION ALL 会保留每一条。UNION 会在合并后按整行去重。两侧 SELECT 的输出列数需要一致。

```sql
SELECT 'tag' UNION ALL SELECT 'tag';
```
