# QueryStep

以 EpiKT 选择下一道 SQL 练习。MVP 验证真实 EpiKT 选题和规则对照。完整版加入真实 LLM 多轮辅导，并与模板提示独立对照。

本地启动和学生端体验见 [QueryStep 本地启动与体验手册](docs/QueryStep%20本地启动与体验手册.md)。从数据准备到部署见 [操作指南](deploy/OPERATIONS.md)。当前验证范围及尚待验收的功能见 [工程审计报告](docs/工程审计与交付报告.md)。

多 Agent 扩展提供带课程引用和可运行 SQL 示例的错题诊断，以及学生确认后可复用的学习记录。启动方式见操作手册第 6 节，架构、接口和验收记录见 [多 Agent 扩展开发文档](docs/QueryStep%20多%20Agent%20扩展开发文档.md)。

| 目录 | 职责与当前进度 |
|---|---|
| data/ | DBE-KT22 官方归档及本地处理产物 |
| data_pipeline/ | DBE 原始适配、pyKT 切分和数据指纹，已实现 |
| kt/ | pyKT 源码定位、训练、权重校验和因果候选评分，已实现 |
| evals/ | pyKT 题目窗口 late_mean 评估，已实现 |
| api/ | 学生会话、受约束选题、服务端判分、作答流水和决策回放 |
| web/ | React / TypeScript 学生练习页和错题辅导 |
| course_content/、tutor/、migrations/ | 审核题库、只读工具辅导 Agent 和数据库初始化说明 |
| configs/、deploy/、tests/ | 数据范围、独立环境和回归验证 |
| docs/、research/ | 计划书与原始 EpiKT 研究材料 |

## 1. 环境

从项目根目录运行：

```sh
conda create --override-channels -c conda-forge -n querystep python=3.11 pip
conda activate querystep
python -m pip install -e '.[kt,api,test]'
```

在 Linux GPU 主机上，先按驱动安装匹配 CUDA 的 PyTorch 构建。研究目录中的 EpiKT 与 pyKT 实现是训练和评估的源码基准，项目代码只负责适配。

## 2. 数据准备

```sh
python -m data_pipeline.preprocess
```

默认生成 `data/processed/dbe_kt22_sql_core/`。已有输出目录时用 `--output` 指定新目录。用 `--scope all` 生成完整 DBE-KT22 实验数据。默认范围按 `configs/dbe_sql_core.json` 选取基础查询相关 KC，并排除依赖图片的题。

适配器从官方 CSV 重建原题交互，取每个学习者对每题最早完成的提交，筛除隐藏、用过提示、时间异常、答案冲突和与保留历史重叠的记录。随后写出 pyKT 六行格式，直接运行随附 `split_datasets.py`，由 pyKT 完成多 KC 展开、ID 映射、20% 学习者留出、五折划分和概念／题目窗口生成。训练和验证用额外生成的题目窗口 CSV，目标的各 KC 使用同一个答题前历史。完整来源哈希、清洗计数和切分规模在输出目录的 `manifest.json`。

## 3. 训练和评估

从 Mac 传输训练文件、在 Linux 配置 CUDA、取回 checkpoint 和接入学生端，见 [GPU 训练操作指南](deploy/GPU_TRAINING.md)。

```sh
# 本机检查真实前向、反向和 checkpoint 读写
python -m kt.train --smoke --run artifacts/epikt-smoke
# 可选，检查验证集校准。若拟合斜率不为正，停止并检查该次训练。
python -m evals.calibrate_kt --run artifacts/epikt-smoke --allow-smoke
python -m evals.evaluate_kt --run artifacts/epikt-smoke --allow-smoke

# Linux NVIDIA CUDA 上的正式首折训练
python -m kt.train --fold 0 --run artifacts/epikt-dbe-fold0
python -m evals.calibrate_kt --run artifacts/epikt-dbe-fold0
python -m evals.evaluate_kt --run artifacts/epikt-dbe-fold0
```

正式训练默认 `qid_alibi`，复用 pyKT 的加载器、Adam 训练循环与验证早停。评估使用 pyKT 的题目窗口 `late_mean`。冒烟使用小模型与部分 batch，产物只供本地验收。每个 run 绑定模型源码、训练数据、ID 映射和权重文件。模型概率接入学生策略前需完成留出评估与校准。

题目级评估复用研究包的 `evaluate_question_window_late_mean`，并在相同窗口对比题目先验、近期 KC 正确率和 BKT。准备好数据和本地冒烟 checkpoint 后，运行 `python -m unittest discover -s tests -v` 可验证切分、同题防泄漏、基线对齐和真实权重评分。

## 4. API 与前端联调

```sh
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

另开终端进入 `web/`，运行 `npm ci` 和 `npm run dev`，打开 Vite 输出的本地地址。默认用原创题库、SQLite、规则推荐和审核提示，可以完成选题、答题、错题辅导和续学。`/healthz` 同时返回模型配置状态。

在启动 API 的进程中设置 `QUERYSTEP_LLM_BASE_URL` 和 `QUERYSTEP_LLM_MODEL`，按服务要求设置 `QUERYSTEP_LLM_API_KEY`，可启用 LLM 辅导。模型返回引用或工具异常时使用审核提示。

在线 EpiKT 验收需要非冒烟权重、通过留出门槛的 `test_metrics.json`、同版本校准与映射，以及获准展示且可映射的题库。用 `QUERYSTEP_EPIKT_RUN` 和 `QUERYSTEP_CATALOG` 指定相应目录和 JSON。默认 Docker Compose 环境见 [部署说明](deploy/README.md)。

DBE-KT22 按已接受的协议用于分析建模。学生展示、在线模型使用和对外发布按确认的许可范围实施。原数据、处理数据、实验权重和匿名研究材料均从默认版本控制范围排除。
