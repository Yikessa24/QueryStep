# QueryStep 操作指南

命令均从项目根目录执行，除非另有说明。日常演示可用原创题库、SQLite、规则推荐和审核提示。正式 EpiKT 验收需要同域权重和获准展示的匹配题库。真实 LLM 联调可先用原创题单独进行。

## 1. 准备数据和训练

已有 `data/processed/dbe_kt22_sql_core/manifest.json` 时直接使用该目录。需要重建时，将官方 DBE-KT22 CSV 归档放入 `data/DBE-KT22/` 后运行：

```bash
conda create --override-channels -c conda-forge -n querystep python=3.11 pip
conda activate querystep
python -m pip install -e '.[kt,api,test]'
python -m data_pipeline.preprocess --scope sql-core --maxlen 200
```

已存在的预处理目录可保留，通过 `--output` 指定新的输出目录。训练、校准、测试和回放使用同一份数据清单。在 AutoDL 等 GPU 环境配置适配的 CUDA 版 PyTorch，按 [GPU 训练指南](GPU_TRAINING.md) 上传数据、启动训练和下载完整 run。正式步骤如下：

```bash
RUN=artifacts/epikt-dbe-fold0
python -m kt.train --run "$RUN"
python -m evals.calibrate_kt --run "$RUN"
python -m evals.evaluate_kt --run "$RUN"
python -m json.tool "$RUN/test_metrics.json"
```

保留完整 run，尤其是权重、配置、题目和 KC 映射、校准及测试报告。权重准入需要 `passes_scoring_gate=true`。`test_metrics.json` 中的 `common_coverage` 对齐题目先验、近期 KC 正确率、BKT 和 EpiKT 的评分对象。测试集用于最终报告，调整训练配置时依据训练折和验证折。

## 2. 配置和验证 LLM

模型服务使用 OpenAI 兼容的 `/models` 和 `/chat/completions`。已配置本地 `.env` 时，直接加载它并运行探针。

```bash
set -a
source ./.env
set +a
python -m tutor.check_provider
```

新环境或更换供应商时，在受控的 shell 或部署凭据管理器中配置。

```bash
export QUERYSTEP_LLM_BASE_URL='https://你的模型服务/v1'
export QUERYSTEP_LLM_TIMEOUT_SECONDS=5
read -r -s -p 'API key: ' QUERYSTEP_LLM_API_KEY
export QUERYSTEP_LLM_API_KEY
printf '\n'

python -m tutor.check_provider --list-only
python -m tutor.check_provider
```

输入密钥的示例使用 Bash。未设置 `QUERYSTEP_LLM_MODEL` 时，探针从服务实际返回的列表中优先选稳定的 Gemini Flash 文本模型。按探针结果设置 `QUERYSTEP_LLM_MODEL` 后启动 API。也可显式指定列表中的其他模型并重跑探针。探针只发送合成 SQL 问题，分别检查基本对话、函数调用、可校验的 JSON、原生 JSON 模式和两轮辅导。项目以服务端校验的结构化动作驱动 UI。原生 JSON 模式是单独报告的兼容能力。

远程 HTTP 默认关闭。仅在已确认受控传输边界的私有联调环境中，可显式设置 `QUERYSTEP_LLM_ALLOW_INSECURE_HTTP=1`。明文 HTTP 无法防止链路上的观察者读取密钥和消息。映射到研究数据的题默认继续用审核提示。外发学生自由文本前另行确认可发送范围和模型供应商条款。

`/healthz` 的 `tutor_status=configured` 表示配置可用来发起请求。模型可达性和工具能力以探针输出为准。超时、调用超量或输出校验失败时，页面显示审核提示，作答账本照常工作。

## 3. 启动和验收学生流程

在本机激活项目环境并加载配置。

```bash
conda activate querystep
set -a
source ./.env
set +a
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

另开终端，在 `web/` 下运行 `npm ci`、`npm run dev`，打开 Vite 显示的地址。用新会话开始练习，答错首题，连续询问两轮，刷新检查作答与辅导是否恢复，再打开下一题并提交。练习和调试数据应使用独立数据库。

启用正式 EpiKT 时，先在项目根目录检查完整 run 和获准展示的题库。下列检查可在 Mac 运行：

```bash
python -m course_content.check_catalog \
  --run artifacts/epikt-dbe-fold0 --catalog artifacts/dbe-sql-approved.json
```

本机已准备好上面的演示题库。需要在其他机器重新生成时，从有权使用的原始归档和对应预处理产物导入。

```bash
python -m course_content.import_dbe --authorized --demo-context \
  --output artifacts/dbe-sql-approved.json
```

预检核对文件指纹、模型索引、题号、KC、训练覆盖和准入报告。报告只打印内部题目 ID 与错误原因。通过预检后，在 Linux CUDA 环境将 `QUERYSTEP_EPIKT_RUN` 指向完整 run，将 `QUERYSTEP_CATALOG` 指向该题库 JSON。由 GPU 加载测试确认 checkpoint 可反序列化并运行，再检查 API：

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

确认 `epikt_ready` 为真后，用新会话先完成三道冷启动题。观察下一题的推荐来源和选题回放。用同一组历史、候选和课程约束保存一条模型与规则选中不同题的记录。若 API 和前端分开运行，使用 [GPU 训练指南](GPU_TRAINING.md) 中的本地端口转发。

### 在同一留出历史上回放选题

在包含应用源码的环境使用获准审阅的题库，且数据目录保留原预处理生成的 `test.csv`。GPU 最小训练包默认只包含训练与校准需要的文件，回放时另外同步 `api/` 和这份 `test.csv`。使用与训练同指纹的数据清单。

```bash
python -m evals.replay_policy --run artifacts/epikt-dbe-fold0 \
  --catalog artifacts/dbe-sql-approved.json
```

输出为 run 中的 `policy_replay.json`。对照记录覆盖率、动作和题目变更，并仅对实际作答题计算 Brier。该记录用于检查决策差异；学习效果需另做教学实验。内部检查 CPU 冒烟权重时，需要显式传 `--allow-smoke`。

## 4. 测试

```bash
python -m unittest discover -s tests -v
npm --prefix web run build
```

测试 EpiKT 评分需要项目数据与 CPU 冒烟权重。缺少时先准备数据，再执行 `python -m kt.train --smoke --run artifacts/epikt-smoke`。这些用例会在数据或冒烟权重缺失时明确跳过。

使用空的 PostgreSQL 测试数据库时，先把连接串设置为 `QUERYSTEP_TEST_DATABASE_URL`，再运行：

```bash
python -m unittest discover -s tests -p test_practice_api.py -v
```

可选浏览器测试使用独立安装的 Playwright 和 Chromium。在启动 API 与 Vite 后，将 `NODE_PATH` 指向测试工具的 `node_modules`，执行 `node tests/browser_smoke.cjs`。测试默认使用原创题和审核提示。指定 `QUERYSTEP_TEST_TUTOR_LLM=1` 时，测试要求两轮均返回模型辅导及预期的工具引用，适合对接可控的协议替身。

## 5. 部署

本机 Docker Compose 预览见 [部署说明](README.md)。配置 `QUERYSTEP_DB_PASSWORD` 后运行 `docker compose config --quiet` 和 `docker compose up --build`，浏览器访问本地 8080 端口。Compose 以 PostgreSQL 保存学生状态，并可配置 LLM。GPU 权重接入使用独立 CUDA 环境和授权题库。

用于公开学生服务前，应补做真实模型联调、完整容器验证、服务入口鉴权和请求限流，并通过 HTTPS 提供学生端。当前匿名 Cookie 按浏览器隔离学习状态，适用于本机或受控演示。跨设备身份、公开服务和正式学习效果是独立验收范围。
