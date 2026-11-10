# 环境与部署

本机使用独立 Conda 环境。正式 `qid_alibi` 训练和在线推理使用 Linux NVIDIA CUDA，按驱动安装对应的 PyTorch 构建。macOS 可用 `qid` 跑冒烟。训练产物留在 `artifacts`，DBE-KT22 和派生数据保存在受控数据目录。

从项目根目录复制 `.env.example` 为 `.env`，设置 `QUERYSTEP_DB_PASSWORD`，运行 `docker compose up --build`，然后打开本机的 8080 端口。Compose 使用 PostgreSQL 和原创题库，默认规则选题。可选 LLM 配置与本地 API 相同。API 镜像仅打包原创题库；有授权的 EpiKT 推理部署需要单独准备 CUDA 运行环境、研究源码、兼容权重及题库。
