const assert = require("node:assert/strict");
const { chromium } = require("playwright");

// Mock mode is the default and intercepts every API request, including session creation.
// No API request in mock mode is forwarded to the running user's backend.
const base = process.env.QUERYSTEP_TEST_WEB_URL || "http://127.0.0.1:5173";
const mode = process.argv.includes("--real") ? "real" : "mock";
const malicious = '<img src=x onerror="window.workbenchXSS=1">';
const hiddenReference = "SECRET_REFERENCE_SQL_MUST_NOT_RENDER";
const tables = [
  { name: "courses", columns: ["id", "title"], types: ["INTEGER", "TEXT"], rows: [[1, "SQL 入门"], [2, malicious], [3, null]] },
  { name: "enrolments", columns: ["id", "course_id"], types: ["INTEGER", "INTEGER"], rows: [[11, 1], [12, 1]] },
];
const taskIds = ["select_basics", "filter_rows", "left_join_counts", "group_counts", "having_groups", "null_values", "distinct_rows", "subquery_exists", "union_rows", "ordered_rows"];
const tasks = taskIds.map((id, index) => ({ id, title: id === "left_join_counts" ? "统计每门课程的选课人数" : `实作任务 ${index + 1}`, topic: "join", concepts: ["LEFT JOIN", "COUNT", "NULL"], prompt: "列出每门课程及其选课人数。没有选课记录的课程也要保留，人数为 0。", starter_sql: "SELECT c.id, COUNT(e.id) FROM courses c LEFT JOIN enrolments e ON c.id = e.course_id GROUP BY c.id;", dialect: "sqlite", version: 1, tables, ordered: false }));
const wrongSQL = "SELECT c.id, COUNT(*) FROM courses c LEFT JOIN enrolments e ON c.id = e.course_id GROUP BY c.id;";
const rightSQL = tasks[2].starter_sql;
const query = (rows = [[1, 2], [2, 0]]) => ({ status: "ok", columns: ["id", "n"], rows, row_count: rows.length, error: null, elapsed_ms: 7, fingerprint: "mock", scenario: "boundary", seed: 17 });
const check = (passed) => ({ status: passed ? "passed" : "mismatch", passed, checked: passed ? 4 : 2, total: 4, message: passed ? "当前测试数据均符合要求。" : "未选课的课程人数应为 0。", query_result: query(), counterexample: passed ? null : { scenario: "unmatched", seed: 17, tables, actual: query([[1, 2], [2, 1]]), expected: query() } });
function resultFor(run) {
  if (run.action === "run") {
    if (run.sql.includes("DROP")) return { kind: "run", query: { ...query([]), status: "rejected", error: "只允许只读查询。" } };
    if (run.sql.includes("TIMEOUT")) return { kind: "run", query: { ...query([]), status: "timeout", error: "查询超过执行时限。" } };
    if (run.sql.includes("BROKEN")) return { kind: "run", query: { ...query([]), status: "error", error: "SQL 语法错误。" } };
    return { kind: "run", query: query() };
  }
  if (run.action === "check") return { kind: "check", check: check(!run.sql.includes("COUNT(*)")) };
  return {
    kind: "coach", mode: "evidence_only", text: `先观察右表匹配列，再判断 COUNT 的计数对象。${malicious}`, question: "没有匹配记录时，e.id 是什么？",
    citations: [{ id: "course", title: "LEFT JOIN 课程依据", url: "https://example.test/sql", text: "外连接保留未匹配的左表行。" }, { id: "unsafe", title: "危险链接作为文本", url: "javascript:alert(1)" }],
    evidence: [
      { id: "e1", tool: "run_student_sql", data: query() }, { id: "e2", tool: "check_student_sql", data: check(false) },
      { id: "e3", tool: "search_course", data: { cards: [{ id: "card", title: "COUNT 的课程检索证据", text: `COUNT(列) 不计 NULL。${malicious}`, url: "https://example.test/count", citation_id: "e3.c1", private_debug: hiddenReference }, { id: "unsafe", title: "检索危险链接", text: "不能执行链接。", url: "javascript:alert(1)", citation_id: "e3.c2" }], private_debug: hiddenReference } },
      { id: "e4", tool: "inspect_student_sql", data: { valid: true, error: null, private_debug: hiddenReference } },
      { id: "e5", tool: "inspect_student_sql", data: { valid: false, error: "unknown_column" } },
      { kind: "unknown", data: { reference_sql: hiddenReference, payload: "x".repeat(10000) } },
    ],
    metrics: { model: "test-model", workflow_version: "workbench-coach-v1", prompt_version: "workbench-plan-v1", tool_version: "workbench-readonly-v1", task_version: "1", service_version: "test-service", attempt_elapsed_ms: 123, elapsed_ms: 456, provider_calls_this_attempt: 1, model_calls: 2, tool_calls: 4, usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 }, usage_this_attempt: { prompt_tokens: null, completion_tokens: null, total_tokens: null }, cost: null, model_records: [{ private_debug: hiddenReference }], private_debug: hiddenReference },
    learning_context: { recent_independent_attempts: [{ sequence: 1, topic: "join", correct: false, private_debug: hiddenReference }], epikt: { available: true, model_version: "epikt-test", snapshot_history_version: 2, current_history_version: 3, candidates: [{ item_id: 75, topic: "join", predicted_correct_probability: 0.625, private_debug: hiddenReference }] }, confirmed_notes: [{ id: "note", version: 2, summary: `先检查未匹配客户。${malicious}`, private_debug: hiddenReference }], practice_activity: [{ action: "check", status: "mismatch", assisted: false }], private_debug: hiddenReference },
  };
}
function gate(state, key) { return new Promise((resolve) => { state[key] = resolve; }); }
async function waitFor(checkFn, message = "Condition timed out") {
  const start = Date.now();
  while (!(await checkFn())) {
    if (Date.now() - start > 8000) throw new Error(message);
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}
function release(state, key) { assert.equal(typeof state[key], "function", `Missing ${key}`); state[key](); state[key] = null; }
async function fixtures(context, { formal = false, coachAvailable = true } = {}) {
  const formalQuestion = { status: "ready", decision_id: "formal-1", source: "rule", reason: "cold_start", item: { id: 75, title: "Q3-19", topic: "aggregate", level: 2, prompt: "How many groups?", options: ["1", "2", "3", "4"] } };
  const formalFeedback = { decision_id: "formal-1", event_seq: 1, correct: false, selected_option: 1, template_hint: "先观察分组。" };
  const state = { started: formal, sessionCalls: 0, nextCalls: 0, calls: [], unexpected: [], failList: 0, failSession: 0, failDetail: "", holdDetail: "", releaseDetail: null, failSave: 0, holdSave: false, releaseSave: null, saves: [], drafts: Object.fromEntries(tasks.map((task) => [task.id, { sql: "", version: 0 }])), runs: [], byKey: new Map(), posts: [], failPost: 0, holdPost: false, releasePost: null, nextStatus: "queued", autoComplete: true, failPoll: 0, pollCalls: 0, holdPoll: false, releasePoll: null, denyResume: false, failCancel: 0, formalQuestion, formalFeedback };
  await context.route("**/api/**", async (route) => {
    const req = route.request(); const pathname = new URL(req.url()).pathname; const body = req.postDataJSON(); const method = req.method();
    state.calls.push({ method, pathname, body });
    const reply = (json, status = 200) => route.fulfill({ status, json });
    if (pathname === "/api/practice/progress") return state.started ? reply({ total: formal ? 1 : 0, correct: 0, pending: null, last: formal ? { presentation: formalQuestion, feedback: formalFeedback, turns: [{ message: "之前的提问", text: "之前的辅导内容", source: "template", citations: [], memory_ids: [] }] } : null }) : reply({ detail: "没有会话" }, 401);
    if (pathname === "/api/session") { state.sessionCalls += 1; assert.ok(!req.url().includes("restart"), "SQL entry must not restart the session"); if (state.failSession-- > 0) return reply({ detail: "会话服务暂不可用" }, 503); state.started = true; return reply({}); }
    if (pathname === "/api/practice/next") { state.nextCalls += 1; return reply(formalQuestion); }
    if (pathname === "/api/learning-memories") return reply([]);
    if (pathname.startsWith("/api/practice/history/")) return reply({ presentation: formalQuestion, feedback: formalFeedback, turns: [] });
    if (pathname.endsWith("/transfer")) return reply({ available: true, exercise: null, feedback: null });
    if (pathname.endsWith("/diagnosis")) return reply({ available: true, topic: "aggregate", run: null });
    if (pathname.endsWith("/coach") && !pathname.startsWith("/api/sql/")) return reply({ available: false, can_submit: true, runs: [] });
    if (pathname === "/api/sql/tasks") { if (state.failList-- > 0) return reply({ detail: "任务列表暂不可用" }, 503); return reply({ available: true, coach_available: coachAvailable, coach_reason: coachAvailable ? null : "model_unavailable", tasks: tasks.map(({ id, title, topic, concepts }) => ({ id, title, topic, concepts })) }); }
    const detail = pathname.match(/^\/api\/sql\/tasks\/([^/]+)$/);
    if (detail) {
      const id = detail[1];
      if (state.failDetail === id) { state.failDetail = ""; return reply({ detail: "任务暂时读取失败" }, 503); }
      const data = structuredClone({ task: tasks.find((task) => task.id === id), draft: state.drafts[id], runs: state.runs.filter((run) => run.task_id === id) });
      if (state.holdDetail === id) { state.holdDetail = ""; await gate(state, "releaseDetail"); }
      return reply(data);
    }
    const draft = pathname.match(/^\/api\/sql\/tasks\/([^/]+)\/draft$/);
    if (draft) {
      assert.equal(method, "PUT"); const id = draft[1]; state.saves.push({ id, ...body });
      if (state.failSave-- > 0) return reply({ detail: "草稿保存服务暂不可用" }, 503);
      if (body.version !== state.drafts[id].version) return reply({ detail: { code: "draft_conflict", message: "草稿版本冲突" } }, 409);
      state.drafts[id] = { sql: body.sql, version: body.version + 1 }; const result = { ...state.drafts[id] };
      if (state.holdSave) { state.holdSave = false; await gate(state, "releaseSave"); }
      return reply(result);
    }
    const create = pathname.match(/^\/api\/sql\/tasks\/([^/]+)\/runs$/);
    if (create) {
      assert.equal(method, "POST"); state.posts.push({ task_id: create[1], ...body });
      let run = state.byKey.get(body.idempotency_key);
      if (!run) {
        const count = state.runs.length + 1;
        run = { id: `run-${count}`, task_id: create[1], sql: body.sql, action: body.action, message: body.message, status: state.nextStatus, events: [{ seq: 1, type: "queued", data: { reference_sql: hiddenReference } }], result: null, created_at: new Date(Date.UTC(2026, 0, 1, 10, 0, count)).toISOString() };
        if (run.status === "completed") run.result = state.resultOverride ?? resultFor(run);
        state.runs.push(run); state.byKey.set(body.idempotency_key, run); state.nextStatus = "queued";
      }
      if (state.holdPost) { state.holdPost = false; await gate(state, "releasePost"); }
      if (state.failPost-- > 0) return reply({ detail: "响应中断，请重试同一请求" }, 503);
      return reply(run, 202);
    }
    const runRoute = pathname.match(/^\/api\/sql\/runs\/([^/]+)(?:\/(cancel|resume))?$/);
    if (runRoute) {
      const run = state.runs.find((value) => value.id === runRoute[1]); assert.ok(run);
      if (runRoute[2] === "cancel") {
        if (state.failCancel-- > 0) return reply({ detail: "取消服务暂不可用" }, 503);
        run.status = "cancelled"; run.events.push({ seq: run.events.length + 1, type: "cancelled" }); return reply(run);
      }
      if (runRoute[2] === "resume") {
        if (state.denyResume) return reply({ detail: "此失败运行不可恢复，请重新提交" }, 409);
        run.status = "queued"; run.events.push({ seq: run.events.length + 1, type: "resumed" }); return reply(run);
      }
      state.pollCalls += 1;
      if (state.failPoll-- > 0) return reply({ detail: "状态读取服务暂不可用" }, 503);
      if (state.autoComplete && ["queued", "running"].includes(run.status)) {
        run.status = "completed"; run.result = state.resultOverride ?? resultFor(run);
        for (const [type, tool] of [["tool_started", run.action], ["tool_completed", run.action === "coach" ? "check_student_sql" : run.action], ["observation", null], ["completed", null]]) run.events.push({ seq: run.events.length + 1, type, tool, elapsed_ms: 7 });
        if (run.action === "coach") run.events.push({ seq: run.events.length + 1, type: "retrieval_version", tool: "search_course", data: { mode: "hybrid", corpus: "a".repeat(64), reference_sql: hiddenReference } });
      }
      const snapshot = structuredClone(run);
      if (state.holdPoll) { state.holdPoll = false; await gate(state, "releasePoll"); }
      return reply(snapshot);
    }
    state.unexpected.push(`${method} ${pathname}`);
    return reply({ detail: "Unmocked endpoint blocked" }, 501);
  });
  await context.route("**/healthz", (route) => route.fulfill({ json: { status: "ok" } }));
  return state;
}
const editor = (page) => page.getByRole("textbox", { name: "你的 SQL", exact: true });
const coachInput = (page) => page.getByRole("textbox", { name: "向实验教练提问", exact: true });
const saveDone = (page) => page.getByText("草稿已保存", { exact: true }).waitFor();
const selectedRun = (page) => page.getByRole("article", { name: "选定实验" });
async function enter(page) { await page.getByRole("button", { name: "SQL 实作", exact: true }).click(); }
async function waitSelected(page, id) { await page.locator(`.sql-wb-selected[data-run-id="${id}"]`).waitFor(); }
async function runAndWait(page, action = "运行 SQL") {
  await page.getByRole("button", { name: action, exact: true }).waitFor();
  const responsePromise = page.waitForResponse((response) => response.request().method() === "POST" && /\/api\/sql\/tasks\/[^/]+\/runs$/.test(new URL(response.url()).pathname));
  await page.getByRole("button", { name: action, exact: true }).click();
  const response = await responsePromise; assert.equal(response.status(), 202);
  const run = await response.json();
  await waitSelected(page, run.id);
  await selectedRun(page).getByText("已完成", { exact: true }).waitFor({ timeout: 60000 });
  return run.id;
}

async function mockWorkbench(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  const state = await fixtures(context); state.failList = 1;
  const page = await context.newPage(); const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await page.goto(base); await enter(page);
    await page.getByText("任务列表暂不可用", { exact: true }).waitFor();
    await page.getByRole("button", { name: "重试加载任务列表" }).click();
    await editor(page).waitFor();
    assert.equal(state.sessionCalls, 1); assert.equal(state.nextCalls, 0);
    assert.equal(await page.getByLabel("选择实作任务").inputValue(), "left_join_counts");
    assert.deepEqual(await page.getByLabel("选择实作任务").locator("option").evaluateAll((nodes) => nodes.map((node) => node.value)), taskIds);
    for (const name of ["运行 SQL", "提交验证", "请教实验教练"]) assert.equal(await page.getByRole("button", { name, exact: true }).isDisabled(), true);
    assert.equal(await editor(page).getAttribute("maxlength"), "6000"); assert.equal(await coachInput(page).getAttribute("maxlength"), "500");
    assert.equal(await page.locator(".sql-wb img").count(), 0);

    // A delayed save must not replace newer editing, and saves use successive versions.
    state.holdSave = true;
    await editor(page).fill("SELECT 1;");
    await waitFor(() => state.releaseSave, "First save was not sent");
    await editor(page).fill(wrongSQL);
    release(state, "releaseSave"); await saveDone(page);
    assert.equal(await editor(page).inputValue(), wrongSQL);
    assert.equal(state.drafts.left_join_counts.sql, wrongSQL);
    assert.deepEqual(state.saves.slice(0, 2).map((save) => save.version), [0, 1]);

    // Save failure retains local SQL and has a direct retry, including after a task switch.
    state.failSave = 1; await editor(page).fill("SELECT 2;");
    await page.getByRole("button", { name: "重试保存草稿" }).waitFor();
    assert.equal(await editor(page).inputValue(), "SELECT 2;");
    await page.getByRole("button", { name: "重试保存草稿" }).click(); await saveDone(page);
    state.failDetail = "select_basics";
    await page.getByLabel("选择实作任务").selectOption("select_basics");
    await page.getByRole("button", { name: "重试加载此任务" }).click(); await editor(page).waitFor();
    await editor(page).fill("SELECT 'other task';"); await saveDone(page);
    state.holdDetail = "filter_rows";
    await page.getByLabel("选择实作任务").selectOption("filter_rows"); await waitFor(() => state.releaseDetail);
    await page.getByLabel("选择实作任务").selectOption("left_join_counts");
    release(state, "releaseDetail");
    assert.equal(await editor(page).inputValue(), "SELECT 2;");
    assert.equal(await page.getByLabel("选择实作任务").inputValue(), "left_join_counts");

    // Conflict resolution never silently advances the local version and overwrites another tab.
    const remote = "SELECT 'from another tab';";
    state.drafts.left_join_counts = { sql: remote, version: state.drafts.left_join_counts.version + 1 };
    await editor(page).fill("SELECT 'local conflict';");
    await page.getByText("草稿版本冲突 · 本地输入已保留", { exact: true }).waitFor();
    await editor(page).fill("SELECT 'newer local conflict';");
    await page.getByRole("button", { name: "读取远端草稿" }).click();
    await page.getByRole("button", { name: "使用远端草稿（替换编辑器）" }).waitFor();
    assert.equal(await editor(page).inputValue(), "SELECT 'newer local conflict';"); assert.equal(state.drafts.left_join_counts.sql, remote);
    await page.getByRole("button", { name: "使用远端草稿（替换编辑器）" }).click();
    assert.equal(await editor(page).inputValue(), remote);
    await page.getByText("冲突前的本地 SQL（可复制）", { exact: true }).click();
    assert.equal(await page.getByRole("textbox", { name: "冲突前的本地 SQL", exact: true }).inputValue(), "SELECT 'newer local conflict';");

    // A lost response retry reuses the key and the accepted run; successful/new input creates a new key.
    await editor(page).fill(wrongSQL); await saveDone(page);
    state.failPost = 1;
    await page.getByRole("button", { name: "运行 SQL", exact: true }).click();
    await page.getByRole("button", { name: "重试运行 SQL", exact: true }).click();
    await selectedRun(page).getByText("已完成", { exact: true }).waitFor();
    assert.equal(state.posts[0].idempotency_key, state.posts[1].idempotency_key); assert.equal(state.runs.length, 1);
    assert.equal(await editor(page).inputValue(), wrongSQL);
    await runAndWait(page, "提交验证");
    await page.getByText("发现结果差异", { exact: true }).waitFor();
    assert.equal(await page.getByRole("region", { name: "你的结果", exact: true }).locator(".sql-wb-different").count(), 1);
    assert.equal(await page.getByRole("region", { name: "预期结果", exact: true }).locator(".sql-wb-different").count(), 1);
    assert.equal(await page.locator(".sql-wb-events").getAttribute("open"), null);
    await page.locator(".sql-wb-events > summary").click();
    assert.equal(await page.getByText(hiddenReference, { exact: false }).count(), 0);
    assert.notEqual(state.posts[1].idempotency_key, state.posts[2].idempotency_key);
    await editor(page).fill(rightSQL); await runAndWait(page, "提交验证");
    await page.getByText("通过当前测试", { exact: true }).waitFor();
    await selectedRun(page).getByRole("button", { name: "恢复此运行 SQL 到编辑器" }).click();
    assert.equal(await editor(page).inputValue(), rightSQL);
    const olderRun = page.getByRole("region", { name: "最近实验" }).getByRole("button").last();
    await olderRun.click(); await selectedRun(page).getByRole("button", { name: "恢复此运行 SQL 到编辑器" }).click();
    assert.equal(await editor(page).inputValue(), wrongSQL); await saveDone(page);

    // IME Enter never sends; pending success/failure must not clear a newly typed question.
    await coachInput(page).fill("为何人数不正确？"); const beforeIME = state.posts.length;
    await coachInput(page).evaluate((node) => node.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, isComposing: true })));
    await coachInput(page).evaluate((node) => node.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229, bubbles: true })));
    assert.equal(state.posts.length, beforeIME);
    state.holdPost = true; await coachInput(page).press("Enter"); await waitFor(() => state.releasePost);
    await coachInput(page).fill("下一条新输入不会丢失"); release(state, "releasePost");
    await waitSelected(page, state.runs.at(-1).id);
    await selectedRun(page).getByText("已完成", { exact: true }).waitFor();
    assert.equal(await coachInput(page).inputValue(), "下一条新输入不会丢失");
    await page.getByRole("link", { name: "LEFT JOIN 课程依据" }).waitFor();
    assert.equal(await page.getByRole("link", { name: "危险链接作为文本" }).count(), 0);
    assert.equal(await page.locator(".sql-wb img").count(), 0);
    await page.getByText("查看实验依据", { exact: true }).click();
    await page.getByRole("region", { name: "查询证据", exact: true }).waitFor();
    await page.getByRole("link", { name: "COUNT 的课程检索证据" }).waitFor();
    assert.equal(await page.getByRole("link", { name: "检索危险链接" }).count(), 0);
    await page.getByText("引用 e3.c1", { exact: true }).waitFor();
    await page.getByText("当前 SQL 通过有效性检查；不代表结果符合任务。", { exact: true }).waitFor();
    await page.getByText("当前 SQL 未通过有效性检查：找不到所用列，请核对表结构。", { exact: true }).waitFor();
    for (const selector of [".sql-wb-metrics", ".sql-wb-learning"]) {
      assert.equal(await page.locator(selector).getAttribute("open"), null);
      await page.locator(`${selector} > summary`).click();
    }
    await page.getByText("test-model", { exact: true }).waitFor();
    await page.getByText("仅保留证据（降级）", { exact: true }).waitFor();
    await page.getByText("输入 100 / 输出 20 / 合计 120", { exact: true }).waitFor();
    await page.getByText("输入 未知 / 输出 未知 / 合计 未知", { exact: true }).waitFor();
    assert.equal(await page.locator(".sql-wb-metrics dt").filter({ hasText: /^费用$/ }).locator("+ dd").textContent(), "未知");
    await page.getByText("正式题候选 1 · 表连接 · 62.5%", { exact: true }).waitFor();
    await page.getByText(/快照已过时：/).waitFor();
    await page.getByText(/版本 2 · 先检查未匹配客户/).waitFor();
    await page.locator(".sql-wb-events > summary").click();
    for (const text of ["开始调用工具", "工具执行完成", "汇总实验观察", "核对场景与边界"]) assert.ok((await page.locator(".sql-wb-events").textContent()).includes(text));
    assert.equal(await page.locator(".sql-wb img").count(), 0);
    assert.equal(await page.evaluate(() => window.workbenchXSS), undefined);
    assert.equal(await page.getByText(hiddenReference, { exact: false }).count(), 0);
    state.holdPost = true; state.failPost = 1;
    await coachInput(page).press("Enter"); await waitFor(() => state.releasePost);
    await coachInput(page).fill("失败期间的新输入"); release(state, "releasePost");
    await page.getByText("输入已更新，请按当前内容重新提交。", { exact: true }).first().waitFor();
    assert.equal(await coachInput(page).inputValue(), "失败期间的新输入");
    state.failPost = 1; await coachInput(page).press("Enter");
    await runAndWait(page, "重试请教实验教练");
    await page.locator(".sql-wb-events > summary").click();
    await page.getByText(`hybrid · 课程版本 ${"a".repeat(64)}`, { exact: true }).waitFor();
    assert.equal(await page.getByText(hiddenReference, { exact: true }).count(), 0);
    assert.equal(state.posts.at(-1).idempotency_key, state.posts.at(-2).idempotency_key);
    assert.equal(await coachInput(page).inputValue(), "");

    // Poll failures explicitly retry; stale polling cannot undo cancellation.
    state.failPoll = 1; await page.getByRole("button", { name: "运行 SQL", exact: true }).click();
    await page.getByRole("button", { name: "重试读取状态" }).click();
    await selectedRun(page).getByText("已完成", { exact: true }).waitFor();
    state.autoComplete = false; state.holdPoll = true;
    await page.getByRole("button", { name: "运行 SQL", exact: true }).click(); await waitFor(() => state.releasePoll);
    state.failCancel = 1; await page.getByRole("button", { name: "取消执行", exact: true }).click();
    await page.getByText(/取消服务暂不可用/).waitFor();
    await page.getByRole("button", { name: "取消执行", exact: true }).click();
    await selectedRun(page).getByText("已取消", { exact: true }).waitFor();
    release(state, "releasePoll");
    await editor(page).fill(rightSQL); await saveDone(page);
    assert.equal(await selectedRun(page).getByRole("button", { name: "取消执行", exact: true }).count(), 0);
    state.autoComplete = true; state.nextStatus = "interrupted";
    await page.getByRole("button", { name: "运行 SQL", exact: true }).click();
    await page.getByRole("button", { name: "恢复执行", exact: true }).click();
    await selectedRun(page).getByText("已完成", { exact: true }).waitFor();
    state.nextStatus = "failed"; state.denyResume = true;
    await page.getByRole("button", { name: "运行 SQL", exact: true }).click();
    await page.getByRole("button", { name: "恢复执行", exact: true }).click();
    await page.getByText(/此失败运行不可恢复，请重新提交/).waitFor();
    assert.equal(await editor(page).inputValue(), rightSQL);

    for (const [sql, message] of [["DROP TABLE courses;", "只允许只读查询。"], ["SELECT TIMEOUT;", "查询超过执行时限。"], ["SELECT BROKEN;", "SQL 语法错误。"]]) {
      await editor(page).fill(sql); await runAndWait(page); await page.getByText(message, { exact: true }).waitFor();
    }
    assert.equal(await page.getByRole("region", { name: "最近实验" }).getByRole("button").count(), 8);
    await editor(page).fill(rightSQL); await saveDone(page);

    // Switching to formal practice preserves SQL state and does not start a formal question.
    await page.getByRole("button", { name: "练习工作台", exact: true }).click();
    await page.getByRole("button", { name: "开始练习", exact: true }).waitFor();
    await enter(page); assert.equal(await editor(page).inputValue(), rightSQL);
    const mainBox = await page.locator("#sql-workspace").boundingBox();
    const coachBox = await page.getByRole("complementary", { name: "实验教练", exact: true }).boundingBox();
    assert.ok(coachBox.x >= mainBox.x + mainBox.width - 1);
    await page.locator("#sql-workspace").evaluate((node) => { node.scrollTop = node.scrollHeight; });
    assert.deepEqual(await page.getByRole("complementary", { name: "实验教练", exact: true }).boundingBox(), coachBox);
    await page.reload(); await enter(page); await editor(page).waitFor();
    assert.equal(await editor(page).inputValue(), rightSQL); assert.equal(state.sessionCalls, 1);
    await page.getByLabel("选择实作任务").selectOption("select_basics"); await editor(page).waitFor();
    assert.equal(await editor(page).inputValue(), "SELECT 'other task';");
    await page.getByLabel("选择实作任务").selectOption("left_join_counts");

    // 320px entry stays visible; practice/assistant retain their mobile switch and contained tables.
    await page.setViewportSize({ width: 320, height: 740 });
    await page.getByRole("button", { name: "正式练习", exact: true }).click();
    await enter(page); await editor(page).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.locator("#sql-workspace").evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
    await page.getByRole("navigation", { name: "切换学习面板" }).getByRole("button", { name: "助教", exact: true }).click();
    await coachInput(page).waitFor();
    const composer = await page.locator(".sql-wb-composer").boundingBox();
    assert.ok(composer.x >= 0 && composer.x + composer.width <= 321 && composer.y + composer.height <= 684);
    assert.equal(await page.getByRole("complementary", { name: "实验教练", exact: true }).evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
    await page.getByRole("button", { name: "返回实作练习" }).click(); await editor(page).waitFor();
    assert.equal(state.nextCalls, 0); assert.deepEqual(state.unexpected, []); assert.deepEqual(pageErrors, []);
    console.log("Mock SQL workbench: sessions, list/detail failures, serialized saves, 409 conflict, cross-task/refresh, idempotency, IME, message retention, evidence, cancel/resume, query failures, history and 320px layout passed.");
  } finally { await context.close(); }
}

async function mockPresentation(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const state = await fixtures(context); const page = await context.newPage(); const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const show = async (result) => { state.resultOverride = result; state.nextStatus = "completed"; await runAndWait(page); };
  const labels = {
    invalid_sql: "SQL 内容无效，请检查输入。", single_select_required: "只允许一条 SELECT 查询。", unsupported_sql: "暂不支持此 SQL 写法。",
    unknown_column: "找不到所用列，请核对表结构。", unknown_table: "找不到所用表，请核对表名。", ambiguous_column: "列名有歧义，请补充表名或别名。",
    syntax_error: "SQL 语法错误，请检查语句。", invalid_aggregate: "聚合用法无效，请检查分组与聚合表达式。", query_error: "查询执行失败，请检查语句。",
    query_too_complex: "查询过于复杂，请简化后重试。", query_not_allowed: "此查询操作不被允许，仅支持只读查询。", table_not_allowed: "只能查询当前任务允许的表。",
    query_timeout: "查询超过执行时限，请简化后重试。", query_cancelled: "查询已取消，输入仍保留。", sql_too_large: "SQL 超过长度限制，请缩短后重试。",
    result_limit_exceeded: "结果超过大小限制，请减少返回内容。", memory_limit_exceeded: "查询超过内存限制，请简化后重试。", worker_error: "查询执行进程异常，请重试。",
    sandbox_unavailable: "安全执行环境暂不可用，请稍后重试。", sql_parser_unavailable: "SQL 解析服务暂不可用，请稍后重试。",
  };
  try {
    await page.goto(base); await enter(page); await editor(page).fill(rightSQL);
    for (const [code, label] of Object.entries(labels)) {
      await show({ kind: "run", query: { ...query([]), status: "rejected", error: code } });
      await page.getByText(label, { exact: true }).waitFor();
      assert.equal(await page.getByText(code, { exact: true }).count(), 0);
      await show({ kind: "check", text: code, check: { ...check(false), status: "rejected", message: code, query_result: null, counterexample: null } });
      await page.getByText(label, { exact: true }).waitFor();
      assert.equal(await page.getByText(code, { exact: true }).count(), 0);
    }
    const unknown = `${malicious}${"x".repeat(1000)}`;
    await show({ kind: "run", query: { ...query([]), status: "error", error: unknown } });
    assert.equal((await page.locator(".sql-wb-query .sql-wb-warning").textContent()).length, 401);
    assert.equal(await page.locator(".sql-wb img").count(), 0);
    await show({ kind: "run", query: { ...query([]), status: "error", error: "__proto__" } });
    await page.getByText("__proto__", { exact: true }).waitFor();
    const mismatch = check(false);
    mismatch.counterexample.actual.columns = ["customer", "my_alias"];
    mismatch.counterexample.expected.columns = ["id", "expected_alias"];
    await show({ kind: "check", check: mismatch });
    await page.getByText(/列值按位置比较，忽略列名与别名/).waitFor();
    assert.equal(await page.getByText(/结果列名或列顺序不同|结果列数不同/).count(), 0);
    mismatch.counterexample.actual.columns = ["customer"];
    mismatch.counterexample.actual.rows = [[1], [2]];
    await show({ kind: "check", check: mismatch });
    await page.getByText("结果列数不同：你的结果 1 列，预期 2 列。", { exact: true }).waitFor();

    const result = resultFor({ action: "coach" });
    result.learning_context.epikt = { available: false, reason: "model_unavailable", private_debug: hiddenReference };
    await show(result); await page.locator(".sql-wb-learning > summary").click();
    await page.getByText("预测模型不可用或暂无预测：模型不可用。", { exact: true }).waitFor();
    result.learning_context.epikt = { available: true, candidates: [], model_version: "test" };
    await show(result); await page.locator(".sql-wb-learning > summary").click();
    await page.getByText("当前任务主题暂无候选正式题预测。", { exact: true }).waitFor();
    result.evidence = [{ id: "bounded", tool: "search_course", data: { cards: Array.from({ length: 20 }, (_, index) => ({ id: index, citation_id: `b.c${index}`, title: "有界课程依据", text: "界".repeat(5000), url: "javascript:alert(1)", private_debug: hiddenReference })) } }, { kind: "unknown", data: { text: hiddenReference, rows: [], columns: [], status: "ok", row_count: 0 } }];
    result.learning_context.confirmed_notes = Array.from({ length: 20 }, () => ({ version: 1, summary: "记".repeat(3000), private_debug: hiddenReference }));
    await show(result);
    await page.getByText("查看实验依据", { exact: true }).click();
    assert.equal(await page.locator(".sql-wb-course").count(), 10);
    assert.equal((await page.locator(".sql-wb-course .sql-wb-prose").first().textContent()).length, 2001);
    await page.locator(".sql-wb-learning > summary").click(); await page.locator(".sql-wb-metrics > summary").click();
    assert.equal(await page.locator(".sql-wb-learning li").filter({ hasText: "版本 1" }).count(), 4);
    assert.equal(await page.getByText(hiddenReference, { exact: false }).count(), 0);
    assert.equal(await page.evaluate(() => window.workbenchXSS), undefined);
    await page.setViewportSize({ width: 320, height: 740 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.locator("#sql-workspace").evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
    assert.deepEqual(errors, []); assert.deepEqual(state.unexpected, []);
    console.log("Mock presentation: all 20 engine codes in query/check, escaped bounded unknowns, positional grading, typed/bounded evidence, metrics, stale/unavailable/empty predictions and expanded 320px containment passed.");
  } finally { await context.close(); }
}

async function mockFormalState(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const state = await fixtures(context, { formal: true }); const page = await context.newPage();
  try {
    await page.goto(base); await page.getByText("之前的辅导内容", { exact: true }).waitFor();
    await page.getByRole("textbox", { name: "你的问题", exact: true }).fill("正式练习尚未发出的提问");
    await enter(page); await editor(page).fill(rightSQL); await runAndWait(page, "提交验证");
    assert.equal(state.sessionCalls, 0); assert.equal(state.nextCalls, 0);
    await page.getByRole("button", { name: "练习工作台", exact: true }).click();
    assert.equal(await page.getByRole("textbox", { name: "你的问题", exact: true }).inputValue(), "正式练习尚未发出的提问");
    assert.equal(await page.getByRole("radio").nth(1).isChecked(), true);
    await page.getByText("之前的辅导内容", { exact: true }).waitFor();
    await page.getByRole("button", { name: /学习记录/ }).click();
    await page.getByText("本轮完成 1 题，答对 0 题。", { exact: false }).waitFor();
    assert.deepEqual(state.unexpected, []);
    console.log("Mock formal-state preservation: selected answer, unsent tutor text, prior conversation and formal count unchanged.");
  } finally { await context.close(); }
}

async function mockUnavailableCoach(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const state = await fixtures(context, { coachAvailable: false }); const page = await context.newPage();
  try {
    await page.goto(base); await enter(page); await editor(page).fill(rightSQL);
    await page.getByText("实验教练未配置模型；仍可运行 SQL 和提交验证。", { exact: true }).waitFor();
    await page.locator("#sql-wb-message").fill("检查结果");
    assert.equal(await page.getByRole("button", { name: "请教实验教练", exact: true }).isDisabled(), true);
    await runAndWait(page, "提交验证");
    assert.equal(state.posts.length, 1);
    assert.equal(state.posts[0].action, "check");
    console.log("Unavailable coach remains explicit while SQL verification works.");
  } finally { await context.close(); }
}

// Real writes are authorized only on the new isolated frontend/proxy, never 5173/8000.
async function realWorkbench(browser) {
  if (process.env.QUERYSTEP_WORKBENCH_ISOLATED_DB !== "1" || base !== "http://127.0.0.1:5174") {
    throw new Error("Real mode requires QUERYSTEP_WORKBENCH_ISOLATED_DB=1 and QUERYSTEP_TEST_WEB_URL=http://127.0.0.1:5174 (proxying isolated 8001).");
  }
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  const blocked = []; const requests = []; const errors = []; const metrics = [];
  await context.route("**/*", async (route) => {
    const request = route.request(); const url = new URL(request.url()); const method = request.method();
    const allowedWrite = (method === "POST" && url.pathname === "/api/session" && !url.search)
      || (method === "PUT" && /^\/api\/sql\/tasks\/[^/]+\/draft$/.test(url.pathname))
      || (method === "POST" && /^\/api\/sql\/(tasks\/[^/]+\/runs|runs\/[^/]+\/cancel)$/.test(url.pathname));
    if (url.origin !== base || url.pathname === "/api/practice/next" || (!["GET", "HEAD"].includes(method) && !allowedWrite)) {
      blocked.push(`${method} ${url.origin}${url.pathname}`); return route.abort();
    }
    requests.push(`${method} ${url.pathname}`); return route.continue();
  });
  const page = await context.newPage(); page.on("pageerror", (error) => errors.push(error.message));
  const get = async (path) => { const response = await page.request.get(`${base}${path}`); assert.equal(response.status(), 200); return response.json(); };
  const completed = async (action) => {
    const id = await runAndWait(page, action); const run = await get(`/api/sql/runs/${id}`);
    assert.equal(run.status, "completed");
    const m = run.result.metrics ?? {};
    metrics.push({ action: run.action, status: run.result.query?.status ?? run.result.check?.status ?? run.result.mode, attempt_elapsed_ms: m.attempt_elapsed_ms, provider_calls: m.provider_calls_this_attempt, model_calls: m.model_calls, tool_calls: m.tool_calls, tokens: m.usage_this_attempt, cost: m.cost });
    return run;
  };
  const incorrect = "SELECT c.customer_id, COUNT(*) AS my_count FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id;";
  const correct = incorrect.replace("COUNT(*)", "COUNT(o.order_id)");
  try {
    await page.goto(base); await enter(page); await editor(page).waitFor();
    await page.getByLabel("选择实作任务").selectOption("left_join_counts");
    assert.equal(await page.getByLabel("选择实作任务").locator("option").count(), 10);
    const detail = await get("/api/sql/tasks/left_join_counts"); assert.equal(detail.task.dialect, "sqlite");
    assert.deepEqual(detail.task.tables.map((table) => table.name), ["customers", "orders"]);
    const initialProgress = await get("/api/practice/progress");
    assert.equal(initialProgress.total, 0); assert.equal(initialProgress.pending, null); assert.equal(initialProgress.last, null);
    await editor(page).fill(incorrect); await saveDone(page);
    const executed = await completed("运行 SQL");
    assert.equal(executed.result.query.status, "ok"); assert.ok(executed.result.query.rows.length > 0);
    await page.getByRole("region", { name: "查询结果 数据表", exact: true }).waitFor();
    await page.locator(".sql-wb-metrics > summary").click();
    assert.ok((await page.locator(".sql-wb-metrics").textContent()).includes("本次执行耗时"));
    assert.equal(await editor(page).inputValue(), incorrect);

    const failed = await completed("提交验证"); const checkResult = failed.result.check;
    assert.equal(checkResult.status, "mismatch"); const example = checkResult.counterexample; assert.ok(example);
    const unmatched = example.expected.rows.find((row) => row[1] === 0 && example.actual.rows.some((actual) => actual[0] === row[0] && actual[1] === 1));
    assert.ok(unmatched, "Real counterexample must show expected 0 / actual 1 for an unmatched customer");
    await page.getByText("发现结果差异", { exact: true }).waitFor();
    for (const [label, value] of [["你的结果", 1], ["预期结果", 0]]) {
      const row = page.getByRole("region", { name: `${label} 数据表`, exact: true }).locator("tr.sql-wb-different").filter({ has: page.getByRole("cell", { name: String(unmatched[0]), exact: true }) });
      assert.ok(await row.count() > 0); assert.equal(await row.first().getByRole("cell").nth(1).textContent(), String(value));
    }
    assert.equal(await page.getByText(/结果列数不同|结果列名或列顺序不同/).count(), 0);
    await page.getByText(/列值按位置比较，忽略列名与别名/).waitFor();
    await page.locator(".sql-wb-events > summary").click();
    for (const label of ["开始调用工具", "工具执行完成", "验证多组数据"]) assert.ok((await page.locator(".sql-wb-events").textContent()).includes(label));
    await editor(page).fill(correct);
    const passed = await completed("提交验证");
    assert.equal(passed.result.check.status, "passed"); assert.equal(passed.result.check.passed, true);
    assert.equal(passed.result.check.checked, 4); assert.equal(passed.result.check.total, 4);
    await page.getByText("已检查 4 / 4 组数据", { exact: true }).waitFor();

    for (const sql of ["SELECT FROM customers;", "ATTACH DATABASE ':memory:' AS extra;"]) {
      await editor(page).fill(sql); const rejected = await completed("运行 SQL");
      // Syntax can be rejected by the parser or reported as an SQLite execution error.
      assert.ok((sql.startsWith("ATTACH") ? ["rejected"] : ["rejected", "error"]).includes(rejected.result.query.status)); assert.ok(rejected.result.query.error);
      assert.equal(await page.getByText(rejected.result.query.error, { exact: true }).count(), 0);
      assert.match(await page.locator(".sql-wb-query .sql-wb-warning").textContent(), /[\u4e00-\u9fff]/);
      assert.equal(await editor(page).inputValue(), sql);
    }

    // One configured-provider question; completed fallback is valid, not claimed as agent success.
    await editor(page).fill(incorrect); await saveDone(page);
    await coachInput(page).fill("为什么没有订单的客户被计为 1？请用 check_student_sql 核对边界并给出提示");
    const coached = await completed("请教实验教练");
    assert.ok(["agent", "evidence_only"].includes(coached.result.mode)); assert.ok(coached.result.text?.trim());
    assert.equal(await editor(page).inputValue(), incorrect);
    await page.locator(".sql-wb-metrics > summary").click(); await page.locator(".sql-wb-learning > summary").click();
    await page.getByText("正式题预测正确率（EpiKT）", { exact: true }).waitFor();
    if (coached.result.mode === "evidence_only") await page.getByText("仅保留证据（降级）", { exact: true }).waitFor();
    const coachMetrics = coached.result.metrics;
    console.log("Real coach outcome:", JSON.stringify({ mode: coached.result.mode, finish_reason: coachMetrics.finish_reason, model: coachMetrics.model, workflow: coachMetrics.workflow_version, prompt: coachMetrics.prompt_version, tool: coachMetrics.tool_version, task: coachMetrics.task_version, elapsed_ms: coachMetrics.elapsed_ms, model_calls: coachMetrics.model_calls, tool_calls: coachMetrics.tool_calls, usage: coachMetrics.usage, cost: coachMetrics.cost }));

    // Cancel a real pending SQL run, without a second provider question or fake responses.
    await coachInput(page).fill("取消期间保留的未发送问题");
    const responsePromise = page.waitForResponse((response) => response.request().method() === "POST" && /\/api\/sql\/tasks\/[^/]+\/runs$/.test(new URL(response.url()).pathname));
    await page.getByRole("button", { name: "运行 SQL", exact: true }).click();
    const pendingResponse = await responsePromise; assert.equal(pendingResponse.status(), 202);
    const pending = await pendingResponse.json(); await waitSelected(page, pending.id);
    await page.getByRole("button", { name: "取消执行", exact: true }).click();
    await selectedRun(page).getByText("已取消", { exact: true }).waitFor();
    assert.equal((await get(`/api/sql/runs/${pending.id}`)).status, "cancelled");
    assert.equal(await editor(page).inputValue(), incorrect); assert.equal(await coachInput(page).inputValue(), "取消期间保留的未发送问题");
    await editor(page).fill(correct); await saveDone(page);
    await page.reload(); await enter(page); await editor(page).waitFor();
    assert.equal(await editor(page).inputValue(), correct);
    assert.equal((await get("/api/sql/tasks/left_join_counts")).draft.sql, correct);
    assert.deepEqual(await get("/api/practice/progress"), initialProgress);
    await page.getByRole("button", { name: "练习工作台", exact: true }).click();
    await page.getByRole("button", { name: "开始练习", exact: true }).waitFor(); await enter(page);
    assert.equal(await editor(page).inputValue(), correct);

    await page.setViewportSize({ width: 320, height: 740 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.locator("#sql-workspace").evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
    await page.getByRole("navigation", { name: "切换学习面板" }).getByRole("button", { name: "助教", exact: true }).click();
    await page.getByRole("region", { name: "最近实验" }).getByRole("button", { name: /请教实验教练/ }).click();
    for (const selector of [".sql-wb-metrics", ".sql-wb-learning"]) await page.locator(`${selector} > summary`).click();
    assert.equal(await page.getByRole("complementary", { name: "实验教练", exact: true }).evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
    const composer = await page.locator(".sql-wb-composer").boundingBox(); assert.ok(composer.x >= 0 && composer.x + composer.width <= 321);
    const screenshot = require("node:path").resolve(__dirname, "../artifacts/workbench-real-mobile320.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    await page.getByRole("button", { name: "返回实作练习" }).click(); assert.equal(await editor(page).inputValue(), correct);

    const expectedCorpus = process.env.QUERYSTEP_TEST_EXPECT_COURSE_CORPUS;
    if (expectedCorpus) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.getByLabel("选择实作任务").selectOption("sum_totals");
      await editor(page).fill("SELECT SUM(amount) AS total FROM line_items;");
      await saveDone(page);
      await coachInput(page).fill("这是概念问题。请先用 search_course 检索 SQLite SUM 在空表和全 NULL 时的规则，引用对应课程依据。");
      const courseRun = await completed("请教实验教练");
      assert.ok(courseRun.events.some((event) => event.type === "retrieval_version" &&
        event.data?.mode === "hybrid" && event.data?.corpus === expectedCorpus),
      "The real coach must retrieve from the expected hybrid corpus");
      assert.ok(courseRun.result.evidence.some((item) => item.tool === "search_course" &&
        item.data?.cards?.some((card) => card.id === "count/sum-null")), "The newly indexed SUM lesson must be found");
      await page.reload(); await enter(page);
      await page.getByLabel("选择实作任务").selectOption("sum_totals");
      await page.getByRole("region", { name: "最近实验" }).getByRole("button", { name: /请教实验教练/ }).first().click();
      await waitSelected(page, courseRun.id);
      await page.locator(".sql-wb-events > summary").click();
      await page.getByText(`hybrid · 课程版本 ${expectedCorpus}`, { exact: true }).waitFor();
      console.log("Confirmed real hybrid SUM retrieval and course fingerprint after refresh:", expectedCorpus.slice(0, 12));
    }

    assert.equal(requests.filter((value) => /practice\/(next|answer)/.test(value)).length, 0);
    assert.deepEqual(blocked, []); assert.deepEqual(errors, []);
    console.log("Real isolated workbench: COUNT(*) runs but mismatches 0/1; COUNT(order_id) passes 4 scenes; malformed/ATTACH rejection, one truthful coach outcome, real cancellation, persistence, no formal question/count, and 320px containment passed.");
    console.log("Real run metrics:", JSON.stringify(metrics)); console.log("Real mobile screenshot:", screenshot);
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    if (mode === "real") await realWorkbench(browser);
    else { await mockWorkbench(browser); await mockPresentation(browser); await mockFormalState(browser); await mockUnavailableCoach(browser); }
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
