# QueryStep 本地启动与体验手册

适用于包含证据优先诊断、Gemini 补充讲解和 24 道 SQL Core 迁移练习的版本。正式 EpiKT 权重在 Mac CPU 上运行，Gemini 通过本机 `.env` 配置的服务提供辅导。

## 1. 启动完整功能

在这台 Mac 上打开终端，整行复制以下命令并回车。

```bash
QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$HOME/Desktop/实习/projects/QueryStep/artifacts/diagnostics-venv/bin/python" "$HOME/Desktop/实习/projects/QueryStep/start.sh"
```

命令会激活 Conda 的 `querystep` 环境，核对正式权重和 24 道演示题，读取 `.env`，再启动前后端。`QUERYSTEP_DIAGNOSTICS_ENABLED=1` 会开启 SQL 诊断、迁移练习和学习记录。看到「QueryStep 已启动」和「EpiKT 已加载。Gemini 辅导已配置。」后，打开 [QueryStep 学生端](http://127.0.0.1:5173/)。保持这个终端运行。结束时按 `Ctrl+C`。

如果已经开着旧实例，先在启动它的终端按 `Ctrl+C`，然后用上面的命令重启。若用新的 Mac 或独立环境不存在，参见第 6 节。

## 2. 固定演示路线

首次体验用一个新的无痕窗口，点击「开始练习」。以下选项用于复现这台 Mac 上当前权重和题库的固定路径。平时练习可自行作答。

| 页面上的第几题 | 演示选项 | 提交后应看到 |
|---|---|---|
| 第 1 题 | **B** | 规则推荐、回答有误 |
| 第 2 题 | **A** | 规则推荐、回答有误 |
| 第 3 题 | **A** | 规则推荐、回答正确 |
| 第 4 题 | **A** | EpiKT 推荐、回答有误 |

每题点击「提交答案」。前三题提交后点击「下一题」，第 4 题提交后先留在反馈页。点击「查看选题记录」，应看到**本轮实际题号 75，规则对照题号 69**，以及 EpiKT 模型版本。这两个题号来自同一份作答历史。第 75 题是你实际做到的题。

题目上方的「上一题」可以回看已提交的选择、判分和已保存的辅导内容。回看时可以逐题前后翻，也可以点「返回当前进度」直接回到当前题。回看页面只读，正式作答计数和当前未提交的选项会保留。

## 3. 从错题到下一题

以下操作都从第 75 题的错题反馈页开始。

1. **运行错题诊断。** 在「SQL 错题诊断」下的「你的判断」输入框粘贴这句，然后点击「运行诊断」。

   > 为什么分组后还要检查 HAVING？请用严格大于 1 的示例。

   页面先展示课程依据和实际执行的两条 SQL。原始分组有 **4 组**，`HAVING COUNT(*) > 1` 后剩 **3 组**，D 被筛除。可展开「查看诊断轨迹」确认课程检索、查询执行和结果比较的工具步骤。

   「课程依据」里的中文说明和链接是提前写好的资料卡。系统按主题和关键词检索，链接指向 PostgreSQL 官方文档。Gemini 补讲可以从当前卡片中选择引用。可直接阅读页面上的中文说明，需要查原文时再点链接。 [PostgreSQL 聚合函数教程](https://www.postgresql.org/docs/18/tutorial-agg.html) · [GROUP BY 和 HAVING](https://www.postgresql.org/docs/18/queries-table-expressions.html#QUERIES-GROUP)

2. **看 Gemini 补充讲解。** 证据出现后，页面可能短暂显示「Gemini 正在补充讲解…」，随后出现「Gemini 补充讲解 · 本轮诊断」，包含一个讲解重点、一个追问和一条依据。网关超时后仍可使用已显示的课程依据和 SQL 结果完成后续步骤。

3. **改条件再运行一次。** 将「筛选条件」设为「大于等于」，「计数阈值」设为 **1**，点击「比较结果」。新的对照应显示 **4 组 → 4 组**，页面提示「两次查询未移除任何结果键」。原来的 `> 1` 结果仍可对照。

4. **做一道迁移练习。** 在错题反馈页点「换一组数据练练」。75 号题的新版变式用一张合成数据表考 `HAVING COUNT(*) >= 2`。按 `category` 分组后，示例中有两组符合条件，选 **2 行**。选项顺序会变化。点「提交迁移题」，查看判分、解释和 SQLite 实际返回的结果。此时左侧「已作答」仍为 **4**，迁移作答单独保存。此前已经打开过旧版迁移题的会话仍会显示原题。

5. **刷新并保存复习要点。** 仍留在第 75 题，刷新页面。确认诊断和迁移题反馈仍在，再找到「保存为学习记录」，保留默认复习要点或自行改写，点击「确认保存」。左侧展开「已确认的学习记录」可查看、修改或删除条目。先留着这条记录，便于体验下面的召回。

   建议写成自己下次想检查的具体步骤，比如「我容易把 `>` 当成 `>=`，下次先看有没有计数恰好等于阈值的组」。确认后，它会成为同主题错题辅导的可选上下文。侧栏随时可回顾，删除后停止后续召回。EpiKT 仍根据正式作答记录决定下一题。

6. **验证下一题的助教能用到记录。** 点击「下一题」，按当前演示历史会进入另一道相关聚合题。选 **A** 并提交，进入错题反馈。在「问问助教」输入下方第一句话并点「发送」。模型正常回复时会标为「LLM 助教」。如果本轮读取了复习记录，回复下方会显示「本轮辅导读取了已确认的学习记录」。

   > 请调用 retrieve_course_notes，再给一句简短的 GROUP BY 提示。

   想继续体验多轮问答，可以接着发第二句。

   > 请用例题工具给一个不同的简短例子，帮我区分 GROUP BY 和 HAVING。

   发出问题后，页面会用「助教正在思考…」提示等待。看到「审核提示」时，本轮使用的是审核过的说明。可以继续练习，或按第 5 节排查 Gemini。

在普通浏览器窗口中保留此站点的 Cookie，关闭页面或重启服务后可以继续。无痕窗口适合单次演示，关闭所有无痕窗口后，下次通常会从新会话开始。页面上的「重新开始」会开启新学习身份。

## 4. 可选路线 · 连接条件对照

另开独立的新会话，依次提交 **A、B、A、C、A**，每次提交后点「下一题」。第 6 题应由 EpiKT 推荐 **81 号题**，规则对照是 **70 号题**。选 **A** 提交进入错题反馈，在「你的判断」输入下方问题，再点击「运行诊断」。

> ON 和 WHERE 有什么区别？

在合成数据上，付款条件放在 `ON` 时返回 **3 行**，移到 `WHERE` 后只剩 **1 行**，账户 2 和 3 被筛除。可以点「把条件移到 WHERE 并比较」再运行一次。

在同一页点「换一组数据练练」可做 `LEFT JOIN` 变式，也可以答错后直接打开。数出左表每行在右表的匹配条数。找不到匹配时仍计一行。合计为 **8 或 9 行**，以当前展示的数据表为准。提交后可以在「SQLite 查询结果」中看到哪些左表记录的右侧值为 `NULL`。其余 SQL Core 题同样在答错后提供迁移入口。

## 5. 排查常见情况

在另一个终端运行以下命令检查服务。

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

| 现象 | 怎么处理 |
|---|---|
| 页面打不开，或提示端口已占用 | 查终端有没有打印「QueryStep 已启动」。如有旧服务，请到它的终端停止后重启。备用端口命令见第 6 节。 |
| 第 4 题没有出现 EpiKT 推荐 | 查看 `epikt_ready`。若为 `false`，检查权重、配套映射和题库。若为 `true`，确认是新会话且前三题为 B、A、A，再看「查看选题记录」里的回退信息。 |
| 看不到「SQL 错题诊断」 | 查看 `diagnostics_ready` 和 `mcp_ready`，正常都为 `true`。确认启动时加了诊断开关，且当前是第 75 或 81 题的错题反馈页。 |
| 有 SQL 诊断，Gemini 一直没出现 | `tutor_ready: true` 代表已读入服务配置。实际联通看「LLM 助教」或「Gemini 补充讲解」。普通问答读取 `QUERYSTEP_LLM_MODEL`，补充讲解读取 `QUERYSTEP_EXPLANATION_MODEL`，后者默认 `gemini-3-flash`，设为空会关闭补充讲解。修改 `.env` 后重启后端。 |
| 页面提示「请确认实验条件」 | 诊断问题的条件不明确。可直接在页面选条件并比较。想继续体验第 3 节的完整路线时，用其中的原句新发起一次诊断。 |
| 刷新没有恢复原进度 | 确认仍在原浏览器和原地址，且站点 Cookie 保留。若换了本机作答数据库或开始了新学习身份，则会显示对应的另一份进度。 |

## 6. 环境、备用启动与模型排查

这台 Mac 的默认作答库为 `artifacts/querystep.sqlite3`。重新布置环境时，准备 Conda、Node.js、项目源码与配套的本地文件。

| 本地文件 | 用途 |
|---|---|
| 根目录 `.env` | Gemini 地址、密钥、模型和超时配置 |
| `artifacts/epikt-dbe-fold0/` | 正式权重、模型配置、ID 映射、校准和验收文件。恢复时整体复制。 |
| `artifacts/dbe-sql-approved.json` | 与正式权重匹配的 24 道演示题 |
| `research/` 下的配套 pyKT 源码 | 加载 EpiKT。具体目录和准备方式见部署文档。 |

如果项目根目录的独立诊断环境不可用，可以在已有的 Conda `querystep` 环境安装依赖后启动。只有环境还没建立时，先运行 `conda create -n querystep python=3.11 pip`。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
conda activate querystep
python -m pip install -e '.[api,kt,diagnostics]'
npm --prefix web ci
QUERYSTEP_DIAGNOSTICS_ENABLED=1 ./start.sh
```

如果 `conda activate` 提示当前终端没有初始化，在这台 Mac 可以先执行 `source /opt/miniconda3/etc/profile.d/conda.sh`。检查端口使用 `lsof -nP -iTCP:8000 -iTCP:5173 -sTCP:LISTEN`。希望用备用端口时，在项目根目录执行下方命令，并打开启动日志打印的 `5174` 页面地址。

```bash
QUERYSTEP_BACKEND_PORT=8001 QUERYSTEP_FRONTEND_PORT=5174 QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$PWD/artifacts/diagnostics-venv/bin/python" ./start.sh
```

### 分开启动前后端

排查后端启动日志时，可用两个终端分别启动。在第一个终端从项目根目录运行以下命令。这里使用本机已有的独立诊断环境。如已在 `querystep` 安装诊断依赖，可激活该环境，并把最后一行的 `artifacts/diagnostics-venv/bin/python` 改成 `python`。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
set -a
source ./.env
set +a
export QUERYSTEP_EPIKT_RUN="$PWD/artifacts/epikt-dbe-fold0"
export QUERYSTEP_CATALOG="$PWD/artifacts/dbe-sql-approved.json"
export QUERYSTEP_LLM_ALLOW_MAPPED_ITEMS=1
export QUERYSTEP_DIAGNOSTICS_ENABLED=1
artifacts/diagnostics-venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

看到 `Application startup complete` 后，另开终端启动前端。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep/web"
QUERYSTEP_API_PROXY=http://127.0.0.1:8000 npm run dev -- --strictPort
```

### Gemini 连通性探针

需要单独检查普通 Gemini 助教的服务时，在项目根目录运行以下探针。它会向已经配置的模型服务发送合成 SQL 问题。

```bash
conda activate querystep
set -a
source ./.env
set +a
python -m tutor.check_provider
```

技术架构、验收对照和独立评估方法见 [多 Agent 扩展开发文档](QueryStep%20多%20Agent%20扩展开发文档.md)。权重及环境布置见 [部署操作指南](../deploy/OPERATIONS.md)。
