---
{
  "id": "set-operations",
  "version": 1,
  "topic": "set_ops",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#compound",
  "source_section": "3. Compound Select Statements",
  "reviewed_on": "2026-11-14"
}
---
# 合并和比较查询结果

## union | UNION 合并并去重
<!-- keywords: UNION, UNION ALL, 集合, 合并, 去重 -->
先看两侧各自返回了哪些行。UNION 合并它们并去掉重复结果，UNION ALL 保留全部记录。两个查询要返回同样多的列。

## except | EXCEPT 查只在左侧出现的行
<!-- keywords: EXCEPT, INTERSECT, 差集, 交集, 顺序 -->
EXCEPT 返回左侧存在、右侧没有的行，交换顺序可能改变结果。INTERSECT 返回两边都出现的行。
