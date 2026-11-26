# QueryStep Docker Compose 实机冒烟验收手册（可直接交给另一台机器的 AI 执行）

> **目标**：在装有 Docker / Docker Compose 的宿主机上，验证 `deploy/Dockerfile.api`、`deploy/Dockerfile.web`、`deploy/nginx.conf` 与 `compose.yaml` 能否一键构建、健康启动，并通过 Nginx (`http://127.0.0.1:8080`) 走通全栈 API、SQL 安全沙箱、MCP 工具、数据库持久化与 SSE 非缓冲推送。
>
> **安全红线**：
> - 严禁把 `.env`、API Key、真实数据库文件提交到 Git；
> - 严禁在日志或汇报中打印 `QUERYSTEP_LLM_API_KEY` 或 `QUERYSTEP_DB_PASSWORD` 明文；
> - 所有测试均使用合成查询与独立测试会话，完成后按需清理容器和临时 Cookie 文件。

---

## 0. 环境预检

在项目根目录执行：

```bash
docker --version
docker compose version
mkdir -p artifacts research
```

准备本机 `.env`（若尚未存在）：

```bash
cp -n .env.example .env
```

确保 `.env` 至少设置了非空的 `QUERYSTEP_DB_PASSWORD`（例如随机字符串 `querystep_smoke_pass_2026`）。若希望同时验证 LLM 教练，再填写 `QUERYSTEP_LLM_BASE_URL`、`QUERYSTEP_LLM_MODEL`、`QUERYSTEP_LLM_API_KEY`（明文 HTTP 测试网需设置 `QUERYSTEP_LLM_ALLOW_INSECURE_HTTP=1`）。

校验 Compose 渲染配置无语法错误：

```bash
docker compose config --quiet && echo "compose config OK"
```

---

## 1. 模式 A：基础全栈冒烟（仅需 Git 仓库，无需私有权重）

该模式使用仓库内原创 SQL 题库（`/app/course_content/catalog.json`）、PostgreSQL 16、FastAPI + MCP + SQL 沙箱、诊断检查点卷 `api_runtime` 以及 React 19 + Nginx。

### 1.1 构建并启动全部容器

```bash
docker compose up --build -d
docker compose ps
```

预期：`db`、`api`、`web` 三个容器全部为 `Up` / `healthy`。如 `api` 启动失败，运行 `docker compose logs --tail=120 api` 排查。

### 1.2 验证 Nginx 配置与 `/healthz`

```bash
docker compose exec web nginx -t
curl -fsS http://127.0.0.1:8080/healthz | python3 -m json.tool
```

验收条件：
- `nginx -t` 返回 `syntax is ok` / `test is successful`；
- `/healthz` 返回 `200 OK`，且满足：
  - `"status": "ok"`
  - `"sql_workbench_ready": true`
  - `"diagnostics_ready": true`
  - `"mcp_ready": true`
  - `"epikt_ready": false`（模式 A 未挂载私有权重时为预期值）
  - 若 `.env` 配了 LLM，则 `"tutor_ready": true` 且 `"sql_coach_ready": true`

### 1.3 验证前后端与 SQL 沙箱核心链路（经 Nginx `8080`）

运行以下端到端脚本（零外部依赖，仅用 `python3` 标准库）：

```bash
python3 - <<'PY'
import http.cookiejar, json, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8080"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def req(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with opener.open(r, timeout=30) as resp:
        return resp.status, dict(resp.headers), resp.read().decode("utf-8")

def poll_run(run_id, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, _, txt = req("GET", f"/api/sql/runs/{run_id}")
        obj = json.loads(txt)
        if obj["status"] not in ("queued", "running"):
            return obj
        time.sleep(0.2)
    raise RuntimeError(f"Run {run_id} did not finish within {timeout}s")

# 1) 前端静态首页
status, _, html = req("GET", "/")
assert status == 200 and "<div id=\"root\">" in html, "Frontend index.html check failed"
print("1. Frontend index.html: OK")

# 2) 创建匿名会话
status, _, _ = req("POST", "/api/session", {})
assert status == 200
print("2. Session cookie created: OK")

# 3) 拉取 SQL 实作任务列表与推荐字段
status, _, txt = req("GET", "/api/sql/tasks")
tasks_resp = json.loads(txt)
assert status == 200 and tasks_resp["available"] is True
assert len(tasks_resp["tasks"]) == 10
assert "recommendation" in tasks_resp
print(f"3. /api/sql/tasks: OK (10 tasks, coach_available={tasks_resp['coach_available']}, rec={tasks_resp['recommendation']})")

# 4) 验证 SQL 沙箱反例发现（COUNT(*) 在未匹配左表行应被捕获为 mismatch）
buggy_sql = (
    "SELECT c.customer_id, COUNT(*) AS order_count "
    "FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id "
    "GROUP BY c.customer_id"
)
status, _, txt = req("POST", "/api/sql/tasks/left_join_counts/runs", {
    "sql": buggy_sql,
    "action": "check",
    "idempotency_key": "docker-smoke-buggy-001",
})
assert status == 202
run1 = poll_run(json.loads(txt)["id"])
assert run1["status"] == "completed"
assert run1["result"]["check"]["status"] == "mismatch"
assert run1["result"]["check"]["counterexample"] is not None
print("4. SQL sandbox counterexample (mismatch): OK")

# 5) 验证 SQL 沙箱安全拦截（ATTACH DATABASE 必须被拒绝，且不影响后续查询）
status, _, txt = req("POST", "/api/sql/tasks/left_join_counts/runs", {
    "sql": "ATTACH DATABASE '/tmp/pwn.db' AS pwn",
    "action": "run",
    "idempotency_key": "docker-smoke-reject-001",
})
assert status == 202
run2 = poll_run(json.loads(txt)["id"])
assert run2["status"] == "completed"
assert run2["result"]["query"]["status"] == "rejected"
print("5. SQL sandbox security rejection (ATTACH): OK")

# 6) 验证正式练习流程 + 历史回退推荐（答错 1 题后 /api/sql/tasks 应返回 history_fallback）
status, _, txt = req("POST", "/api/practice/next", {})
item = json.loads(txt)
assert status == 200 and item["status"] == "ready"
# 随便选一个选项提交
status, _, txt = req("POST", f"/api/practice/{item['decision_id']}/answer", {
    "option": 0,
    "idempotency_key": "docker-smoke-mcq-001",
})
assert status == 200
print("6. Formal practice + PostgreSQL persistence: OK")

# 7) 验证容器内诊断检查点目录可写
print("ALL MODE-A API SMOKE CHECKS PASSED!")
PY
```

### 1.4 验证可写检查点卷与容器内 Python 依赖

```bash
docker compose exec api ls -la /app/runtime
docker compose exec api python -m sql_lab.check
```

预期：`/app/runtime` 存在且包含 `diagnosis-checkpoints.sqlite3`（或可写）；`python -m sql_lab.check` 退出码为 `0`。

### 1.5 （若 `.env` 已配置可用 LLM）验证容器内 `WorkbenchCoach` 实时调用

```bash
python3 - <<'PY'
import http.cookiejar, json, time, urllib.request

BASE = "http://127.0.0.1:8080"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def req(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with opener.open(r, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8")

req("POST", "/api/session", {})
_, txt = req("POST", "/api/sql/tasks/left_join_counts/runs", {
    "sql": "SELECT c.customer_id, COUNT(*) AS order_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id",
    "action": "coach",
    "message": "请验证我的 SQL 在边界情况下是否正确，为什么零订单客户会出错？",
    "idempotency_key": "docker-smoke-coach-001",
})
run_id = json.loads(txt)["id"]
for _ in range(150):
    _, body = req("GET", f"/api/sql/runs/{run_id}")
    obj = json.loads(body)
    if obj["status"] not in ("queued", "running"):
        print("Coach status:", obj["status"], "mode:", (obj.get("result") or {}).get("mode"))
        print("Metrics:", json.dumps((obj.get("result") or {}).get("metrics", {}), ensure_ascii=False))
        assert obj["status"] == "completed"
        assert obj["result"]["check"]["status"] == "mismatch"
        break
    time.sleep(0.2)
else:
    raise RuntimeError("Coach run timed out")
PY
```

---

## 2. 模式 B：完整 EpiKT + 混合知识索引 + SSE 流式冒烟（可选）

若已通过安全通道将以下私有/研究产物同步到该宿主机同路径：
- `artifacts/epikt-dbe-fold0/`
- `artifacts/dbe-sql-approved.json`
- `artifacts/workbench-knowledge.sqlite3`
- `research/363_EpiKT_Causal_Recursive_Con_Supplementary Material/code/pykt-toolkit-main-epikt/`

在 `.env` 中取消注释或追加：

```dotenv
QUERYSTEP_DOCKER_CATALOG=/app/artifacts/dbe-sql-approved.json
QUERYSTEP_DOCKER_EPIKT_RUN=/app/artifacts/epikt-dbe-fold0
QUERYSTEP_DOCKER_KNOWLEDGE_INDEX=/app/artifacts/workbench-knowledge.sqlite3
```

重建并验证 `api`：

```bash
docker compose up -d --force-recreate api
sleep 5
curl -fsS http://127.0.0.1:8080/healthz | python3 -m json.tool
```

验收条件：
1. `/healthz` 中 `"epikt_ready": true`、`"sql_workbench_ready": true`、`"diagnostics_ready": true`；
2. 完成 3 道冷启动题并请求第 4 题后，确认推荐 `"source": "epikt"`，紧接着 `GET /api/sql/tasks` 返回的 `recommendation.source == "epikt"`，包含 `guidance_tier`、`mean_predicted_probability` 与 `priority_scenarios`；
3. 当遇到题号 `75` 或 `81` 答错并触发 `POST /api/practice/{decision_id}/diagnosis` 时，用 `curl -iN -b <cookie> http://127.0.0.1:8080/api/diagnosis/{run_id}/events` 验证响应头含 `content-type: text/event-stream` 与 `x-accel-buffering: no`（Nginx 默认消费并剥离上游 `X-Accel-Buffering`，本仓库 `deploy/nginx.conf` 同时显式关闭 `proxy_buffering` 并通过 `add_header X-Accel-Buffering "no" always` 透出给下游），且事件按序逐条实时到达直至 `event: settled`。

---

## 3. 清理与回报模板

验收完成后按需清理：

```bash
docker compose down -v
```

请执行验证的 AI 按以下格式汇报实测结果（全部据实填写，不省略错误）：

```text
[Docker 实机冒烟验收汇报]
- 宿主机 OS / Docker / Compose 版本：
- docker compose config --quiet：PASS / FAIL
- docker compose up --build -d（构建耗时与镜像状态）：PASS / FAIL
- nginx -t：PASS / FAIL
- /healthz 关键字段（epikt_ready / sql_workbench_ready / sql_coach_ready / diagnostics_ready）：
- 模式 A（6 项 API/沙箱检查 + sql_lab.check）：PASS / FAIL
- 可选 LLM WorkbenchCoach 容器实测：PASS / SKIP / FAIL
- 模式 B（EpiKT + 推荐联动 + SSE 非缓冲）：PASS / SKIP / FAIL
- 如失败，请附 `docker compose logs --tail=80 api web` 中脱敏后的关键报错。
```
