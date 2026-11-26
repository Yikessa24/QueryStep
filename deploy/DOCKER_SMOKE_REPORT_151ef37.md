# Docker 实机冒烟验收汇报

验收日期为 2026-11-26（UTC+8），被测提交为 `151ef37cdc28687c01c15e958a90290b9bc3fa66`。验收依据为 [Docker Compose 实机冒烟验收手册](DOCKER_SMOKE_TEST.md)。

- 宿主机 OS / Docker / Compose 版本：Windows 11 家庭版 64 位（Build 26200）/ Docker 29.5.2（Linux 容器，amd64）/ Compose v5.1.4。
- `docker compose config --quiet`：**PASS**，退出码 `0`。
- `docker compose up --build -d`（构建耗时与镜像状态）：**PASS**，拉取、构建和启动共耗时 `00:03:27.920`。API 和 Web 镜像构建成功，`postgres:16` 拉取成功。DB 和 API 为 `healthy`，Web 为 `Up`，监听 `127.0.0.1:8080`。
- `nginx -t`：**PASS**，输出包含 `syntax is ok` 和 `test is successful`，退出码 `0`。
- `/healthz` 关键字段：HTTP `200`，`status=ok`，`epikt_ready=false`，`sql_workbench_ready=true`，`sql_coach_ready=false`，`diagnostics_ready=true`，`mcp_ready=true`，`tutor_status=llm_unconfigured`。
- 模式 A（6 项 API/沙箱检查 + `sql_lab.check`）：**PASS**。文档脚本和 `sql_lab.check` 均退出 `0`。`/app/runtime` 中存在 `diagnosis-checkpoints.sqlite3`。第 1.3 节第 6 项另用独立会话提交错误答案，随后读取到 `recommendation.source=history_fallback`。
- 可选 LLM WorkbenchCoach 容器实测：**SKIP**，`.env` 中的 LLM 地址、模型和 API Key 均为空。
- 模式 B（EpiKT + 推荐联动 + SSE 非缓冲）：**SKIP**，验收所需的权重、批准题库、知识索引和研究代码均未就位。
- 失败日志：无。

首次验收时启动了 Docker Desktop，并从模板生成本地 `.env`，设置随机测试数据库密码。容器和测试卷保留供复查。

<details>
<summary>原始验证输出</summary>

````text
=== 复核与环境 ===
Commit:
151ef37cdc28687c01c15e958a90290b9bc3fa66
151ef37cdc28687c01c15e958a90290b9bc3fa66
## main...origin/main
git diff HEAD exit=0
Windows:
Microsoft Windows 11 家庭版 中文版 10.0.26200 build 26200 64 位
Docker version 29.5.2, build 79eb04c
Docker Compose version v5.1.4
Server=29.5.2 OSTYPE=linux Arch=x86_64 OS=Docker Desktop
docker compose config --quiet exit=0
QUERYSTEP_LLM_BASE_URL configured in .env: False
QUERYSTEP_LLM_MODEL configured in .env: False
QUERYSTEP_LLM_API_KEY configured in .env: False
artifacts/epikt-dbe-fold0: False
artifacts/dbe-sql-approved.json: False
artifacts/workbench-knowledge.sqlite3: False
research/363_EpiKT_Causal_Recursive_Con_Supplementary Material/code/pykt-toolkit-main-epikt: False
NAME              IMAGE           COMMAND                  SERVICE   CREATED              STATUS                        PORTS
querystep-api-1   querystep-api   "python -m uvicorn a…"   api       About a minute ago   Up About a minute (healthy)   8000/tcp
querystep-db-1    postgres:16     "docker-entrypoint.s…"   db        About a minute ago   Up About a minute (healthy)   5432/tcp
querystep-web-1   querystep-web   "/docker-entrypoint.…"   web       About a minute ago   Up About a minute             127.0.0.1:8080->80/tcp

=== 1.1 首次构建完成与容器状态 ===
#32 exporting layers 35.0s done
#32 exporting manifest sha256:d60e00f955264a20af1166e77895322977988291ccbac337b5a9bdca4c97ed48 0.0s done
#32 exporting config sha256:898d83a341297a1c9a6e037a6e48fd6c2c18688190e13b619ad50bbe83419293 0.0s done
#32 exporting attestation manifest sha256:fc1e423ef442096a973aea443724315409daf73c1ead7313ef6527c73c3b3669 0.0s done
#32 exporting manifest list sha256:901d22172c5816c0bf239798b79e9dc5c76f9043e79f38f5f8f94c8ebc279cb0
#32 exporting manifest list sha256:901d22172c5816c0bf239798b79e9dc5c76f9043e79f38f5f8f94c8ebc279cb0 0.0s done
#32 naming to docker.io/library/querystep-api:latest done
#32 unpacking to docker.io/library/querystep-api:latest
#32 unpacking to docker.io/library/querystep-api:latest 8.5s done
#32 DONE 43.7s

#33 [api] resolving provenance for metadata file
#33 DONE 0.0s
 Image querystep-api Built
 Image querystep-web Built
 Network querystep_default Creating
 Network querystep_default Created
 Volume querystep_pgdata Creating
 Volume querystep_pgdata Created
 Volume querystep_api_runtime Creating
 Volume querystep_api_runtime Created
 Container querystep-db-1 Creating
 Container querystep-db-1 Created
 Container querystep-api-1 Creating
 Container querystep-api-1 Created
 Container querystep-web-1 Creating
 Container querystep-web-1 Created
 Container querystep-db-1 Starting
 Container querystep-db-1 Started
 Container querystep-db-1 Waiting
 Container querystep-db-1 Healthy
 Container querystep-api-1 Starting
 Container querystep-api-1 Started
 Container querystep-api-1 Waiting
 Container querystep-api-1 Healthy
 Container querystep-web-1 Starting
 Container querystep-web-1 Started
docker compose up exit=0 elapsed=00:03:27.920
NAME              IMAGE           COMMAND                  SERVICE   CREATED          STATUS                    PORTS
querystep-api-1   querystep-api   "python -m uvicorn a…"   api       12 seconds ago   Up 6 seconds (healthy)    8000/tcp
querystep-db-1    postgres:16     "docker-entrypoint.s…"   db        15 seconds ago   Up 12 seconds (healthy)   5432/tcp
querystep-web-1   querystep-web   "/docker-entrypoint.…"   web       12 seconds ago   Up Less than a second     127.0.0.1:8080->80/tcp
CONTAINER           REPOSITORY          TAG                 PLATFORM            IMAGE ID            SIZE                CREATED
querystep-api-1     querystep-api       latest              linux/amd64         901d22172c58        498MB               59 seconds ago
querystep-db-1      postgres            16                  linux/amd64         07abc3f43c93        166MB               2 days ago
querystep-web-1     querystep-web       latest              linux/amd64         f822d3cc6970        28.9MB              2 minutes ago

=== 1.2–1.4 验证原始输出 ===
=== 1.2 docker compose exec web nginx -t ===
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
nginx exit=0
=== 1.2 GET /healthz ===
HTTP 200
{
    "status": "ok",
    "service": "querystep",
    "catalog_version": "original-sql-v1",
    "epikt_ready": false,
    "tutor_ready": false,
    "coach_ready": false,
    "sql_workbench_ready": true,
    "sql_workbench_reason": null,
    "sql_coach_ready": false,
    "sql_coach_reason": "model_unavailable",
    "tutor_status": "llm_unconfigured",
    "diagnostics_ready": true,
    "mcp_ready": true,
    "diagnostics_reason": null
}
curl exit=0; json.tool exit=0
Mode A health fields matched: True
=== 1.3 Python end-to-end script from deploy/DOCKER_SMOKE_TEST.md ===
1. Frontend index.html: OK
2. Session cookie created: OK
3. /api/sql/tasks: OK (10 tasks, coach_available=False, rec={'available': False, 'source': 'none', 'reason': 'no_epikt_or_history'})
4. SQL sandbox counterexample (mismatch): OK
5. SQL sandbox security rejection (ATTACH): OK
6. Formal practice + PostgreSQL persistence: OK
ALL MODE-A API SMOKE CHECKS PASSED!
Mode A script exit=0
=== 1.4 docker compose exec api ls -la /app/runtime ===
total 76
drwxr-xr-x 2 root root  4096 Nov 26 06:51 .
drwxr-xr-x 1 root root  4096 Nov 26 06:51 ..
-rw------- 1 root root  4096 Nov 26 06:51 diagnosis-checkpoints.sqlite3
-rw------- 1 root root 32768 Nov 26 06:51 diagnosis-checkpoints.sqlite3-shm
-rw------- 1 root root 24752 Nov 26 06:51 diagnosis-checkpoints.sqlite3-wal
ls exit=0
=== 1.4 docker compose exec api python -m sql_lab.check ===
{
  "fixture_id": "grouping_having@1",
  "course_sources": [
    "aggregate-having",
    "aggregate-group-by"
  ],
  "group_counts": [
    [
      "A",
      4
    ],
    [
      "B",
      2
    ],
    [
      "C",
      2
    ],
    [
      "D",
      1
    ]
  ],
  "having_gt": [
    [
      "A",
      4
    ],
    [
      "B",
      2
    ],
    [
      "C",
      2
    ]
  ],
  "having_gte": [
    [
      "A",
      4
    ],
    [
      "B",
      2
    ],
    [
      "C",
      2
    ],
    [
      "D",
      1
    ]
  ],
  "comparison": {
    "before_id": "53b6dcdf181d4ead87f9dd107389d3d6",
    "after_id": "1b25690592914830b6dcfdf1ec68bd55",
    "comparison_id": "bcdb86ebb41a4fc2ba4e875dd4d1afc5",
    "fixture_id": "grouping_having@1",
    "before_row_count": 4,
    "after_row_count": 3,
    "removed_keys": [
      "D"
    ],
    "added_keys": [],
    "changed_keys": []
  }
}
sql_lab.check exit=0

=== 1.3 第 6 项补充检查 ===
POST /api/practice/{decision_id}/answer: 200 correct: false
GET /api/sql/tasks: 200
{
  "available": true,
  "source": "history_fallback",
  "task_id": "order_top",
  "task_title": "稳定选出评分前三产品",
  "topic": "select",
  "guidance_tier": "foundation",
  "scaffolding_level": "step_by_step",
  "priority_scenarios": [
    "sample",
    "boundary",
    "empty",
    "duplicates"
  ],
  "mean_predicted_probability": null,
  "candidate_count": 0,
  "model_version": null,
  "snapshot_history_version": null,
  "current_history_version": 1,
  "reason": "recent_incorrect_topic_attempt"
}
history_fallback check exit=0
````

</details>
