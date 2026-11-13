#!/bin/bash
set -eo pipefail

cd "$(dirname "$0")"
project_dir="$PWD"
run_dir="$project_dir/artifacts/epikt-dbe-fold0"
catalog="$project_dir/artifacts/dbe-sql-approved.json"
backend_port="${QUERYSTEP_BACKEND_PORT:-8000}"
frontend_port="${QUERYSTEP_FRONTEND_PORT:-5173}"
backend_url="http://127.0.0.1:$backend_port"
frontend_url="http://127.0.0.1:$frontend_port"
vite_cli="$project_dir/web/node_modules/vite/bin/vite.js"
diagnostics_enabled="${QUERYSTEP_DIAGNOSTICS_ENABLED:-0}"

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

[[ -r .env || "$diagnostics_enabled" == 1 ]] || fail '缺少项目根目录的 .env，请恢复本机 Gemini 配置。'
[[ -f "$vite_cli" ]] || fail '缺少前端依赖，请在项目根目录运行 npm --prefix web ci。'
command -v node >/dev/null || fail '找不到 Node.js，请安装或恢复本机 Node.js 环境。'
[[ "$backend_port" != "$frontend_port" ]] || fail '前端和后端需要使用不同的端口。'

for port in "$backend_port" "$frontend_port"; do
    if lsof -nP -t -iTCP:"$port" -sTCP:LISTEN >/dev/null; then
        fail "端口 $port 已占用。可用 lsof -nP -iTCP:$port -sTCP:LISTEN 查看监听进程。"
    fi
done

conda_base=/opt/miniconda3
if command -v conda >/dev/null; then
    conda_base="$(conda info --base)"
fi
conda_profile="$conda_base/etc/profile.d/conda.sh"
[[ -r "$conda_profile" ]] || fail '找不到 Conda 初始化脚本，请检查本机 Conda 安装。'
source "$conda_profile"
conda activate querystep || fail '无法激活 Conda 环境 querystep，请按操作手册恢复环境。'

python -m course_content.check_catalog --run "$run_dir" --catalog "$catalog"

backend_python="${QUERYSTEP_PYTHON:-python}"

backend_pid=
frontend_pid=
cleanup() {
    local pid
    for pid in "$frontend_pid" "$backend_pid"; do
        if [[ -n "$pid" ]]; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_for_http() {
    local pid="$1" url="$2" deadline=$((SECONDS + 30))
    while (( SECONDS < deadline )) && kill -0 "$pid" 2>/dev/null; do
        if curl --noproxy '*' -fsS --max-time 1 "$url" 2>/dev/null; then
            return 0
        fi
        sleep 0.25
    done
    return 1
}

(
    if [[ -r .env ]]; then
        set -a
        source ./.env
        set +a
    fi
    export QUERYSTEP_EPIKT_RUN="$run_dir"
    export QUERYSTEP_CATALOG="$catalog"
    export QUERYSTEP_LLM_ALLOW_MAPPED_ITEMS=1
    export QUERYSTEP_DIAGNOSTICS_ENABLED="$diagnostics_enabled"
    exec "$backend_python" -m uvicorn api.main:app --host 127.0.0.1 --port "$backend_port"
) &
backend_pid=$!

health="$(wait_for_http "$backend_pid" "$backend_url/healthz")" ||
    fail '后端未能启动，请查看上方日志。'
if ! python -c 'import json, sys
status = json.load(sys.stdin)
sys.exit(status.get("epikt_ready") is not True)' <<< "$health"; then
    printf '%s\n' "$health" >&2
    fail 'EpiKT 未就绪，请核对权重和题库。'
fi
tutor_message='Gemini 辅导已配置。'
if ! python -c 'import json, sys
sys.exit(json.load(sys.stdin).get("tutor_ready") is not True)' <<< "$health"; then
    [[ "$diagnostics_enabled" == 1 ]] || fail 'Gemini 配置未就绪，请核对 .env。'
    tutor_message='Gemini 配置未就绪，普通辅导使用审核提示。'
fi
if [[ "$diagnostics_enabled" == 1 ]] && ! python -c 'import json, sys
sys.exit(json.load(sys.stdin).get("diagnostics_ready") is not True)' <<< "$health"; then
    printf '%s\n' "$health" >&2
    fail '诊断模块未就绪，请检查 diagnostics 依赖、数据库和 MCP 启动日志。'
fi

(
    cd "$project_dir/web"
    export QUERYSTEP_API_PROXY="$backend_url"
    exec node "$vite_cli" --host 127.0.0.1 --port "$frontend_port" --strictPort
) &
frontend_pid=$!

wait_for_http "$frontend_pid" "$frontend_url/healthz" >/dev/null ||
    fail '前端未能连上后端，请查看上方日志。'

printf '\nQueryStep 已启动，请打开 %s/\nEpiKT 已加载。%s\n按 Ctrl+C 停止前后端。\n\n' "$frontend_url" "$tutor_message"
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
    sleep 1
done
fail '有一个服务已退出，正在关闭另一个服务。请查看上方日志。'
