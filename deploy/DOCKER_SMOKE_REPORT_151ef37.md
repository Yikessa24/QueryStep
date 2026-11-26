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

## 2026-11-26 补充验收（模式 B 与容器内 LLM）

本次验收在 `151ef37cdc28687c01c15e958a90290b9bc3fa66` 的部署和业务代码上进行。总体结果为 **FAIL**，阻塞项为 Nginx 对外响应缺少验收要求的 SSE 响应头，以及启用完整配置后 SQL 沙箱在 API 请求中报告内存限制错误。

| 验收项 | 结果 | 实测证据 |
| --- | --- | --- |
| 产物、配置与 API 重建 | **PASS** | EpiKT 运行目录、批准题库、知识索引、BGE 模型和 pykt 源码均就位。保留原数据库密码，更新四个容器产物路径及 LLM 配置。Compose 配置校验和 API 重建均退出 `0`。 |
| `/healthz` | **PASS** | HTTP `200`。七个标志 `epikt_ready`、`tutor_ready`、`coach_ready`、`sql_workbench_ready`、`sql_coach_ready`、`diagnostics_ready` 和 `mcp_ready` 均为 `true`。 |
| 模式 B EpiKT 推荐与工作台联动 | **PASS** | 冷启动题依次为 `57`、`62`、`63`，提交下标 `[1, 0, 0]`。第 4 题为 `75`，`source=epikt`。工作台返回 `source=epikt`、`guidance_tier=foundation`、`mean_predicted_probability=0.6033` 和四个 `priority_scenarios`。 |
| 模式 B 诊断 SSE | **FAIL** | 第 75 题提交下标 `0` 判错，诊断返回 HTTP `202`。经 Nginx 的 `curl -iN` 返回 HTTP `200` 和 `Content-Type: text/event-stream; charset=utf-8`。7 条事件在约 `0.550s` 内陆续到达，最后收到 `event: settled`。容器内直连 API 带 `X-Accel-Buffering: no`，Nginx 对外响应缺少该头。 |
| §1.5 `COUNT(*)` WorkbenchCoach | **FAIL** | 两次调用均发出 2 次模型调用，run 均为 `completed`，均返回 `check.status=error`、`mode=evidence_only`、`finish_reason=no_new_action`。同一 SQL 的独立 `action=check` 返回 `memory_limit_exceeded`。 |
| §1.5 概念提问与 Hybrid RAG | **PASS** | 概念请求为 `completed`、`mode=agent`。`search_course` 产生 `retrieval_version.mode=hybrid` 事件。 |
| 完整配置下的基础回归 | **FAIL** | `nginx -t`、前端、会话、10 项任务列表、正式答题、检查点卷和 `sql_lab.check` 通过。§1.3 脚本在第 4 项反例断言处退出。额外复测中，反例检查与 `ATTACH` 均由 API 返回 `memory_limit_exceeded`，未满足预期结果。同容器的独立 Python 进程运行反例检查返回 `mismatch`。 |

`docker compose logs --tail=80 api web` 中未匹配到错误日志行。沙箱错误来自上述 API 响应。

<details>
<summary>实测命令输出及事件摘要</summary>

### 压缩包解压与配置校验

````text
Archive extraction: 76 entries; 98,438,745 bytes uncompressed
artifacts/epikt-dbe-fold0: present (8 files)
artifacts/dbe-sql-approved.json: present (19,738 bytes)
artifacts/workbench-knowledge.sqlite3: present (270,336 bytes)
artifacts/bge-small-zh-v1.5: present (10 files)
research/363_EpiKT_Causal_Recursive_Con_Supplementary Material/code/pykt-toolkit-main-epikt/pykt: present (42 files)

Updated .env entries: 13; existing database password preserved.
docker compose config --quiet exit=0
## main...origin/main
```

### API 重建与就绪状态

````text
 Container querystep-db-1 Running
 Container querystep-api-1 Recreate
 Container querystep-api-1 Recreated
 Container querystep-db-1 Waiting
 Container querystep-db-1 Healthy
 Container querystep-api-1 Starting
 Container querystep-api-1 Started
docker compose up -d --force-recreate api exit=0 elapsed=00:00:02.025
NAME              IMAGE           COMMAND                  SERVICE   CREATED          STATUS                                     PORTS
querystep-api-1   querystep-api   "python -m uvicorn a…"   api       2 seconds ago    Up Less than a second (health: starting)   8000/tcp
querystep-db-1    postgres:16     "docker-entrypoint.s…"   db        18 minutes ago   Up 18 minutes (healthy)                    5432/tcp
querystep-web-1   querystep-web   "/docker-entrypoint.…"   web       18 minutes ago   Up 18 minutes                              127.0.0.1:8080->80/tcp

GET /healthz HTTP 200 after 0.09s
{
  "status": "ok",
  "service": "querystep",
  "catalog_version": "dbe-v1-c5271713de70-demo",
  "epikt_ready": true,
  "tutor_ready": true,
  "coach_ready": true,
  "sql_workbench_ready": true,
  "sql_workbench_reason": null,
  "sql_coach_ready": true,
  "sql_coach_reason": null,
  "tutor_status": "configured",
  "diagnostics_ready": true,
  "mcp_ready": true,
  "diagnostics_reason": null
}
All seven readiness flags are true: True
NAME              IMAGE           COMMAND                  SERVICE   CREATED          STATUS                    PORTS
querystep-api-1   querystep-api   "python -m uvicorn a…"   api       35 seconds ago   Up 33 seconds (healthy)   8000/tcp
querystep-db-1    postgres:16     "docker-entrypoint.s…"   db        19 minutes ago   Up 19 minutes (healthy)   5432/tcp
querystep-web-1   querystep-web   "/docker-entrypoint.…"   web       19 minutes ago   Up 19 minutes             127.0.0.1:8080->80/tcp
```

### 模式 B 推荐与诊断 SSE

````text
Cold start answer {"position":1,"item":57,"source":"rule","option":1,"correct":false}
Cold start answer {"position":2,"item":62,"source":"rule","option":0,"correct":false}
Cold start answer {"position":3,"item":63,"source":"rule","option":0,"correct":true}
Fourth practice item {"id":75,"source":"epikt","reason":"consolidate"}
Workbench recommendation {"available":true,"source":"epikt","task_id":"filter_paid","task_title":"筛选已付款订单","topic":"where","guidance_tier":"foundation","scaffolding_level":"step_by_step","priority_scenarios":["sample","boundary","empty","duplicates"],"mean_predicted_probability":0.6033,"candidate_count":2,"model_version":"c31ae1ebdda8","snapshot_history_version":3,"current_history_version":3,"reason":"lowest_calibrated_topic_probability"}
ASSERT {"name":"fourth item is EpiKT item 75","pass":true}
ASSERT {"name":"workbench EpiKT guidance fields","pass":true}
Fourth answer {"item":75,"option":0,"correct":false}
ASSERT {"name":"fourth answer is incorrect","pass":true}
Diagnosis accepted {"http":202,"status":"queued"}
curl -iN Nginx headers {"status":"HTTP/1.1 200 OK","content-type":"text/event-stream; charset=utf-8","x-accel-buffering":null}
SSE {"at_s":0.035,"seq":1,"type":"run_started","status":"running"}
SSE {"at_s":0.506,"seq":2,"type":"branch_started","status":"running"}
SSE {"at_s":0.506,"seq":3,"type":"branch_started","status":"running"}
SSE {"at_s":0.506,"seq":4,"type":"branch_finished","status":"needs_input"}
SSE {"at_s":0.52,"seq":5,"type":"branch_finished","status":"ok"}
SSE {"at_s":0.584,"seq":6,"type":"evidence_verified","mode":"clarify"}
SSE {"at_s":0.584,"seq":7,"type":"run_finished","status":"completed"}
SSE {"at_s":0.584,"line":"event: settled"}
SSE verdict {"curl_exit":0,"http_200":true,"content_type":true,"x_accel_buffering_no":false,"event_count":7,"sequence_complete":true,"settled":true,"event_arrival_span_s":0.55,"progressive_arrival":true}
Direct API response headers {"status":200,"content-type":"text/event-stream; charset=utf-8","x-accel-buffering":"no"}
Diagnosis final {"status":"completed","result_mode":"clarify"}
Case result {"case":"mode-b","pass":false}
```

### 基础回归与 SQL 沙箱复测

````text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
nginx -t exit=0
1. Frontend index.html: OK
2. Session cookie created: OK
3. /api/sql/tasks: OK (10 tasks, coach_available=True, rec={'available': False, 'source': 'none', 'reason': 'no_epikt_or_history'})
Traceback (most recent call last):
  File "<stdin>", line 56, in <module>
AssertionError
Mode A API script exit=1
total 64
drwxr-xr-x 2 root root  4096 Nov 26 07:10 .
drwxr-xr-x 1 root root  4096 Nov 26 07:10 ..
-rw------- 1 root root 20480 Nov 26 07:10 diagnosis-checkpoints.sqlite3
-rw------- 1 root root 32768 Nov 26 07:10 diagnosis-checkpoints.sqlite3-shm
-rw------- 1 root root     0 Nov 26 07:10 diagnosis-checkpoints.sqlite3-wal
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
    "before_id": "33e996cf645243fcb16e2ebffd1e202b",
    "after_id": "14bb782b06cc4c1ebb2ff83ab7ad3563",
    "comparison_id": "4d5cd90418b1467c94ac2da3a4746ad1",
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

check result {"submit_http": 202, "run_status": "completed", "status": "error", "message": "memory_limit_exceeded", "error": null, "has_counterexample": false, "query_result_error": "memory_limit_exceeded"}
run result {"submit_http": 202, "run_status": "completed", "status": "error", "message": null, "error": "memory_limit_exceeded", "has_counterexample": false, "query_result_error": null}
Practice result {"next_http": 200, "status": "ready", "answer_http": 200, "correct": true}
Direct check in separate API-container process {"exit": 0, "result": {"status": "mismatch", "has_counterexample": true, "error": null, "message": "发现反例：请对照输入表、重复次数、NULL 与要求的行顺序。"}}
```

### WorkbenchCoach 首次、复测与概念检索

````text
COUNT(*) WorkbenchCoach {"http_submit":202,"status":"completed","mode":"evidence_only","check_status":"error","elapsed_s":9.702,"metrics":{"finish_reason":"no_new_action","model_calls":2,"tool_calls":1,"provider_calls_this_attempt":2,"usage_this_attempt":{"prompt_tokens":2953,"completion_tokens":106,"total_tokens":3059}},"retrieval_version":[],"trace":[{"seq":1,"type":"plan","tool":null},{"seq":2,"type":"tool_completed","tool":"check_student_sql"},{"seq":3,"type":"observation","tool":null},{"seq":4,"type":"plan","tool":null}]}
Case result {"case":"coach","pass":false}

COUNT(*) WorkbenchCoach {"http_submit":202,"status":"completed","mode":"evidence_only","check_status":"error","elapsed_s":4.852,"metrics":{"finish_reason":"no_new_action","model_calls":2,"tool_calls":1,"provider_calls_this_attempt":2,"usage_this_attempt":{"prompt_tokens":2953,"completion_tokens":119,"total_tokens":3072}},"retrieval_version":[],"trace":[{"seq":1,"type":"plan","tool":null},{"seq":2,"type":"tool_completed","tool":"check_student_sql"},{"seq":3,"type":"observation","tool":null},{"seq":4,"type":"plan","tool":null}]}
Case result {"case":"coach","pass":false}

Concept WorkbenchCoach {"http_submit":202,"status":"completed","mode":"agent","check_status":null,"elapsed_s":8.731,"metrics":{"finish_reason":"answer","model_calls":2,"tool_calls":1,"provider_calls_this_attempt":2,"usage_this_attempt":{"prompt_tokens":3249,"completion_tokens":274,"total_tokens":3523}},"retrieval_version":[{"mode":"hybrid","corpus":"2a329b4f082cd0af1a6b3105fb85d9a0903e39a0860436c5e601346b362b66a0"}],"trace":[{"seq":1,"type":"plan","tool":null},{"seq":2,"type":"retrieval_version","tool":"search_course"},{"seq":3,"type":"tool_completed","tool":"search_course"},{"seq":4,"type":"observation","tool":null},{"seq":5,"type":"plan","tool":null},{"seq":6,"type":"observation","tool":null}]}
Case result {"case":"concept","pass":true}
```

### 脱敏日志检查

````text
docker compose logs --tail=80 api web exit=0; matching error lines=0
## main...origin/main
.env
artifacts/epikt-dbe-fold0/qid_alibi_model.ckpt
artifacts/dbe-sql-approved.json
artifacts/workbench-knowledge.sqlite3
artifacts/bge-small-zh-v1.5/model.safetensors
research
querystep_api_runtime
querystep_pgdata
```

</details>

## 2026-11-26 修复复测（afa17cc）

**总体结果为 PASS。** 以 `git pull --ff-only origin main` 快进到 `afa17cc4d89b20113b236f815dbcdbe12f5f9320`，使用本地完整配置和产物重新构建并启动。Compose 配置校验退出 `0`，`docker compose up --build -d` 耗时 `00:03:10.634`。DB 和 API 达到 `healthy`，Web 为 `Up`。

| 验收项 | 结果 | 实测证据 |
| --- | --- | --- |
| `/healthz` | **PASS** | HTTP `200`，`epikt_ready`、`tutor_ready`、`coach_ready`、`sql_workbench_ready`、`sql_coach_ready`、`diagnostics_ready` 和 `mcp_ready` 全为 `true`。 |
| 完整配置下运行模式 A 脚本 | **PASS** | 6 项全部通过，退出 `0`。`COUNT(*)` 反例返回 `mismatch` 且含反例，`ATTACH` 返回 `rejected`。这两项均未出现 `memory_limit_exceeded`。 |
| Nginx 与容器内自检 | **PASS** | `nginx -t` 和 `python -m sql_lab.check` 均退出 `0`，检查点卷存在 SQLite 文件及 WAL。 |
| 模式 B EpiKT 推荐联动 | **PASS** | 冷启动题号依次为 `57`、`62`、`63`，提交下标 `[1, 0, 0]`。第 4 题为 `75` 且 `source=epikt`。工作台返回 `source=epikt`、`guidance_tier=foundation`、`mean_predicted_probability=0.6033` 和 4 个 `priority_scenarios`。 |
| 模式 B 诊断 SSE | **PASS** | 第 75 题提交下标 `0` 判错，诊断返回 HTTP `202`。`curl -iN` 经 Nginx 得到 HTTP `200`、`content-type: text/event-stream; charset=utf-8` 和 `x-accel-buffering: no`。7 条事件连续编号，首末到达时间相差 `0.375s`，随后收到 `event: settled`。诊断最终为 `completed`。 |
| §1.5 `COUNT(*)` WorkbenchCoach | **PASS** | `status=completed`、`mode=agent`、`check.status=mismatch` 且返回反例。调用模型 2 次，耗时 `12.133s`。 |
| §1.5 概念问答与 Hybrid RAG | **PASS** | `status=completed`、`mode=agent`，两条 `retrieval_version` 事件的 `mode` 均为 `hybrid`。调用模型 3 次，耗时 `15.496s`。 |

<details>
<summary>脱敏命令输出与事件摘要</summary>

### 快进与构建摘要

```text
From https://github.com/Yikessa24/QueryStep
 * branch            main       -> FETCH_HEAD
   ff6a344..afa17cc  main       -> origin/main
Updating ff6a344..afa17cc
Fast-forward
 deploy/DOCKER_SMOKE_TEST.md |  2 +-
 deploy/nginx.conf           |  1 +
 sql_lab/query_worker.py     | 18 +++++++++++++++---
 tests/test_deploy_config.py |  1 +
 tests/test_sql_workbench.py | 22 ++++++++++++++++++++++
 5 files changed, 40 insertions(+), 4 deletions(-)
afa17cc4d89b20113b236f815dbcdbe12f5f9320
afa17cc4d89b20113b236f815dbcdbe12f5f9320
afa17cc Fix Linux fork-inherited ru_maxrss OOM in SQL worker and expose Nginx SSE buffering header
## main...origin/main
afa17cc Fix Linux fork-inherited ru_maxrss OOM in SQL worker and expose Nginx SSE buffering header
 deploy/DOCKER_SMOKE_TEST.md |  2 +-
 deploy/nginx.conf           |  1 +
 sql_lab/query_worker.py     | 18 +++++++++++++++---
 tests/test_deploy_config.py |  1 +
 tests/test_sql_workbench.py | 22 ++++++++++++++++++++++
 5 files changed, 40 insertions(+), 4 deletions(-)

docker compose config --quiet exit=0
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
docker compose up --build -d exit=0 elapsed=00:03:10.634
NAME              IMAGE           COMMAND                  SERVICE   CREATED          STATUS                    PORTS
querystep-api-1   querystep-api   "python -m uvicorn a…"   api       17 seconds ago   Up 11 seconds (healthy)   8000/tcp
querystep-db-1    postgres:16     "docker-entrypoint.s…"   db        18 seconds ago   Up 16 seconds (healthy)   5432/tcp
querystep-web-1   querystep-web   "/docker-entrypoint.…"   web       17 seconds ago   Up Less than a second     127.0.0.1:8080->80/tcp
CONTAINER           REPOSITORY          TAG                 PLATFORM            IMAGE ID            SIZE                CREATED
querystep-api-1     querystep-api       latest              linux/amd64         c944ea6399ce        498MB               59 seconds ago
querystep-db-1      postgres            16                  linux/amd64         07abc3f43c93        166MB               2 days ago
querystep-web-1     querystep-web       latest              linux/amd64         53b13b0b0cfa        28.9MB              3 minutes ago
```

### 就绪检查

```text
GET /healthz HTTP 200: {"status":"ok","service":"querystep","catalog_version":"dbe-v1-c5271713de70-demo","epikt_ready":true,"tutor_ready":true,"coach_ready":true,"sql_workbench_ready":true,"sql_workbench_reason":null,"sql_coach_ready":true,"sql_coach_reason":null,"tutor_status":"configured","diagnostics_ready":true,"mcp_ready":true,"diagnostics_reason":null}
Readiness: {"epikt_ready":true,"tutor_ready":true,"coach_ready":true,"sql_workbench_ready":true,"sql_coach_ready":true,"diagnostics_ready":true,"mcp_ready":true}
Verdict: {"case":"health","pass":true}
```

### 模式 A 原脚本、Nginx 和 MCP 自检

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
nginx -t exit=0
1. Frontend index.html: OK
2. Session cookie created: OK
3. /api/sql/tasks: OK (10 tasks, coach_available=True, rec={'available': False, 'source': 'none', 'reason': 'no_epikt_or_history'})
4. SQL sandbox counterexample (mismatch): OK
5. SQL sandbox security rejection (ATTACH): OK
6. Formal practice + PostgreSQL persistence: OK
ALL MODE-A API SMOKE CHECKS PASSED!
Mode A API script exit=0
total 76
drwxr-xr-x 2 root root  4096 Nov 26 07:32 .
drwxr-xr-x 1 root root  4096 Nov 26 07:32 ..
-rw------- 1 root root  4096 Nov 26 07:32 diagnosis-checkpoints.sqlite3
-rw------- 1 root root 32768 Nov 26 07:32 diagnosis-checkpoints.sqlite3-shm
-rw------- 1 root root 24752 Nov 26 07:32 diagnosis-checkpoints.sqlite3-wal
runtime listing exit=0
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
    "before_id": "00c5d6c02a0b446f9943853322280a2b",
    "after_id": "c69ccd0f827c40f9acae23b9ba176a67",
    "comparison_id": "028bc35897904694a946472283724c0f",
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
```

### 模式 B EpiKT 和 SSE

```text
Cold start answer: {"position":1,"item":57,"source":"rule","option":1,"correct":false}
Cold start answer: {"position":2,"item":62,"source":"rule","option":0,"correct":false}
Cold start answer: {"position":3,"item":63,"source":"rule","option":0,"correct":true}
Fourth practice item: {"id":75,"source":"epikt","reason":"consolidate"}
Workbench recommendation: {"available":true,"source":"epikt","task_id":"filter_paid","task_title":"筛选已付款订单","topic":"where","guidance_tier":"foundation","scaffolding_level":"step_by_step","priority_scenarios":["sample","boundary","empty","duplicates"],"mean_predicted_probability":0.6033,"candidate_count":2,"model_version":"c31ae1ebdda8","snapshot_history_version":3,"current_history_version":3,"reason":"lowest_calibrated_topic_probability"}
Fourth answer: {"item":75,"option":0,"correct":false}
Diagnosis accepted: {"http":202,"status":"queued"}
curl -iN response headers: {"status":"HTTP/1.1 200 OK","content-type":"text/event-stream; charset=utf-8","x-accel-buffering":"no"}
SSE: {"at_s":0.036,"seq":1,"type":"run_started","status":"running"}
SSE: {"at_s":0.326,"seq":2,"type":"branch_started","status":"running"}
SSE: {"at_s":0.326,"seq":3,"type":"branch_started","status":"running"}
SSE: {"at_s":0.326,"seq":4,"type":"branch_finished","status":"needs_input"}
SSE: {"at_s":0.341,"seq":5,"type":"branch_finished","status":"ok"}
SSE: {"at_s":0.411,"seq":6,"type":"evidence_verified","mode":"clarify"}
SSE: {"at_s":0.411,"seq":7,"type":"run_finished","status":"completed"}
SSE: {"at_s":0.411,"line":"event: settled"}
SSE verdict: {"curl_exit":0,"events":7,"arrival_span_s":0.375,"http_200":true,"content_type":true,"x_accel_buffering_no":true,"seven_sequential_events":true,"progressive_arrival":true,"settled":true}
Diagnosis final: {"status":"completed","mode":"clarify"}
Verdict: {"case":"mode-b","pass":true}
```

### §1.5 WorkbenchCoach 和 Hybrid RAG

```text
WorkbenchCoach result: {"case":"coach","http_submit":202,"status":"completed","mode":"agent","check_status":"mismatch","counterexample":true,"check_error":null,"elapsed_s":12.133,"metrics":{"finish_reason":"answer","model_calls":2,"tool_calls":1,"provider_calls_this_attempt":2,"usage_this_attempt":{"prompt_tokens":3456,"completion_tokens":270,"total_tokens":3726}},"retrieval_version":[],"trace":[{"seq":1,"type":"plan","tool":null},{"seq":2,"type":"tool_completed","tool":"check_student_sql"},{"seq":3,"type":"observation","tool":null},{"seq":4,"type":"plan","tool":null},{"seq":5,"type":"observation","tool":null}]}
Verdict: {"case":"coach","pass":true}

WorkbenchCoach result: {"case":"concept","http_submit":202,"status":"completed","mode":"agent","check_status":null,"counterexample":false,"check_error":null,"elapsed_s":15.496,"metrics":{"finish_reason":"answer","model_calls":3,"tool_calls":2,"provider_calls_this_attempt":3,"usage_this_attempt":{"prompt_tokens":5687,"completion_tokens":395,"total_tokens":6082}},"retrieval_version":[{"mode":"hybrid","corpus":"2a329b4f082cd0af1a6b3105fb85d9a0903e39a0860436c5e601346b362b66a0"},{"mode":"hybrid","corpus":"2a329b4f082cd0af1a6b3105fb85d9a0903e39a0860436c5e601346b362b66a0"}],"trace":[{"seq":1,"type":"plan","tool":null},{"seq":2,"type":"retrieval_version","tool":"search_course"},{"seq":3,"type":"tool_completed","tool":"search_course"},{"seq":4,"type":"observation","tool":null},{"seq":5,"type":"plan","tool":null},{"seq":6,"type":"retrieval_version","tool":"search_course"},{"seq":7,"type":"tool_completed","tool":"search_course"},{"seq":8,"type":"observation","tool":null},{"seq":9,"type":"plan","tool":null},{"seq":10,"type":"observation","tool":null}]}
Verdict: {"case":"concept","pass":true}
```

### 脱敏日志

```text
docker compose logs --tail=80 api web exit=0; matching error lines=0
## main...origin/main
```

</details>
