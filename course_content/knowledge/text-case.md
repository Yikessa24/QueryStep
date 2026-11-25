---
{
  "id": "text-case",
  "version": 1,
  "topic": "where",
  "dialect": "sqlite",
  "source_url": "https://www.sqlite.org/lang_corefunc.html#lower",
  "source_section": "lower(X)",
  "reviewed_on": "2026-11-25"
}
---
# 文本大小写筛选

## lower-ascii | LOWER 将 ASCII 字母转为小写
<!-- keywords: lower, lower(Name), 小写, 大小写, ASCII, 字符串, 忽略大小写, 混合大小写 -->
WHERE 中可以先对列调用 LOWER，再与小写字面值比较。SQLite 内置 LOWER 的默认大小写转换覆盖 ASCII 字母。若输入还有其他文字，应检查实际部署的 Unicode 支持。

```sql
WITH labels(word) AS (VALUES ('MAP'), ('map'), ('Stop')) SELECT count(*) FROM labels WHERE lower(word) = 'map';
```
