# QueryStep 本地启动与体验手册

本手册适用于当前 Mac 上的 QueryStep。EpiKT 使用已训练的 DBE-KT22 权重在 Mac CPU 上选题，Gemini 使用本机 `.env` 中的服务配置。启动和体验过程都可以在 Mac 上完成。

如果服务已经启动，可以直接打开 [QueryStep 学生端](http://127.0.0.1:5173/)，从第 3 节开始。关机或重启后，从第 1 节开始。

## 1. 确认本地文件

以下命令使用本机项目目录 `~/Desktop/实习/projects/QueryStep`。如果你把项目放在其他位置，将命令里的目录换成实际路径。启动需要以下内容。

| 内容 | 路径或名称 | 用途 |
|---|---|---|
| Python 环境 | Conda 的 `querystep` | 运行后端和 EpiKT |
| 前端依赖 | `web/node_modules/` | 启动 React 学生页面 |
| Gemini 配置 | 项目根目录的 `.env` | 读取 API 地址、密钥、模型 ID 和超时配置 |
| 正式模型产物 | `artifacts/epikt-dbe-fold0/` | 加载 checkpoint、校准参数和题目映射 |
| 演示题库 | `artifacts/dbe-sql-approved.json` | 提供已与正式模型对齐的 24 道 SQL 练习 |

正式模型目录包含 `qid_alibi_model.ckpt`、`config.json`、`keyid2idx.json`、`question_kcs.json`、`training_metrics.json`、`calibration.json` 和 `test_metrics.json`。恢复文件时可以整体复制这个目录。配置和映射与权重配套，加载时会检查它们的文件指纹。

## 2. 一键启动

在 Mac 的任意终端运行这一条命令。

```bash
"$HOME/Desktop/实习/projects/QueryStep/start.sh"
```

如果终端已经位于项目根目录，运行 `./start.sh` 即可。脚本会激活 `querystep` 环境，检查 EpiKT 权重与题库，读取 `.env` 启用这套题库的 Gemini 辅导，再启动后端和前端。看到 `QueryStep 已启动` 后打开 [QueryStep 学生端](http://127.0.0.1:5173/)。保留该终端，按 `Ctrl+C` 可以停止两个服务。

如果端口已被之前启动的 QueryStep 占用，可以直接使用现有服务。需要改用其他端口时，可在项目根目录运行 `QUERYSTEP_BACKEND_PORT=8001 QUERYSTEP_FRONTEND_PORT=5174 ./start.sh`，然后打开脚本打印的地址。

### 手动启动与排查

#### 终端 1 · 后端

打开 Mac「终端」，逐段运行下面的命令。项目路径带中文，复制时保留引号。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
conda activate querystep

set -a
source ./.env
set +a

export QUERYSTEP_EPIKT_RUN="$PWD/artifacts/epikt-dbe-fold0"
export QUERYSTEP_CATALOG="$PWD/artifacts/dbe-sql-approved.json"
export QUERYSTEP_LLM_ALLOW_MAPPED_ITEMS=1
```

最后一个开关允许 Gemini 为这套 DBE 演示题提供辅导。它在加载 `.env` **之后**设置，并随当前终端启动的后端生效。当前演示使用的模型 ID 是 `gemini-4-argon-high`。演示时可直接使用第 3 节给出的 SQL 提问。

首次启动，或更换权重、题库后，先核对模型与题库是否配套。

```bash
python -m course_content.check_catalog \
  --run "$QUERYSTEP_EPIKT_RUN" \
  --catalog "$QUERYSTEP_CATALOG"
```

当前产物预期显示 `items: 24`、`mapped_and_supported: 24`、`issues: []`，以及 `production_package_compatible: true`。通过后启动后端。

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

看到 `Application startup complete` 后保留此终端。后端地址是 `http://127.0.0.1:8000`。

#### 终端 2 · 前端

另开一个终端。当前 Mac 的前端依赖已经安装，可以直接运行。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep/web"
curl -fsS http://127.0.0.1:8000/healthz
npm run dev -- --strictPort
```

健康检查里，`epikt_ready: true` 表示正式权重已加载且题库匹配，`tutor_ready: true` 和 `tutor_status: configured` 表示后端已读取 Gemini 配置。两轮真实辅导是否成功，以学生页面的回复来源为准。Vite 显示本地地址后，保留此终端并打开 [QueryStep 学生端](http://127.0.0.1:5173/)。

## 3. 从学生视角完整体验

第一次演示建议用一个新的无痕窗口，获得独立的作答记录。以下选项顺序对应当前 24 题演示题库和正式权重。想正常练习时，可以自行作答。

1. **开始练习。** 打开学生端，点「开始练习」。左侧会显示「已作答」和「答对」。
2. **完成三道冷启动题。** 第 1、2、3 题依次选择 **B、A、B**。每题点「提交答案」，看到反馈后再点「下一题」。这条演示路径会得到三次错题记录，前三题显示「规则推荐」。
3. **确认真实 EpiKT 推荐。** 第 4 题应显示「EpiKT 推荐」。选 **B** 并提交，这条路径会进入错题反馈。点「查看选题记录」，可以看到实际题号、规则对照题号和 EpiKT 模型版本。当前路径上两种评分方式都选到题号 68。第 4 节给出了两者选出不同题目的路径。
4. **体验 Gemini 两轮辅导。** 在第 4 题的「问问助教」区域，先发送「请查阅课程规则，用一个提示解释本题涉及的 SQL 概念，不要直接给出答案。」看到回复后，再发送「请用例题工具给一个不同的简短例子，帮我理解这个概念。」验收时看两轮是否都标为「LLM 助教」。此前联合验收中，第一轮查询了课程规则并给出提示，第二轮调用了例题工具并给出独立例子。
5. **验证刷新续学。** 仍停在这道错题时刷新页面。作答计数、错题反馈和两轮辅导应恢复。然后点「下一题」，提交一次作答，确认练习可以继续。

正常练习可继续使用同一个浏览器窗口。同一浏览器保留站点 Cookie 时，可以恢复对应进度。默认的作答记录保存在 `artifacts/querystep.sqlite3`，重启前后端后可以继续使用。

## 4. 单独复现 EpiKT 与规则选出不同题目

用另一个独立浏览器会话开始练习。可以先完成第 3 节，再关闭该浏览器的所有无痕窗口，重新打开一个无痕窗口。

1. 前三题依次选 **B、A、A**。每次提交后点「下一题」。这次历史是错、错、对。
2. 在第 4 题确认「EpiKT 推荐」，任选一项提交，再点「查看选题记录」。
3. 当前权重和题库下，EpiKT 选出 **75 号题**，同一历史下的规则对照选出 **69 号题**。这是用本机正式权重核对过的一条对照。若同时想看错题辅导，第 4 题选择 **A** 会进入错题反馈。

## 5. 停止、重启和排查

一键启动时，在运行脚本的终端按 `Ctrl+C`。手动启动时，在前端和后端各自的终端按 `Ctrl+C`。下次按第 2 节重新启动，再用同一个浏览器继续学习。

| 现象 | 怎么处理 |
|---|---|
| `conda activate` 报终端未初始化 | 在当前 Mac 执行 `source /opt/miniconda3/etc/profile.d/conda.sh`，再运行 `conda activate querystep`。 |
| 报端口已占用 | 用下方命令查谁在监听。如果两个服务都已运行且健康检查通过，可以直接打开学生页。如果要更新后端配置，在原后端终端按 `Ctrl+C` 后再启动。 |
| 页面打不开或显示「暂时无法恢复练习」 | 分别确认 8000 和 5173 都在监听。先访问后端的 `/healthz`，再访问学生端。 |
| 前三题显示「规则推荐」 | 这是新会话的冷启动。提交第三次作答后点「下一题」。 |
| 第 4 题仍走规则 | 查 `epikt_ready`。如果是 `false`，检查权重和题库路径并重跑预检。如果是 `true`，提交当前题后打开「查看选题记录」，查看本轮回退原因。 |
| 答对后没有「问问助教」 | 辅导入口在当前题的错题反馈页。可以用第 3 节的固定路径体验。 |
| 辅导显示「审核提示」 | 检查 `.env` 是否在启动后端前加载，确认随后执行了 `export QUERYSTEP_LLM_ALLOW_MAPPED_ITEMS=1`。两项都已配置时，可以运行下方 Gemini 探针排查服务和工具调用。 |
| 找不到 `vite` | 在 `web/` 执行 `npm ci` 安装锁定依赖，再运行启动命令。 |

检查本地端口和后端状态。

```bash
lsof -nP -iTCP:8000 -iTCP:5173 -sTCP:LISTEN
curl -fsS http://127.0.0.1:8000/healthz
```

如果后端由 Codex 启动，找不到原终端，可以先在自己的终端查到进程。确认命令行显示 `uvicorn api.main:app` 后，再单独执行停止命令。

```bash
backend_pid=$(lsof -nP -t -iTCP:8000 -sTCP:LISTEN)
ps -p "$backend_pid" -o pid=,command=
```

```bash
kill -TERM "$backend_pid"
```

需要排查 Gemini 时，另开一个终端执行探针。它会用合成 SQL 问题实际调用已配置的模型服务。

```bash
cd "$HOME/Desktop/实习/projects/QueryStep"
conda activate querystep
set -a
source ./.env
set +a
python -m tutor.check_provider
```

如果将来要在另一台 Mac 重建环境，先准备 Conda、Node.js、对应版本的项目源码和第 1 节列出的本地模型与题库文件。然后从项目根目录运行以下命令，配置自己的 `.env` 后再回到第 2 节。

```bash
conda create -n querystep python=3.11 pip
conda activate querystep
python -m pip install -e '.[kt,api]'
npm --prefix web ci
```

## 6. 启用 SQL 错题诊断与学习记录

在现有 Mac 环境安装一次诊断依赖。在项目根目录执行：

```bash
conda activate querystep
python -m pip install -e '.[api,kt,diagnostics]'
QUERYSTEP_DIAGNOSTICS_ENABLED=1 ./start.sh
```

已使用独立开发环境 `artifacts/diagnostics-venv/` 时，可以直接复用：

```bash
QUERYSTEP_DIAGNOSTICS_ENABLED=1 QUERYSTEP_PYTHON="$PWD/artifacts/diagnostics-venv/bin/python" ./start.sh
```

打开 [QueryStep 学生端](http://127.0.0.1:5173/)，在新会话前三题依次选 **B、A、A**，第四题选 **A**。在 75 号错题反馈页点「运行诊断」，输入「为什么分组后还要检查 HAVING？请用严格大于 1 的示例。」完整诊断会展示课程依据，以及合成数据上的 **4 组 → 3 组**。选择「大于等于」，保留阈值 1，再点「比较结果」即可观察边界。若模型超时，页面会保留已经取得的证据和可用提示。仍可点击「比较结果」直接运行参数实验，或重新发起诊断。

完整诊断会生成一条待确认的复习建议。可以刷新页面再确认，也可以修改后保存或跳过。侧栏的「已确认的学习记录」可以修改或删除。保留当前会话 Cookie，下次遇到相关错题时助教可读取这些记录。点击「重新开始」会创建新学习身份。实验结果和复习建议分别保存，作答计数只随正式提交变化。

复现工具执行和回归测试：

```bash
python -m sql_lab.check
python -m sql_lab.check --fixture left_join_predicate@1
python -m unittest discover -s tests
```

扩展阶段、测试边界和评估命令见 [多 Agent 扩展开发文档](QueryStep%20多%20Agent%20扩展开发文档.md)。
