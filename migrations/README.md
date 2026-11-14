# PostgreSQL 迁移

初始表由 `api/db.py` 创建。待答题和学生作用域内的幂等键受唯一约束保护，判分与历史版本更新在同一事务完成。后续数据库结构变化需编写版本化迁移。

现有 `decisions.catalog_version` 字段保存题库内容指纹。已有仅保存版本名的旧会话，以及任何内容发生变化的旧会话，均需从界面开启新一轮。原作答仍保留在数据库中。

## `diagnostics_001`

开启诊断时，`api.diagnostics.migrate()` 在事务内登记版本并增量创建诊断运行、事件和学习记录表。旧有 `learners`、`decisions`、`attempts` 和 `tutor_turns` 继续使用原结构。LangGraph 的 checkpoint 使用单独 SQLite 文件，默认与本机作答数据库同目录，可通过 `QUERYSTEP_DIAGNOSIS_CHECKPOINTS` 设置路径。

## `diagnostics_002`

增量创建 `diagnosis_experiments`，以 `(run_id, request_key)` 为主键持久保存参数实验的幂等结果。重复请求读取已保存的观察，使用同键提交其他参数时返回 `409`。迁移无需重写现有记录。

## `diagnostics_003`

增量创建 `diagnosis_transfer_attempts`。原错题的 `decision_id` 保证每道错题只有一份迁移测量，`run_id` 记录触发练习的诊断。打开时冻结题目版本与时间，提交时保存首次选项、判分和时间。原 `attempts` 表只作为归属关联，迁移作答写入独立表。

## `diagnostics_004`

增量创建 `practice_transfers`，主键为原错题的 `decision_id`。首次打开存储合成题、SQL 答案及选项顺序的快照。旧版 `diagnosis_transfer_attempts` 保留，存在旧记录时练习入口复用原题。两个入口通过同一学习者事务锁维护一次首答。

升级前保留数据库和 checkpoint 备份。停用 `QUERYSTEP_DIAGNOSTICS_ENABLED` 可回到原练习流程，同时保留新增表供之后恢复。部署迁移使用单个启动实例。SQLite 路径已做测试，PostgreSQL 多实例部署需另验收。

## 自主错题教练

开启 `QUERYSTEP_COACH_ENABLED` 时增量创建 `coach_runs`。它保存错题决策、学习者作用域内的幂等键、已发布证据与终态。正式作答表作为外键参照。教练的 MCP 进程随服务启动和关闭。当前本地版以单个服务进程运行，服务重启会将上次未完成的运行标为中断并保留已取得证据。
