# 环境与部署

## 1. 本机统一 Python 环境

建议在单个 Python 3.11 环境内一次性安装全部运行时依赖（避免 `querystep` 与额外 venv 分裂）：

```bash
conda create --override-channels -c conda-forge -n querystep python=3.11 pip
conda activate querystep
python -m pip install -e '.[api,diagnostics,kt,knowledge,test]'
```

`start.sh` 会优先使用显式指定的 `QUERYSTEP_PYTHON`；若未指定且存在历史 `artifacts/diagnostics-venv/bin/python` 则自动复用，否则直接使用当前激活环境中的 `python`。正式 `qid_alibi` 训练建议在 Linux NVIDIA CUDA 环境执行；在线推理在 macOS/Linux CPU 上由 `kt/cpu_epikt.py` 兼容运行。

## 2. Docker Compose 全功能部署

从项目根目录复制 `.env.example` 为 `.env`，设置 `QUERYSTEP_DB_PASSWORD`（及可选 LLM 配置）：

- **基础模式（原创题库 + PostgreSQL + SQL 实作工作台 + 诊断与 SSE）**：直接运行 `docker compose up --build`，访问 `http://127.0.0.1:8080`。
- **完整模式（启用本地已授权 EpiKT 权重与混合知识索引）**：在 `.env` 中配置以下容器内路径（由 `compose.yaml` 通过只读卷 `./artifacts:/app/artifacts:ro` 与 `./research:/app/research:ro` 挂载，不将私有权重或研究归档打入镜像层）：
  - `QUERYSTEP_DOCKER_CATALOG=/app/artifacts/dbe-sql-approved.json`
  - `QUERYSTEP_DOCKER_EPIKT_RUN=/app/artifacts/epikt-dbe-fold0`
  - `QUERYSTEP_DOCKER_KNOWLEDGE_INDEX=/app/artifacts/workbench-knowledge.sqlite3`
  - `QUERYSTEP_LLM_ALLOW_MAPPED_ITEMS=1`（确认允许后开启）

`deploy/nginx.conf` 已为 `/api/diagnosis/{run_id}/events` 单独关闭代理缓冲（`proxy_buffering off`、`proxy_cache off`、`proxy_http_version 1.1`、`Connection ""` 及长连接读超时），`compose.yaml` 已将诊断 LangGraph 检查点目录固定到独立可写卷 `/app/runtime`。镜像默认按 CPU 版 PyTorch 安装全部 extras（`api,diagnostics,kt,knowledge`），可通过 `QUERYSTEP_DOCKER_EXTRAS` 按需裁剪。

另一台装有 Docker 的机器拉取仓库后，可直接按 [Docker Compose 实机冒烟验收手册](DOCKER_SMOKE_TEST.md) 逐项执行验证。
