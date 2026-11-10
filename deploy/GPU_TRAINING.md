# 在 GPU 服务器上训练 QueryStep 的 EpiKT

首轮采用已经准备好的 **DBE-KT22 SQL Core**，固定第 0 折和随机种子 3407。当前数据包含 24 道题、15 个 KC、540 名学习者、11,283 条清洗后的作答。第 0 折用 345 人训练、87 人验证，另有 108 名学习者留出测试。首轮的任务是拿到一份同域、可校验的权重，并判断它能否进入在线选题。

## AutoDL 快速开跑

1. 上传第 1 节的训练包，在 AutoDL 解压。包里已经包含代码、随附 pyKT 和预处理后的 SQL Core 数据。
2. 激活已经配好 CUDA 版 PyTorch 的 Python 环境，在解压后的项目根目录安装项目依赖并检查 GPU。
3. 用默认参数启动训练。训练完成后，checkpoint 在 `artifacts/epikt-dbe-fold0/qid_alibi_model.ckpt`。

```bash
python -m pip install -e '.[kt]'
python -c 'import torch; print(torch.ones(1, device="cuda"))'
python -m kt.train --run artifacts/epikt-dbe-fold0
```

如果你的目标是把这次权重用于学生端选题，训练完成后在同一个环境补跑以下两条，再带回整个 run 目录。

```bash
python -m evals.calibrate_kt --run artifacts/epikt-dbe-fold0
python -m evals.evaluate_kt --run artifacts/epikt-dbe-fold0
```

CUDA 检查报错时再查第 2 节。单轮试跑、保存日志和环境记录可按需使用。

### 从 GitHub 克隆

私有 GitHub 仓库包含应用和训练入口。下载仓库后，另通过私有文件传输上传 `querystep-autodl-inputs.tar.gz`，解压到克隆的 QueryStep 根目录。该包补齐随附 pyKT 和固定的 SQL Core 数据。

```bash
cd QueryStep
tar -xzf /path/to/querystep-autodl-inputs.tar.gz
```

在该目录继续安装依赖和训练。AutoDL 需先具备访问私有仓库的 GitHub 凭据。

## 1. 从 Mac 准备并传输文件

默认传已预处理的数据，沿用现有切分、ID 映射和 `manifest.json`。在有权限处理 DBE-KT22 和匿名研究源码的服务器上建私有目录。

| 内容 | 需要传的文件 |
|---|---|
| 训练环境与入口 | `pyproject.toml`、`deploy/environment.yml`、`kt/`、`evals/`、`data_pipeline/` |
| 随附 pyKT | 研究目录下 `code/pykt-toolkit-main-epikt/pykt/` 整个包，保留目录层级 |
| 题目窗口评估 | 研究目录下 `code/analysis/analyze_epikt_branches.py` |
| 已处理数据 | `data/processed/dbe_kt22_sql_core/` 下的 `manifest.json`、`data_config.json`、`keyid2idx.json`、`data.txt`、`train_valid_question_window_sequences.csv`、`train_valid.csv`、`test_question_window_sequences.csv` |

以下命令在 **Mac** 执行。先把 `YOUR_USER@YOUR_GPU_HOST` 换成 SSH 登录地址。

```bash
project='/Users/felixyan/Desktop/实习/projects/QueryStep'
gpu_host='YOUR_USER@YOUR_GPU_HOST'
stage=$(mktemp -d "${TMPDIR:-/tmp}/querystep-transfer.XXXXXX")
research='research/363_EpiKT_Causal_Recursive_Con_Supplementary Material/code'
data='data/processed/dbe_kt22_sql_core'

COPYFILE_DISABLE=1 tar --exclude='__pycache__' -czf "$stage/querystep-training.tar.gz" \
  -C "$project" \
  pyproject.toml deploy/environment.yml kt evals data_pipeline \
  "$research/pykt-toolkit-main-epikt/pykt" \
  "$research/analysis/analyze_epikt_branches.py" \
  "$data/manifest.json" "$data/data_config.json" "$data/keyid2idx.json" \
  "$data/data.txt" "$data/train_valid.csv" \
  "$data/train_valid_question_window_sequences.csv" \
  "$data/test_question_window_sequences.csv"

ssh "$gpu_host" 'umask 077; mkdir "$HOME/querystep-gpu"'
scp "$stage/querystep-training.tar.gz" "$gpu_host:querystep-gpu/"
ssh "$gpu_host"
```

`mkdir` 提示目录已存在时，先检查它属于哪次实验，再选择新的目录名。首轮压缩包只包含训练所需文件。保留本地原始 ZIP、论文、旧 `.pkl` 缓存和应用凭据。

**如果需要在服务器重新预处理**，用 `data/DBE-KT22/2_DBE_KT22_datafiles_100102_csv.zip` 和 `configs/dbe_sql_core.json` 替换上表的已处理数据。配置环境后在项目根目录运行：

```bash
python -m data_pipeline.preprocess --scope sql-core --maxlen 200
```

这条路径会产生新的数据清单。训练、校准和测试都指向这次生成的同一目录。把该次数据清单保存在实验记录里。重新预处理时也保留对应映射；服务器生成的清单可能因路径等元数据与 Mac 上的清单不同。

## 2. 配置 Linux Conda 与 CUDA

以下命令在 **GPU 服务器**执行。如果是 Slurm 等集群，先申请一张 GPU，然后在分配到的计算节点执行 CUDA 检查和训练。沿用调度器设置的 `CUDA_VISIBLE_DEVICES`。

```bash
umask 077
cd ~/querystep-gpu
tar -xzf querystep-training.tar.gz
uname -m
nvidia-smi
conda --version
```

服务器未提供 Conda 时，先按官方说明安装与服务器架构匹配的 Linux Miniconda，或加载集群提供的 Conda 模块。环境文件固定 Python 3.11。 [Miniconda 安装](https://www.anaconda.com/docs/getting-started/miniconda/install) · [Conda 环境管理](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html)

下面给出 **Linux x86_64** 的固定版本示例。对于 A100、H100、RTX 4090 等，若 `nvidia-smi` 显示的 CUDA 支持版本至少为 12.6，可先用 PyTorch 2.7.1 的 `cu126`。对于 RTX 50 系列等 Blackwell GPU，选支持该 GPU 架构的构建，例如同版 `cu128`，并使用支持 CUDA 12.8 和该卡的驱动。其他机型按实际 GPU、驱动和官方 wheel 选择。这里使用预编译 wheel，项目的这一条训练路径无需额外安装 `nvcc`。 [PyTorch 版本与安装命令](https://pytorch.org/get-started/previous-versions/#v271) · [Blackwell 支持说明](https://pytorch.org/blog/pytorch-2-7/) · [NVIDIA CUDA 与驱动兼容性](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)

```bash
conda create --override-channels -c conda-forge -n querystep python=3.11 pip
conda activate querystep

# 本例为 cu126。上述 Blackwell 示例将 cu126 换成 cu128。
python -m pip install 'torch==2.7.1' \
  --index-url https://download.pytorch.org/whl/cu126
python -m pip install -e '.[kt]'
python -m pip check

python - <<'PY'
import torch
from kt.pykt_source import bundled_pykt

print("PyTorch:", torch.__version__, "wheel CUDA:", torch.version.cuda)
assert torch.version.cuda is not None, "当前安装的是 CPU wheel"
assert torch.cuda.is_available(), "当前进程看不到 NVIDIA GPU"
print("GPU:", torch.cuda.get_device_name(0))
x = torch.ones((32, 32), device="cuda")
assert (x @ x)[0, 0].item() == 32
print("Bundled pyKT:", bundled_pykt().__file__)
PY
```

先验证实际 CUDA 运算。若驱动可见但运算报错，再检查 GPU 架构与 wheel 是否匹配。在个人多卡服务器上如需指定单卡，可在确认 GPU 编号后设置 `CUDA_VISIBLE_DEVICES`；程序内仍使用逻辑设备 `cuda:0`。当前代码按单卡训练。

## 3. 用随附 pyKT 训练

QueryStep 的 `kt.train` 先核对数据清单，再调用随附 pyKT 的 `init_dataset4train → init_model → train_model`。训练与验证使用同一份分折题目窗口文件，按学习者的 fold 取行。使用 Adam、学习率 `1e-3`、200 个展开交互位置的窗口、`n_scales=2`、`qid_alibi`。pyKT 在验证 AUC 超过已保存值至少约 0.001 时更新 checkpoint，连续 10 轮未更新则提前停止。 [训练入口](../kt/train.py)

建议在 `tmux` 会话或集群作业中运行。Bash 中启用 `pipefail`，确保 `tee` 后仍能看到训练失败状态。先跑 1 个 epoch，走真实 CUDA 和正式模型配置，检查加载、前向、反向和保存。联调目录单独留存。

```bash
set -euo pipefail
umask 077
DATA=data/processed/dbe_kt22_sql_core
mkdir -p artifacts

python -u -m kt.train --data "$DATA" --run artifacts/epikt-dbe-gpu-check \
  --fold 0 --seed 3407 --emb-type qid_alibi --epochs 1 --batch-size 16 \
  2>&1 | tee artifacts/epikt-dbe-gpu-check.log
```

确认最后出现 `Saved .../qid_alibi_model.ckpt` 后，用新目录启动正式训练。这里的 `--epochs 200` 是上限。

```bash
RUN=artifacts/epikt-dbe-fold0

python -u -m kt.train --data "$DATA" --run "$RUN" \
  --fold 0 --seed 3407 --emb-type qid_alibi --epochs 200 --batch-size 32 \
  2>&1 | tee "$RUN.train.log"
```

显存不足时，从 32 降到 16 或 8，并使用新的 `--run` 路径。当前 checkpoint 保存模型权重，训练入口没有恢复优化器和训练轮次的续训参数。日志中的 `best epoch` 和 `best auc` 对应已保存的 checkpoint，`training_metrics.json` 中的验证 AUC 和 ACC 也来自同一轮。

## 4. 用验证折做校准，再跑留出测试

下面两步与正式训练用同一个 `DATA`、`RUN`，并继续在 CUDA 环境运行。校准用第 0 折验证学习者，留出评估用独立的 108 名测试学习者。题目级预测用 pyKT 的题目窗口 `late_mean`。 [校准入口](../evals/calibrate_kt.py) · [留出评估入口](../evals/evaluate_kt.py)

```bash
python -u -m evals.calibrate_kt --data "$DATA" --run "$RUN" --batch-size 16 \
  2>&1 | tee "$RUN.calibration.log"
python -u -m evals.evaluate_kt --data "$DATA" --run "$RUN" --batch-size 16 \
  2>&1 | tee "$RUN.test.log"
python -m json.tool "$RUN/test_metrics.json"
```

先看 `question_auc`、`question_acc` 和 `covered_targets`，再看 `common_coverage` 中 EpiKT 与题目先验、近期 KC 正确率、BKT 的指标。正式 run 的在线准入要求在同一批训练支持、已有至少三次历史作答的留出目标题上，校准 Brier 不高于最强基线，且 ECE ≤ 0.08。若校准报斜率非正，或 `passes_scoring_gate` 为 `false`，保留结果供分析，学生端继续走规则。已有 run 若使用旧版评估报告，沿用原权重和数据重跑 `evals.evaluate_kt` 即可生成新报告。 [准入实现](../kt/release.py)

## 5. 带回整个正式 run 目录

| 文件 | 用途 |
|---|---|
| `qid_alibi_model.ckpt` | 最佳轮的 EpiKT 权重 |
| `config.json` | 模型结构、`emb_type`、数据配置、fold、seed、源码和数据清单指纹 |
| `keyid2idx.json` | DBE 原始题目 ID、KC ID 到模型索引的映射 |
| `question_kcs.json` | DBE 题目 ID 对应的有序 KC 列表 |
| `training_metrics.json` | 训练元数据以及配置、权重和映射指纹 |
| `calibration.json` | 验证折拟合的校准参数和有训练支持的题目列表 |
| `test_metrics.json` | 独立留出结果和在线准入状态 |

建议同时保存日志、GPU 环境和训练数据清单。先在 **GPU 服务器**整理正式 run。某一步失败时，保留实际生成的文件与对应日志。

```bash
cp "$DATA/manifest.json" "$RUN/dataset_manifest.json"
python -m pip list --format=freeze > "$RUN/python-packages.txt"
nvidia-smi > "$RUN/gpu-info.txt"
cp "$RUN.train.log" "$RUN.calibration.log" "$RUN.test.log" "$RUN/"
```

再在 **Mac** 下载。run 目录名以本次实际使用的为准。

```bash
project='/Users/felixyan/Desktop/实习/projects/QueryStep'
gpu_host='YOUR_USER@YOUR_GPU_HOST'
mkdir -p "$project/artifacts"
scp -r "$gpu_host:querystep-gpu/artifacts/epikt-dbe-fold0" "$project/artifacts/"
```

保留生成时的 JSON 文件内容。在线加载会校验文件指纹；即使 `config.json` 中记录的是服务器路径，当前加载器也无需打开该路径的训练数据。带回 Mac 的目录可以用于审查和归档。 [权重加载实现](../kt/scoring.py)

## 6. 接入学生端并验收

当前原版 `qid_alibi` 初始化依赖 CUDA，**正式权重先在 GPU 上加载**。可在同一服务器部署 QueryStep API，在 Mac 运行前端。训练包只够训练和评估，部署 API 时另外同步同版本的 `api/`、`tutor/`、`course_content/`，并安装 API 依赖。

题库使用获准展示且能对齐该 run 的版本。每题的 `source_question_id` 与有序 `source_kcs` 要和 run 的映射一致，并且题目要在 `calibration.json` 的训练支持名单内。项目自带的原创题库默认走规则。本机已准备好 `artifacts/dbe-sql-approved.json`。如果需要从获准使用的原始 ZIP 和对应预处理产物重新生成，可用 `python -m course_content.import_dbe --authorized --demo-context --output artifacts/dbe-sql-approved.json`。将获准题库同步到 GPU 服务器，并把下面的 `QUERYSTEP_CATALOG` 改成实际路径。

在 Mac 的项目根目录先运行 `python -m course_content.check_catalog --run artifacts/epikt-dbe-fold0 --catalog artifacts/dbe-sql-approved.json`。预检只核对文件、映射和准入报告。模型实际加载在 GPU 服务启动时验证。

```bash
# GPU 服务器，确认已同步 API 与获准题库
conda activate querystep
python -m pip install -e '.[kt,api]'
export QUERYSTEP_EPIKT_RUN="$PWD/artifacts/epikt-dbe-fold0"
export QUERYSTEP_CATALOG="$PWD/artifacts/dbe-sql-approved.json"
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```bash
ssh -N -L 8000:127.0.0.1:8000 YOUR_USER@YOUR_GPU_HOST
```

保持上述连接，在 Mac 的另一个终端启动前端。

```bash
curl -fsS http://127.0.0.1:8000/healthz
cd '/Users/felixyan/Desktop/实习/projects/QueryStep/web'
npm ci
npm run dev
```

验收时看 `epikt_ready`，再用新会话完成三道合格作答。前三题是规则冷启动。之后确认练习显示「EpiKT 推荐」，并用「查看选题记录」核对实际题与规则对照题。用同一历史和候选集保留一条**两种评分器选中不同题目**的记录。该记录证明 EpiKT 影响了教学动作，学习效果需要单独评估。 [推荐与回退实现](../api/recommend.py) · [API 健康检查](../api/main.py)
