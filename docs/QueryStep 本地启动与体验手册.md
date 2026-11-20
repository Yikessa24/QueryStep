# QueryStep 本地启动与体验手册

在这台 Mac 上，按第 1～3 节可以走完一次「做题 → EpiKT 选题 → 错题诊断 → 迁移练习 → 下次辅导」。跨考点检索见第 4 节；新版 **SQL 实作与动态实验教练**见第 8 节，不必先做完正式题。

平时在原来的浏览器窗口练习，网页会恢复进度，按自己的判断作答。下面的固定选项用于复现特定题目和错题反馈。希望从第一题演示并保留原进度时，再另开无痕窗口。

## 1. 启动网站

**打开 Mac 的「终端」应用**，把下面两行一起复制进去，按回车。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
QUERYSTEP_COACH_ENABLED=1 QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$PWD/artifacts/diagnostics-venv/bin/python" ./start.sh
```

1. 等终端显示「QueryStep 已启动」。保持这个终端打开。
2. 打开浏览器，访问 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)。
3. 想继续平时的练习，就在普通窗口打开上面的地址。想从头按手册复现，就在无痕窗口打开同一个地址。
4. 首页出现「学会的不只是 SQL，还有解决问题的思路」时，点「开始练习」。已有进度的窗口会直接恢复到当前题。

桌面采用三栏布局：左侧是进度与「学习记录」，中间是题目、迁移练习和 SQL 诊断，右侧固定显示学习助教，输入框保持在右下方。「对话辅导」用于追问；「错题教练」用于带工具验证的辅导。窄屏和手机用底部「练习／助教」切换，学习记录入口在练习标题右侧。

启动命令会使用本机已配置的 Conda 环境、EpiKT 权重和 `.env`，同时开启诊断与错题教练。运行结束后回到启动终端按 `Ctrl+C`。如果终端提示端口已占用，按第 5 节处理。

## 2. 做到第 4 题，查看 EpiKT 选题

这一节从点击「开始练习」后的第一题开始。题目上的 A、B 等字母是选项。点击选项后，还要点题目下方的「提交答案」。

| 网页进度 | 点哪个选项 | 提交后点什么 |
|---|---|---|
| 第 1 题 | **B** | 「提交答案」→「下一题」 |
| 第 2 题 | **A** | 「提交答案」→「下一题」 |
| 第 3 题 | **A** | 「提交答案」→「下一题」 |
| 第 4 题 | **A** | 「提交答案」，留在反馈页 |

第 4 题标题上方应显示「EpiKT 推荐」。提交后看到「还差一步，一起理清思路」，在题目卡片下方的操作栏点「查看选题记录」。应看到**本轮实际题号 75，规则对照题号 69**。75 是实际展示的题，69 是使用同一份作答历史按规则计算出的对照题号。

## 3. 从错题到下一题

先留在第 2 节最后的 75 号错题反馈页，按下面的顺序做诊断、迁移练习和复习记录。

### 3.1 运行 HAVING 诊断

1. 在中间练习区向下滚动，点「SQL 错题诊断」卡片将其展开。在「你的判断」输入框粘贴下面这句。

   > 为什么分组后还要检查 HAVING？请用严格大于 1 的示例。

2. 点「运行诊断」。等到「诊断完成，学习记录待确认」或「诊断完成」。
3. 向下看「课程依据」和两张结果表。原始分组有 **4 组**，`HAVING COUNT(*) > 1` 后剩 **3 组**。页面应显示「被筛除的分组：D」。想看用了哪些工具，可展开「查看诊断轨迹」。
4. 同一块下方的「筛选条件」默认是「大于等于」，「计数阈值」默认是 **1**。保持这两个值，直接点「比较结果」。下方会新增一组对照，把**未筛选的 4 组**和 `HAVING COUNT(*) >= 1` **筛选后保留的 4 组**并排展示，并提示「两次查询未移除任何结果键」。上方诊断仍显示输入提示词时执行的 `> 1` 对照，筛选后是 **3 组**。

诊断完成后，页面有时会先显示「Gemini 正在补充讲解…」，随后展示补充解释。可以直接用已经显示的课程依据和 SQL 表继续后面的步骤。

### 3.2 换一组数据再做一次

1. 找到题目操作栏下方的「迁移练习」卡片（位于 SQL 诊断上方），点「换一组数据练练」。
2. 看新表和其中的 `HAVING COUNT(*) >= 2`。按照这条演示路线，选择文字为 **「2 行」**的选项。选项顺序可能变化。
3. 点「提交迁移题」。应看到「答对了。」以及「SQLite 查询结果」，其中列出保留的两个分组。侧栏的「已作答」仍是 **4**，这次变式结果保存在当前错题下。
4. 用 `Command + R` 刷新网页，确认迁移练习反馈仍可查看。

如果你的原会话已经生成过变式，以页面实际展示的题和数据为准。

### 3.3 保存复习要点，并在下一题追问

1. 仍在 75 号错题反馈页，找到「SQL 错题诊断」中的「保存为学习记录」。保留默认「复习要点」，或改成以下内容。

   > 我容易把 > 当成 >=。下次先找计数恰好等于阈值的组。

2. 点「确认保存」。看到「学习记录已保存。」后，点左侧「学习记录」，在弹窗中展开「已确认的学习记录」，就能看到这一条。可用「修改」或「删除」管理记录；删除需要再次确认。完成后点弹窗右上角关闭按钮，或按 Esc。
3. 点当前反馈页底部的「下一题」。按这条演示路线，会进入另一道相关聚合题。选择 **A**，点「提交答案」，等到错题反馈出现。
4. 在右侧「对话辅导」底部输入框粘贴下方第一句，点「发送」。也可以先点题目下方的「问问助教」定位输入框；手机会自动切到助教面板。Enter 发送，Shift + Enter 换行。

   > 请调用 retrieve_course_notes，再给一句简短的 GROUP BY 提示。

5. 等待「助教正在思考…」结束。看到「LLM 助教」表示本轮返回了模型回复。如果本轮使用了刚保存的记录，回复下面会显示「本轮辅导读取了已确认的学习记录」。看到「课程提示／备用回复」时，可以直接阅读备用说明；超时会明确显示原因，原来的「审核提示」标签已移除。
6. 想试一次连续追问，就在**同一个输入框**再粘贴下面这句，点「发送」。

   > 请用例题工具给一个不同的简短例子，帮我区分 GROUP BY 和 HAVING。

7. 点题目上方的向左箭头「上一题」（手机先切回「练习」）。顶部应显示「正在回看第 4 题」，可以查看之前的判分、诊断和迁移练习；诊断需要展开，教练记录需要切换右侧标签。点「返回当前进度」回到第 5 题。也可通过「学习记录」弹窗中的题目序号回看。

## 4. 做到 81 号题，体验跨考点检索

如果当前已经是 81 号题的错题反馈页，直接从第 3 步开始。如果第 2～3 节已做过，可以在新的无痕会话里走这条路线。Chrome 的无痕窗口共享同一次会话，想从第一题重新走时，先关闭**全部**无痕窗口，再新开一个。普通窗口的进度可以继续保留。

1. 打开 [QueryStep](http://127.0.0.1:5173/)，点「开始练习」。前五题依次选择 **A、B、A、C、A**。每题都点「提交答案」，再点「下一题」。
2. 到第 6 题选择 **A**，点「提交答案」。看到「还差一步，一起理清思路」后留在反馈页。点「查看选题记录」，应看到**实际题号 81，规则对照题号 70**。
3. 点右侧学习助教顶部的「错题教练」标签，再点「带我弄懂这题」（手机先点底部「助教」）。在刚出现的输入框粘贴下面这句，再点「请教错题教练」。

   > LEFT JOIN 右边没有配对订单时，左边的用户行还在吗？COUNT(*) 会不会跳过它？

4. 等待「正在查找依据或验证结果…」结束。先看「本轮结论」，再展开「查看工具观察与证据」。其中「课程依据」应能看到两个考点，点击结论下的依据链接也会展开并定位对应证据。

   - **左连接保留未匹配行**。点这一行的「查看依据」，核对为什么左侧记录仍保留，右侧补 `NULL`。
   - **COUNT(*) 统计所有结果行**。点另一行的「查看依据」，核对为什么右侧补了 `NULL` 的行仍会被计入。

5. 首轮缺一份依据且触发补查时，页面显示「已补查缺失考点」。补查后仍缺少依据的考点会显示「暂未找到课程依据」。上面这条问题用于体验两条依据齐备，首轮找齐时直接显示两条链接。
6. 想看教练自己选择实验，在**同一个教练输入框**粘贴下面这句，再点「请教错题教练」。

   > 查询课程规则，验证把右表状态条件从 ON 移到 WHERE 为什么可能少一行。

7. 看教练展示的 SQL 和结果表。如果第一组数据的结果相同，留意它是否换用「含边界数据的样例」重新比较。要直接核对固定 SQL 实验，切回中间练习区并展开「SQL 错题诊断」，在「你的判断」中输入 `ON 和 WHERE 有什么区别？`，点「运行诊断」。结果应显示条件放在 `ON` 时有 **3 行**，放在 `WHERE` 时剩 **1 行**，账户 2 和 3 被筛除。
8. 想继续练习，在「迁移练习」点「换一组数据练练」。看两张合成表和查询，对每个左表键数匹配记录。找不到匹配时仍计一行，答案以页面数据为准。选择行数后点「提交迁移题」，查看「SQLite 查询结果」。点「下一题」可以继续正式练习。

## 5. 页面或按钮和手册对不上

另开一个终端，复制以下命令。保持原启动终端运行。

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

| 看到的情况 | 下一步 |
|---|---|
| 网页打不开 | 回原启动终端，确认是否出现「QueryStep 已启动」。使用备用端口时，按启动终端打印的地址打开网页。 |
| 端口已占用 | 如果已有正常运行的实例，可以直接打开网页。要换到新版，回旧实例的启动终端按 `Ctrl+C`，再运行第 1 节。找不到旧终端时用第 6 节的备用端口。 |
| 看不到「EpiKT 推荐」 | 检查 `epikt_ready`。若为 `true`，先完成前三题，再在当前题提交后点「查看选题记录」查看回退提示。 |
| 看不到「运行诊断」或「带我弄懂这题」 | 先展开中间的「SQL 错题诊断」，或切到右侧「错题教练」标签。再核对 `diagnostics_ready` 与 `coach_ready` 是否为 `true`。实验能力支持 75 号与 81 号题的错题反馈页，其他错题用「对话辅导」。历史回看仅展示已保存结果。 |
| 第 6 题没有出现 81 号或第 4 题没有出现 75 号 | 用「查看选题记录」确认实际题号。如果沿用过往进度，想复现固定路线时用新的浏览器会话从第一题开始。 |
| 助教出现「课程提示／备用回复」或教练超时 | 可以继续查看已有证据、运行快速诊断和做迁移练习。想单独确认 Gemini 服务，运行第 7 节的探针。 |
| 刷新后进度不同 | 确认浏览器、原来的网址、站点 Cookie 和本机数据库一致。普通窗口与无痕窗口各有自己的进度。 |

## 6. 用备用端口启动或恢复环境

只需避开占用的端口时，在终端复制以下两行。看到「QueryStep 已启动」后，到浏览器打开 [http://127.0.0.1:5174/](http://127.0.0.1:5174/)。在该地址检查服务时访问 [备用健康状态](http://127.0.0.1:8001/healthz)。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
QUERYSTEP_BACKEND_PORT=8001 QUERYSTEP_FRONTEND_PORT=5174 QUERYSTEP_COACH_ENABLED=1 QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$PWD/artifacts/diagnostics-venv/bin/python" ./start.sh
```

### 6.1 独立诊断环境缺失时

新机器先按部署指南准备正式权重、题库和 pyKT 源码，用 `.env` 配置 Gemini 与本地知识库路径。现有 Mac 上可以先检查 `artifacts/diagnostics-venv/bin/python` 是否存在。准备文件的具体位置见部署文档。 [部署操作指南](../deploy/OPERATIONS.md)

如果独立诊断环境缺失，使用现有 Conda 的 `querystep` 环境。安装后用它启动。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate querystep
python -m pip install -e '.[api,kt,diagnostics,knowledge]'
npm --prefix web ci
QUERYSTEP_COACH_ENABLED=1 QUERYSTEP_DIAGNOSTICS_ENABLED=1 ./start.sh
```

若 `conda activate querystep` 提示该环境不存在，先执行 `conda create -n querystep python=3.11 pip`，再执行上面从 `conda activate querystep` 开始的命令。

### 6.2 知识库索引缺失时

已有知识库的这台 Mac 可以直接使用第 1 节的启动命令。需要重建时，在项目根目录运行下面的命令。第一条模型路径适用于当前工作区，换机器时需改为该机器的 BAAI/BGE-small-zh-v1.5 本地模型目录。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
export QUERYSTEP_EMBEDDING_MODEL="$PWD/../examples/居丽叶简历项目7：医疗助手/medix-agent-swarm/.venv/models/bge-small-zh-v1.5"
export QUERYSTEP_KNOWLEDGE_INDEX="$PWD/artifacts/workbench-knowledge.sqlite3"
artifacts/diagnostics-venv/bin/python -m pip install -e '.[knowledge]'
artifacts/diagnostics-venv/bin/python -m course_content.knowledge_index \
  --output "$QUERYSTEP_KNOWLEDGE_INDEX" --model "$QUERYSTEP_EMBEDDING_MODEL"
QUERYSTEP_COACH_ENABLED=1 QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$PWD/artifacts/diagnostics-venv/bin/python" ./start.sh
```

如果本地 `.env` 已经写了两个索引变量，启动时以 `.env` 读入的值为准。将其中的 `QUERYSTEP_KNOWLEDGE_INDEX` 指向上面生成的文件，再启动。索引缺失时教练回退到审核卡片或课程关键词检索，模型和索引不匹配时使用关键词检索。

## 7. 单独确认 Gemini 服务

如果网页能做题但助教连续回退，在另一个终端复制以下命令。这个探针会通过本机 `.env` 向已配置的模型服务发送合成 SQL 问题。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
set -a
source ./.env
set +a
artifacts/diagnostics-venv/bin/python -m tutor.check_provider
```

查看探针是否返回模型与检查结果。遇到 `ReadTimeout` 时可以先用网页的快速诊断和迁移练习，模型联通后再试辅导。跨考点检索实现、评估和补查的实测范围见开发方案。 [自主错题教练与课程知识库开发方案](QueryStep%20自主错题教练与课程知识库开发方案.md)

## 8. SQL 实作与动态实验教练

更新代码后，先在原启动终端按 `Ctrl+C`，再按第 1 节启动，避免旧进程继续运行旧后端。环境需包含 `api` 和 `diagnostics` 扩展；缺少时运行 `artifacts/diagnostics-venv/bin/python -m pip install -e '.[api,diagnostics]'`。新版课程新增 SUM 与排序规则，已有向量索引按第 6.2 节重建；未配置索引时仍可检索全部审核课程的关键词。

1. 点击「SQL 实作」（手机在顶部切换）。无需先提交正式题；原练习进度和未发送的辅导输入不会被清空。
2. 在任务选择框选择「保留零订单客户的计数」。先看需求、表结构与样例数据，然后在「你的 SQL」输入：

```sql
SELECT c.customer_id, COUNT(*) AS order_count
FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id
GROUP BY c.customer_id
```

3. 点击「运行 SQL」：样例可以执行，不能据此判定正确。点击「提交验证」：展开反例，找出预期为 0、实际为 1 的客户，并对照输入表中的未匹配记录。
4. 在固定右侧「实验教练」提问：**“样本看起来正常，请检查没有订单的客户和重复订单的边界，用实际结果给我提示，不要直接给答案。”** 教练动态选择检查、检索或执行工具；展开「执行轨迹」「查看实验依据」「运行指标」查看真实调用。模型失败时显示降级原因，不能把降级提示当作模型成功。
5. 自己修改计数对象为右表订单主键，再次「提交验证」。应通过 4 组有限场景；页面仍明确提示这不是所有数据上的 SQL 等价性证明。
6. 刷新页面验证草稿保存；切换其他任务再返回，编辑内容应保留。另一标签页更新同一草稿会提示冲突，不会静默覆盖；可读取远端版本，并保留冲突前本地 SQL 供复制。
7. 运行过程中可在右侧「最近实验」取消。服务中断后显示「恢复执行」，继续使用已保存证据和累计预算；主动取消不能恢复。任务或已确认学习笔记版本发生变化时，需要重新提交。

10 个任务覆盖条件筛选、NULL、去重、分组计数、HAVING、内外连接、求和和排序。只允许受限 SQLite SELECT；写入、外部文件访问、过大的查询或结果会被拒绝。错误提示会保留输入，不会修改正式题答案。

「学习上下文」展示提交时的首次独立作答、已确认笔记和正式题 EpiKT 预测快照。要观察真实预测，先按第 2 节完成三次独立作答并请求下一题，再到对应主题的实作提问；未作答或没有同主题候选时，应显示无预测而不是编造分数。实作与教练提示均不增加正式已答题数。

### 8.1 隔离验收，不影响原来的学习记录

另开终端，使用新的本地测试数据库，不要复用正式学习数据库；保留原来的 8000/5173 服务。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
set -a; source ./.env; set +a
export QUERYSTEP_DATABASE_URL="sqlite:///$PWD/artifacts/workbench-local-test.sqlite3"
export QUERYSTEP_DIAGNOSIS_CHECKPOINTS="$PWD/artifacts/workbench-local-test.checkpoints.sqlite3"
export QUERYSTEP_EPIKT_RUN="$PWD/artifacts/epikt-dbe-fold0"
export QUERYSTEP_CATALOG="$PWD/artifacts/dbe-sql-approved.json"
export QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_COACH_ENABLED=1
artifacts/diagnostics-venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

再开终端：

```bash
cd "$HOME/Desktop/实习/projects/QueryStep/web"
QUERYSTEP_API_PROXY=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

打开 `http://127.0.0.1:5174` 手动测试。自动验收在项目根目录运行（需要已安装本地 Playwright/Chromium）：

```bash
export NODE_PATH="$PWD/artifacts/browser-tools/node_modules"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/artifacts/browser-tools/browsers"
QUERYSTEP_TEST_WEB_URL=http://127.0.0.1:5174 node tests/browser_workbench.cjs
QUERYSTEP_TEST_WEB_URL=http://127.0.0.1:5174 QUERYSTEP_WORKBENCH_ISOLATED_DB=1 node tests/browser_workbench.cjs --real
```

默认测试完全模拟 API；`--real` 会创建合成学习会话并调用已配置模型，不能指向真实学习数据库。

如需同时验证新版课程索引，将 `QUERYSTEP_TEST_EXPECT_COURSE_CORPUS` 设为索引清单中的 `corpus_sha256`，再执行 `--real` 命令。测试会向实验教练询问空表和全 `NULL` 时的 `SUM` 行为，检查命中对应课程卡片，并在刷新后从执行轨迹核对索引版本。

### 8.2 复现 SQL 诊断比较

在项目根目录运行标签审计，不调用模型、不接触学习数据库：

```bash
artifacts/diagnostics-venv/bin/python -m evals.workbench \
  --split all --validate-labels --output artifacts/workbench-label-audit.json
```

100 个冻结案例按任务划分为 60 个开发、40 个测试；每个标签审计四场景和三个种子。案例属于内部作者/编码助手编写，不能称为外部独立基准。

四臂真实模型比较会产生提供方调用与费用。先按第 6.2 节配置本地嵌入模型，并将含新版课程的索引生成到 `artifacts/workbench-knowledge.sqlite3`，再运行：

```bash
set -a; source ./.env; set +a
export QUERYSTEP_EMBEDDING_MODEL="$PWD/../examples/居丽叶简历项目7：医疗助手/medix-agent-swarm/.venv/models/bge-small-zh-v1.5"
QUERYSTEP_LLM_MODEL=gemini-3-flash artifacts/diagnostics-venv/bin/python -m evals.workbench \
  --split test --concurrency 2 --synthetic-snapshot novice-v1 \
  --index artifacts/workbench-knowledge.sqlite3 \
  --embedding-model "$QUERYSTEP_EMBEDDING_MODEL" \
  --output artifacts/workbench-test-local.json
```

未配置索引时可省略两个索引参数，使用词项课程检索，但这不是同一检索配置。所有报告拒绝覆盖已有文件，重跑请使用新文件名。原始输出只保存在本地；报告记录源码与案例哈希、用量缺失、降级原因和证据验证。合成上下文不是真实 EpiKT 效果实验，未知费用不是零；四臂调用预算不同，不能称为等成本比较。

### 8.3 尚待执行的人工验收

以下是验收方法，不是已完成的试用结果：

1. 请未参与编写的 SQL 教师或熟悉 SQL 的审核者，独立核对 10 个任务的要求、数据约束、参考查询和 100 个冻结标签，记录不同意见。参考定义位于 `course_content/sql_tasks.py`，标签位于 `evals/workbench_cases.py`；不能只依据程序输出确认程序自己的规则。
2. 四臂命令可加 `--annotation-output artifacts/workbench-human-review.json` 生成未填写的人审文件。将它与含 arm/答案映射的原报告分开，审核者填写 `manual_review` 中的判断恰当性、提示帮助性、证据支持性及说明。输出结构仍可能暴露实验臂，因此不是严格双盲；未填写字段必须保持 null，不能默认通过。
3. 征得参与者同意后，使用第 8.1 节的独立数据库进行小规模试用。明确告知 SQL 和提问可能发送给已配置模型，不输入个人信息或生产数据库内容，不收集不必要身份信息。
4. 让参与者自行完成“保留零订单客户”“筛选已付款的连接”“空表求和”三个不同任务，观察能否找到入口、运行、理解反例、自主修正及刷新恢复。记录卡住的位置、误导提示、调用失败、独立完成情况，而不是由演示者代答。
5. 随后换一个未演示的同类任务，先不提供提示，记录首次独立尝试与理由。只把结果用于发现体验问题和提出教学假设；少量试用不能推出显著学习增益。

完成后再将实际人数、日期、审核分歧和发现的问题写入审计报告；当前不具备这些记录。
