---
{
  "id": "distinct",
  "version": 1,
  "topic": "distinct",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_select.html#distinct",
  "source_section": "2.6 Removal of duplicate rows",
  "reviewed_on": "2026-11-14"
}
---
# 查询结果去重

## whole-row | DISTINCT 比较输出行的所有列
<!-- keywords: DISTINCT, 多列, 组合, 重复, 去重 -->
DISTINCT 对整个输出行去重。比如输出（蓝、大）、（蓝、小）、（蓝、大），只保留两种组合。若只输出颜色，结果会变成一种。

## null | 去重时相同空值可归为一个结果
<!-- keywords: DISTINCT, NULL, 空值, 去重 -->
对于 DISTINCT 的重复判断，两个 NULL 值可视为相同。普通 WHERE 条件中的 NULL 等值比较遵循另一套真假规则。
