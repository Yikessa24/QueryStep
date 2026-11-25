# QueryStep 本地启动与体验手册

启动一次后，可以按下面两条路线体验。每个功能的操作步骤后都有一小段「背后用到的技术」。

| 路线 | 按顺序体验的功能 |
|---|---|
| 第 2 节 · 正式练习 | 做题与判分 → EpiKT 选题 → SQL 错题诊断 → 迁移练习 → 保存与回看学习记录 → Gemini 多轮对话 → 跨考点错题教练 |
| 第 3 节 · SQL 实作 | 写 SQL 与反例验证 → 问实验教练 → 看课程检索结果 → 刷新后恢复草稿和实验记录 |

平时用原来的浏览器窗口继续学习。手册中的固定选项用于复现特定题目。希望从第一题演示且保留原进度时，可以另开无痕窗口。SQL 实作打开后就能做，普通窗口即可。

## 1. 启动网站

如果服务已经在运行，打开 [QueryStep](http://127.0.0.1:5173/) 并刷新，确认页面有「SQL 实作」，就可以直接进入第 2 或第 3 节。

**打开 Mac 的「终端」应用**，把下面两行一起复制进去，按回车。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
QUERYSTEP_COACH_ENABLED=1 QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$PWD/artifacts/diagnostics-venv/bin/python" ./start.sh
```

1. 等终端显示「QueryStep 已启动」。保持这个终端打开。
2. 打开浏览器，访问 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)。
3. 想做正式题，从第 2 节开始。想直接写 SQL，点左侧「SQL 实作」，到第 3 节继续。

桌面采用三栏布局：左侧是进度与「学习记录」，中间是题目、迁移练习和 SQL 诊断，右侧固定显示学习助教，输入框保持在右下方。「对话辅导」用于追问；「错题教练」用于带工具验证的辅导。窄屏和手机用底部「练习／助教」切换，学习记录入口在练习标题右侧。

启动脚本会使用本机已配置的 Conda 环境、EpiKT 权重和 `.env`。知识库使用 `artifacts/workbench-knowledge.sqlite3`，需要创建或切换时看第 5.2 节。更新代码后，先在旧启动终端按 `Ctrl+C`，再运行上面的命令。端口已占用时看第 4 节。

**背后用到的技术**　`start.sh` 启动 Vite 前端和 Uvicorn 上的 FastAPI 后端。React + TypeScript 负责页面交互，数据库、模型和工具由后端访问。

## 2. 正式练习

### 2.1 做题、提交与判分

1. 在首页点「开始练习」。如果网站已恢复到已有进度，继续作答即可。要复现下面的题号，请从第一题开始。
2. 按表选中选项，再点「提交答案」。前三题提交完点「下一题」进入推荐题。

| 网页进度 | 点哪个选项 | 提交后点什么 |
|---|---|---|
| 第 1 题 | **B** | 「提交答案」→「下一题」 |
| 第 2 题 | **A** | 「提交答案」→「下一题」 |
| 第 3 题 | **A** | 「提交答案」→「下一题」 |

**背后用到的技术**　题库和正确选项在后端。FastAPI 判分后，通过 SQLAlchemy 把正式作答存入 SQLite。重复提交同一答题请求时，后端复用已保存的结果。

### 2.2 看 EpiKT 如何选下一题

1. 做完前三题后，看第 4 题标题上方的「EpiKT 推荐」。选择 **A**，点「提交答案」，留在「还差一步，一起理清思路」的反馈页。
2. 点题目下方的「查看选题记录」。按本机验收路线，应看到**实际题号 75、规则对照题号 69**。如果沿用既有作答记录，以页面显示的实际题号为准。

**背后用到的技术**　PyTorch 加载按 pyKT 流程训练得到的 EpiKT 权重，根据已判分历史给候选正式题预测答对概率。教学策略结合课程条件和概率选题。规则对照用同一历史和候选集，换成规则评分再执行相同的选题逻辑。作答历史太短或模型暂时不可用时，系统使用规则选题。

### 2.3 运行 SQL 错题诊断

留在上一节的 75 号错题反馈页。

1. 在中间练习区向下滚动，点「SQL 错题诊断」卡片将其展开。在「你的判断」输入框粘贴下面这句。

   > 为什么分组后还要检查 HAVING？请用严格大于 1 的示例。

2. 点「运行诊断」。等到「诊断完成，学习记录待确认」或「诊断完成」。
3. 向下看「课程依据」和两张结果表。原始分组有 **4 组**，`HAVING COUNT(*) > 1` 后剩 **3 组**。页面应显示「被筛除的分组：D」。想看用了哪些工具，可展开「查看诊断轨迹」。
4. 同一块下方的「筛选条件」默认是「大于等于」，「计数阈值」默认是 **1**。保持这两个值，直接点「比较结果」。下方会新增一组对照，把**未筛选的 4 组**和 `HAVING COUNT(*) >= 1` **筛选后保留的 4 组**并排展示，并提示「两次查询未移除任何结果键」。上方诊断仍显示输入提示词时执行的 `> 1` 对照，筛选后是 **3 组**。

诊断完成后，页面有时会显示「Gemini 正在补充讲解…」。可以先用已经显示的课程依据和 SQL 表继续后面的步骤。

**背后用到的技术**　LangGraph 编排课程依据和 SQL 实验两条路径。后端经 MCP 调用工具，在合成数据上用 SQLite 执行预设的参数化查询。两组结果可以先展示，Gemini 再根据已有证据异步补充讲解。课程资料链接来自预先维护的课程卡片。

### 2.4 做一题迁移练习

1. 找到题目操作栏下方的「迁移练习」卡片（位于 SQL 诊断上方），点「换一组数据练练」。
2. 看新表和其中的 `HAVING COUNT(*) >= 2`。按照这条演示路线，选择文字为 **「2 行」**的选项。选项顺序可能变化。
3. 点「提交迁移题」。应看到「答对了。」以及「SQLite 查询结果」，其中列出保留的两个分组。侧栏的「已作答」仍是 **4**，这次变式结果保存在当前错题下。
4. 用 `Command + R` 刷新网页，确认迁移练习反馈仍可查看。

如果你的原会话已经生成过变式，以页面实际展示的题和数据为准。

**背后用到的技术**　当前题库的 24 道正式题都有迁移模板。系统按原题和知识点映射选模板，从固定随机种子生成合成数据。MCP 工具执行 SQLite 查询来确定正确选项和干扰项，变式结果独立保存。

### 2.5 保存复习要点，回看学习记录

1. 仍在 75 号错题反馈页，找到「SQL 错题诊断」中的「保存为学习记录」。保留默认「复习要点」，或改成以下内容。

   > 我容易把 > 当成 >=。下次先找计数恰好等于阈值的组。

2. 点「确认保存」。看到「学习记录已保存。」后，点左侧「学习记录」，在弹窗中展开「已确认的学习记录」，就能看到这一条。可用「修改」或「删除」管理记录；删除需要再次确认。完成后点弹窗右上角关闭按钮，或按 Esc。
3. 刷新后可以用同一个普通窗口继续，或在「学习记录」弹窗点击题目序号回看。做了下一题后，也可用题目上方的向左箭头「上一题」回看判分、诊断和迁移练习，再点「返回当前进度」。

**背后用到的技术**　浏览器的会话 Cookie 对应后端的学习者记录。正式答题和聊天按题目存入 SQLite。复习要点通过 LangGraph 的「暂停 → 学生确认 → 继续」流程，确认后才写入学习笔记。下一题辅导会按主题读取相关的已确认笔记。

### 2.6 和 Gemini 多轮对话

1. 点当前反馈页底部的「下一题」。按演示路线，会进入另一道相关聚合题。选择 **A**，点「提交答案」，留在错题反馈页。
2. 在右侧「对话辅导」底部输入框粘贴下面这句，点「发送」。也可以点题目下方的「问问助教」定位输入框。手机会切到助教面板。Enter 发送，Shift + Enter 换行。

   > 我不明白为什么要先分组。能给我一点提示吗？先别告诉我答案。

3. 等待「助教正在思考…」结束。看到「LLM 助教」表示本轮返回了模型回复。引用到课程资料时，点击回复下方的知识卡标题可打开对应的官方文档。想和第一轮对照，在同一个框里再问「我数的是结果有几行，为什么和每组的 COUNT(*) 不一样？」。若本轮读取了第 2.5 节保存的笔记，回复下方会显示「本轮辅导读取了已确认的学习记录」。若显示「课程提示」，可先阅读备用说明。
4. 在**同一个输入框**再粘贴下面这句，点「发送」。对照两轮内容，第一轮给概念提示，第二轮用例子解释两者的区别。

   > 能用一个不同的简短例子，帮我区分 GROUP BY 和 HAVING 吗？

5. 想体验同题历史回查，可在独立练习会话里第一轮先请助教举例，再在同一道错题上继续问到第七轮。第八轮发「请回到第 1 轮，复述刚才的例子」。成功后回复下方显示「本题第 1 轮对话」。用 Safari 网页检查器打开「网络」，筛选 `tutor`，在这次请求的「预览」响应里核对 `trace` 中的 `retrieve_tutor_history` 和 `turn_number: 1`。本题一共允许八轮辅导。

**背后用到的技术**　FastAPI 后端用 HTTPX 调用 `.env` 配置的 Gemini 服务，走兼容 OpenAI 的 `chat/completions` 接口。Gemini 可以用 `retrieve_course_notes` 把自然追问转成课程查询，后端使用与实验教练相同的本地课程索引，结合 SQLite FTS5 和 BGE 检索最多三张卡片。Safari 网页检查器的 `tutor` 响应里，`trace` 的 `retrieved_ids` 记录检索返回的卡片，`corpus` 记录索引版本，`citations` 记录回复实际引用的来源。索引缺失时搜索随仓库发布的审核卡片。检索无结果时仍可取用本题的预写笔记。助教默认带入当前题最近五轮问答和相关学习笔记。学生明确指定窗口以外的轮次时，助教按需调用只读工具取回那一轮。后端校验工具参数、返回结构和引用，模型回复不可用时提供预置提示。

### 2.7 用错题教练查跨考点证据

这条演示使用 81 号题。已经在该题反馈页时，直接从第 3 步开始。之前已经走过 75 号题路线时，可开一个干净的浏览器会话来复现这道题。Chrome 的无痕窗口共享一次会话，可以先关闭全部无痕窗口再开启新的。普通窗口的进度可以继续保留。

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
8. 还可以在这道题点「换一组数据练练」。看两张合成表和查询，对每个左表键数匹配记录。找不到匹配时仍计一行，答案以页面数据为准。选择行数后点「提交迁移题」，查看「SQLite 查询结果」。

**背后用到的技术**　LangGraph 让 Gemini 按「规划 → 调用工具 → 观察结果 → 决定下一步」运行，MCP 提供检索和 SQL 实验工具。跨考点检索先拆出 `LEFT JOIN` 和 `COUNT(*)`，分别找证据，只有证据缺口的考点才补查。

## 3. SQL 实作工作台

在桌面点左侧「SQL 实作」。手机点顶部「SQL 实作」，用底部「练习」和「助教」在编辑区与实验教练之间切换。进入后能看到「选择实作任务」和「你的 SQL」。可以直接开始，实作活动单独记录，正式已答题数保持原值。

### 3.1 写 SQL、运行和查看反例

1. 在「选择实作任务」选「保留零订单客户的计数」。展开「表结构与样例数据」，确认有 `customers` 和 `orders` 两张表。
2. 点击「你的 SQL」，按 `⌘A` 选中原内容，粘贴下面的查询。它按连接后的行数计数，会在边界数据上出错。

   ```sql
   SELECT c.customer_id, COUNT(*) AS order_count
   FROM customers AS c
   LEFT JOIN orders AS o ON c.customer_id = o.customer_id
   GROUP BY c.customer_id;
   ```

3. 点「运行 SQL」。完成后在编辑器下方看「查询结果」，样例上会返回客户和订单数。接着点「提交验证」，等待出现「发现结果差异」。展开「查看反例与结果差异」，对照「你的结果」与「预期结果」，找到同一个 `customer_id` 在前者计为 **1**、后者计为 **0** 的行。上方反例数据中的 `orders` 表可以用来核对该客户是否有订单。
**背后用到的技术**　SQLGlot 解析并限制查询为允许的只读 SQL。MCP 工具调用隔离进程，在合成的 SQLite 数据上执行。「运行 SQL」查样例，「提交验证」逐组比较你的查询与参考查询的结果，并展示实际反例。

### 3.2 用实验教练定位错误，修好后再验证

1. 保持上一节的 SQL 在编辑器里。在右侧「实验教练」底部的「向实验教练提问」粘贴下面这句话，然后点「请教实验教练」。窄屏先点底部「助教」。发送的是当前编辑器中的 SQL 和这条问题。

   > 为什么没有订单的客户被计为 1？请用 check_student_sql 核对边界并给出提示

2. 等右侧「选定实验」显示「已完成」，先看提示，再展开「查看实验依据」。如果教练调用了 SQL 检查工具，这里会展示它实际执行的验证结果。展开「执行轨迹」，查看是否出现「核对场景与边界」。「运行指标」显示耗时和工具调用次数。
3. 回到「你的 SQL」，粘贴下面的修正版本，再点「提交验证」。页面应显示「通过当前测试」和「已检查 4 / 4 组数据」。`LEFT JOIN` 保留零订单客户，`COUNT(o.order_id)` 跳过该行的 `NULL`。通过状态对应这四组数据。

   ```sql
   SELECT c.customer_id, COUNT(o.order_id) AS order_count
   FROM customers AS c
   LEFT JOIN orders AS o ON c.customer_id = o.customer_id
   GROUP BY c.customer_id;
   ```

**背后用到的技术**　实验教练用 LangGraph 组织 Gemini 的计划、MCP 工具执行和结果反馈。教练可按疑问选择检查当前 SQL、验证边界或查课程。后端校验计划和引用，并把实际执行记录给页面展示。

### 3.3 问 SUM 规则，查看课程检索结果

1. 在「选择实作任务」改选「汇总可空金额」。在「你的 SQL」粘贴下面的查询。可以先点「运行 SQL」看样例结果，再等运行结束后发问。

   ```sql
   SELECT SUM(amount) AS total FROM line_items;
   ```

2. 在右侧「向实验教练提问」粘贴下面的内容，点「请教实验教练」。这是一次专门请求查课程依据的提问。

   > 这是概念问题。请先用 search_course 检索 SQLite SUM 在空表和全 NULL 时的规则，引用对应课程依据。

3. 完成后展开「查看实验依据」，在检索卡片中找 **「SUM 保留求和的空值语义」**。卡片说明，当没有任何非 `NULL` 输入时，无论是空表还是全 `NULL`，`SUM` 都返回 `NULL`。如果教练在回答正文里引用了该卡片，正文下方也会显示引用。点击带链接的卡片标题，可在新标签页查看卡片预先关联的 SQLite 官方资料。课程摘录来自项目维护的知识库，Gemini 根据取回的内容组织提示。
4. 在同一条实验记录里展开「执行轨迹」，找到「检索课程依据」和「记录课程版本」。使用新版混合索引时，会显示 `hybrid · 课程版本 …`。本次交付验证的版本以 `af0601a9eb13` 开头。以后更新课程并重建索引后，版本号会随课程内容变化。`keyword` 表示关键词检索，`reviewed_cards` 表示直接从审核课程卡片匹配。

如果出现「仅保留证据（降级）」，已有实验依据仍可展开。本轮没有「检索课程依据」轨迹或看不到 `SUM` 卡片时，可用第 6 节检查 Gemini，再在同一任务重发第 2 步的问题。若有卡片但检索模式是 `keyword` 或 `reviewed_cards`，按第 5.2 节核对 `.env` 的索引文件与嵌入模型目录，重启后发起新一轮查看。

**背后用到的技术**　这是混合检索 RAG。课程材料按 Markdown 小节切成卡片。SQLite FTS5 用 BM25 做关键词排序，BGE 把问题和卡片编码成向量，用相似度找语义相关的内容。搜索工具组合两路结果，Gemini 参考取回的卡片组织回答。

### 3.4 恢复草稿，查看历史实验

1. 在上一节看到「草稿已保存」后刷新网页，再点「SQL 实作」和「汇总可空金额」。「你的 SQL」应恢复刚才输入的 `SUM` 查询。
2. 在右侧「最近实验」按时间点选上一节的「请教实验教练」记录。展开「查看本次 SQL」「查看实验依据」或「执行轨迹」，可以看到当时的查询、检索卡片和课程版本。
3. 想继续改某次查询，点击「恢复此运行 SQL 到编辑器」。执行中的记录可以点「取消执行」。中断的记录如果显示「恢复执行」，可以用这个按钮继续。
4. 展开「学习上下文」，能看到提交当时的正式首次作答、已确认笔记，以及可用的正式题 EpiKT 预测。想观察预测，可以先按第 2.1～2.2 节完成前三题并请求下一题，再到有同主题候选的实作任务提问。

**背后用到的技术**　FastAPI 把草稿、实验结果、工具轨迹和执行状态保存到 SQLite，按学习者和任务读取。草稿带版本号，两个标签页同时修改时会提示冲突。每条实验保存提交时的学习上下文，之后仍可核对当时使用的信息。

## 4. 页面或按钮和手册对不上

另开一个终端，复制以下命令。保持原启动终端运行。

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

| 看到的情况 | 下一步 |
|---|---|
| 网页打不开 | 回原启动终端，确认是否出现「QueryStep 已启动」。使用备用端口时，按启动终端打印的地址打开网页。 |
| 端口已占用 | 如果已有正常运行的实例，可以直接打开网页。要换到新版，回旧实例的启动终端按 `Ctrl+C`，再运行第 1 节。找不到旧终端时用第 5 节的备用端口。 |
| 看不到「EpiKT 推荐」 | 检查 `epikt_ready`。若为 `true`，先完成前三题，再在当前题提交后点「查看选题记录」查看回退提示。 |
| 看不到「运行诊断」或「带我弄懂这题」 | 先展开中间的「SQL 错题诊断」，或切到右侧「错题教练」标签。再核对 `diagnostics_ready` 与 `coach_ready` 是否为 `true`。实验能力支持 75 号与 81 号题的错题反馈页，其他错题用「对话辅导」。历史回看仅展示已保存结果。 |
| 第 6 题没有出现 81 号或第 4 题没有出现 75 号 | 用「查看选题记录」确认实际题号。如果沿用过往进度，想复现固定路线时用新的浏览器会话从第一题开始。 |
| 助教出现「课程提示／备用回复」或教练超时 | 可以继续查看已有证据、运行快速诊断和做迁移练习。想单独确认 Gemini 服务，运行第 6 节的探针。 |
| 刷新后进度不同 | 确认浏览器、原来的网址、站点 Cookie 和本机数据库一致。普通窗口与无痕窗口各有自己的进度。 |

## 5. 用备用端口启动或恢复环境

只需避开占用的端口时，在终端复制以下两行。看到「QueryStep 已启动」后，到浏览器打开 [http://127.0.0.1:5174/](http://127.0.0.1:5174/)。在该地址检查服务时访问 [备用健康状态](http://127.0.0.1:8001/healthz)。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
QUERYSTEP_BACKEND_PORT=8001 QUERYSTEP_FRONTEND_PORT=5174 QUERYSTEP_COACH_ENABLED=1 QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$PWD/artifacts/diagnostics-venv/bin/python" ./start.sh
```

### 5.1 独立诊断环境缺失时

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

### 5.2 知识库索引缺失时

索引是由课程 Markdown 构建的本地文件。首次安装或 `course_content/knowledge/` 更新后，在项目根目录重建索引，再按第 1 节启动。第一条模型路径适用于当前工作区，换机器时需改为该机器的 BAAI/BGE-small-zh-v1.5 本地模型目录。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
export QUERYSTEP_EMBEDDING_MODEL="$PWD/../examples/居丽叶简历项目7：医疗助手/medix-agent-swarm/.venv/models/bge-small-zh-v1.5"
export QUERYSTEP_KNOWLEDGE_INDEX="$PWD/artifacts/workbench-knowledge.sqlite3"
artifacts/diagnostics-venv/bin/python -m pip install -e '.[knowledge]'
artifacts/diagnostics-venv/bin/python -m course_content.knowledge_index \
  --output "$QUERYSTEP_KNOWLEDGE_INDEX" --model "$QUERYSTEP_EMBEDDING_MODEL"
QUERYSTEP_COACH_ENABLED=1 QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$PWD/artifacts/diagnostics-venv/bin/python" ./start.sh
```

如果本地 `.env` 定义了 `QUERYSTEP_KNOWLEDGE_INDEX` 或 `QUERYSTEP_EMBEDDING_MODEL`，启动时以 `.env` 中的值为准。将这两项分别指向上面生成的索引文件和用于构建索引的模型目录，再重启。索引缺失时教练回退到审核卡片，模型和索引不匹配时使用关键词检索。

## 6. 单独确认 Gemini 服务

如果网页能做题但助教连续回退，在另一个终端复制以下命令。这个探针会通过本机 `.env` 向已配置的模型服务发送合成 SQL 问题。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
set -a
source ./.env
set +a
artifacts/diagnostics-venv/bin/python -m tutor.check_provider
```

查看探针是否返回模型与检查结果。遇到 `ReadTimeout` 时可以先用网页的快速诊断和迁移练习，模型联通后再试辅导。跨考点检索实现、评估和补查的实测范围见开发方案。 [自主错题教练与课程知识库开发方案](QueryStep%20自主错题教练与课程知识库开发方案.md)

## 7. 工程复验

### 7.1 用独立数据库重复验收

普通体验直接从第 3 节开始即可。复现验收时，在另一个终端用新的本地数据库启动，原来的 8000 和 5173 服务可以保持运行。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
set -a
source ./.env
set +a
wb_test_dir=$(mktemp -d "$PWD/artifacts/workbench-test.XXXXXX")
export QUERYSTEP_DATABASE_URL="sqlite:///$wb_test_dir/practice.sqlite3"
export QUERYSTEP_DIAGNOSIS_CHECKPOINTS="$wb_test_dir/checkpoints.sqlite3"
export QUERYSTEP_EPIKT_RUN="$PWD/artifacts/epikt-dbe-fold0"
export QUERYSTEP_CATALOG="$PWD/artifacts/dbe-sql-approved.json"
export QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_COACH_ENABLED=1
artifacts/diagnostics-venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

等后端显示启动完成，另开一个终端启动前端。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep/web"
QUERYSTEP_API_PROXY=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

打开 [验收工作台](http://127.0.0.1:5174/)，按第 3.1～3.4 节操作。也可以另开终端，在项目根目录运行浏览器验收。需已安装本地 Playwright 和 Chromium。

```bash
export NODE_PATH="$PWD/artifacts/browser-tools/node_modules"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/artifacts/browser-tools/browsers"
QUERYSTEP_TEST_WEB_URL=http://127.0.0.1:5174 node tests/browser_workbench.cjs
QUERYSTEP_TEST_WEB_URL=http://127.0.0.1:5174 QUERYSTEP_WORKBENCH_ISOLATED_DB=1 node tests/browser_workbench.cjs --real
```

默认测试完全模拟 API；`--real` 会创建合成学习会话并调用已配置模型，不能指向真实学习数据库。

如需同时验证新版课程索引，在执行 `--real` 命令前，先运行下面这行读取索引版本。如果本机索引配置在其他路径，替换命令中的文件名。测试会检查 `SUM` 卡片及刷新后显示的版本。

```bash
export QUERYSTEP_TEST_EXPECT_COURSE_CORPUS="$(sqlite3 -readonly artifacts/workbench-knowledge.sqlite3 "SELECT json_extract(data, '$.corpus_sha256') FROM manifest;")"
```

### 7.2 复现 SQL 诊断比较

在项目根目录运行标签审计，不调用模型、不接触学习数据库：

```bash
artifacts/diagnostics-venv/bin/python -m evals.workbench \
  --split all --validate-labels --output artifacts/workbench-label-audit.json
```

100 个冻结案例按任务划分为 60 个开发、40 个测试；每个标签审计四场景和三个种子。案例属于内部作者/编码助手编写，不能称为外部独立基准。

四臂真实模型比较会产生提供方调用与费用。先按第 5.2 节配置本地嵌入模型，并将含新版课程的索引生成到 `artifacts/workbench-knowledge.sqlite3`，再运行：

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

### 7.3 尚待执行的人工验收

以下是验收方法，不是已完成的试用结果：

1. 请未参与编写的 SQL 教师或熟悉 SQL 的审核者，独立核对 10 个任务的要求、数据约束、参考查询和 100 个冻结标签，记录不同意见。参考定义位于 `course_content/sql_tasks.py`，标签位于 `evals/workbench_cases.py`；不能只依据程序输出确认程序自己的规则。
2. 四臂命令可加 `--annotation-output artifacts/workbench-human-review.json` 生成未填写的人审文件。将它与含 arm/答案映射的原报告分开，审核者填写 `manual_review` 中的判断恰当性、提示帮助性、证据支持性及说明。输出结构仍可能暴露实验臂，因此不是严格双盲；未填写字段必须保持 null，不能默认通过。
3. 征得参与者同意后，使用第 7.1 节的独立数据库进行小规模试用。明确告知 SQL 和提问可能发送给已配置模型，不输入个人信息或生产数据库内容，不收集不必要身份信息。
4. 让参与者自行完成“保留零订单客户”“筛选已付款的连接”“空表求和”三个不同任务，观察能否找到入口、运行、理解反例、自主修正及刷新恢复。记录卡住的位置、误导提示、调用失败、独立完成情况，而不是由演示者代答。
5. 随后换一个未演示的同类任务，先不提供提示，记录首次独立尝试与理由。只把结果用于发现体验问题和提出教学假设；少量试用不能推出显著学习增益。

完成后再将实际人数、日期、审核分歧和发现的问题写入审计报告；当前不具备这些记录。
