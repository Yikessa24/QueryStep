const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");

const base = process.env.QUERYSTEP_TEST_WEB_URL || "http://127.0.0.1:5173";
const screenshotDir = process.env.QUERYSTEP_UI_SCREENSHOTS;
const questions = [
  { id: 75, title: "Q3-19", topic: "aggregate", level: 2,
    prompt: "How many rows will be in the result for the following Select statement?\nSELECT CourseNo, COUNT(*)\nFROM Study\nGROUP BY CourseNo\nHAVING COUNT(*) > 1;\n\n演示用表数据（合成）\n\nStudy\nStudentID | Name | CourseNo\n101 | Tom | COMP2400\n102 | Mei | COMP2400\n103 | Lin | HIST1010",
    options: ["1 row", "2 rows", "3 rows", "4 rows"] },
  { id: 81, title: "Q3-25", topic: "join", level: 3,
    prompt: "How many rows will be in the query result?\nSELECT *\nFROM Course LEFT JOIN Enrol ON Course.CourseNo=Enrol.CourseNo;\n\n演示用表数据（合成）\n\nCourse\nCourseNo | CourseName\nCOMP2400 | Relational Databases\n\nEnrol\nStudentID | CourseNo\n101 | COMP2400",
    options: ["1", "2", "3", "4"] },
];

async function fixtures(context) {
  const state = { started: false, pending: null, history: [], calls: 0, release: null, transfer: null,
    transferFeedback: null, coachAvailable: false, coachRuns: [], coachKeys: [], failNext: false, notes: [{ memory_id: "note-1", topic: "aggregate", summary: "先分组，再用 HAVING 筛选。", version: 1 }], deletes: 0 };
  await context.route("**/healthz", (route) => route.fulfill({ json: { diagnostics_ready: true } }));
  await context.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const body = request.postDataJSON();
    const method = request.method();
    const reply = (json, status = 200) => route.fulfill({ status, json });
    if (pathname === "/api/session") { state.started = true; return reply({}); }
    if (pathname === "/api/practice/progress") {
      if (!state.started) return reply({ detail: "没有会话" }, 401);
      return reply({ total: state.history.length, correct: state.history.filter((r) => r.feedback.correct).length,
        pending: state.pending, last: state.pending ? null : state.history.at(-1) || null });
    }
    if (pathname === "/api/practice/next") {
      if (state.failNext) { state.failNext = false; return reply({ detail: "选题服务暂不可用" }, 503); }
      if (state.pending) return reply(state.pending);
      if (state.history.length === questions.length) return reply({ status: "complete", remaining: 0 });
      state.pending = { status: "ready", decision_id: `decision-${state.history.length}`, item: questions[state.history.length],
        source: state.history.length ? "epikt" : "rule", reason: state.history.length ? "consolidate" : "cold_start" };
      return reply(state.pending);
    }
    const history = pathname.match(/^\/api\/practice\/history\/(\d+)$/);
    if (history) return reply(state.history[Number(history[1]) - 1]);
    if (pathname.endsWith("/replay")) return reply({ chosen_item_id: 75, source: "epikt", comparison: { rule_item_id: 81, model_version: "ui-fixture" } });
    if (pathname.endsWith("/tutor")) {
      state.calls += 1;
      await new Promise((resolve) => { state.release = resolve; });
      if (body.message === "网络失败") return reply({ detail: "辅导服务暂不可用" }, 503);
      const turn = { message: body.message, text: body.message === "超时" ? "先确定每组有哪些行。" : "先观察 `GROUP BY` 的结果，再验证 HAVING。<img src=x onerror=alert(1)>",
        source: body.message === "超时" ? "template" : "llm", fallback_reason: body.message === "超时" ? "llm_timeout" : null,
        action: "give_hint", citations: body.message === "回看第 1 轮"
          ? [{ id: "history-turn-1", title: "本题第 1 轮对话", turn_number: 1 }]
          : [{ id: "rule", title: "课程规则" }], memory_ids: ["note-1"] };
      state.history.at(-1).turns.push(turn);
      return reply(turn);
    }
    if (pathname.endsWith("/coach")) {
      if (method === "GET") return reply({ available: state.coachAvailable, can_submit: true, runs: state.coachRuns });
      state.coachKeys.push(body.idempotency_key);
      if (state.coachRuns.length === 0) {
        state.coachRuns.push({ id: "coach-ui", message: body.message, status: "completed", events: [], result: { status: "hint", text: "已经保存的教练结论。", question: null, citations: [] } });
        return reply({ detail: "教练响应暂时中断" }, 503);
      }
      return reply(state.coachRuns[0]);
    }
    if (pathname.endsWith("/diagnosis")) return reply({ available: true, topic: "aggregate", run: null });
    if (pathname.endsWith("/transfer") || pathname.endsWith("/transfer/answer")) {
      if (method === "POST" && !pathname.endsWith("/answer")) state.transfer = {
        id: "transfer-ui", context: "换一组数据，判断分组后的结果。", tables: [{ name: "Orders", columns: ["id", "category"], rows: [[1, "A"], [2, "A"], [3, "B"]] }],
        sql: "SELECT category, COUNT(*) FROM Orders GROUP BY category;", options: ["2 行", "3 行", "1 行", "0 行"] };
      if (pathname.endsWith("/answer")) state.transferFeedback = { selected_option: body.option, correct: body.option === 0, correct_option: 0, text: "两个分组返回两行。", result_columns: ["category", "count"], result_rows: [["A", 2], ["B", 1]] };
      return reply({ available: true, exercise: state.transfer, feedback: state.transferFeedback });
    }
    if (pathname === "/api/learning-memories") return reply(state.notes);
    if (pathname.startsWith("/api/learning-memories/")) {
      if (method === "PATCH") { state.notes[0].summary = body.summary; state.notes[0].version += 1; }
      if (method === "DELETE") { state.notes = []; state.deletes += 1; }
      return reply({});
    }
    if (pathname.endsWith("/answer")) {
      const result = { decision_id: state.pending.decision_id, event_seq: state.history.length + 1,
        selected_option: body.option, correct: state.history.length > 0, template_hint: "先确定每组有哪些行，再按聚合条件筛选。" };
      state.history.push({ presentation: state.pending, feedback: result, turns: [] });
      state.pending = null;
      return reply(result);
    }
    throw new Error(`Unhandled mocked endpoint: ${method} ${pathname}`);
  });
  return state;
}

async function waitFor(check, message) {
  const start = Date.now();
  while (!(await check())) {
    if (Date.now() - start > 5000) throw new Error(message);
    await new Promise((resolve) => setTimeout(resolve, 30));
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
    const state = await fixtures(context);
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto(base);
    await page.getByRole("button", { name: "开始练习", exact: true }).waitFor();
    if (screenshotDir) await page.screenshot({ path: path.join(screenshotDir, "ui-welcome-desktop.png") });
    assert.equal(await page.getByRole("textbox", { name: "你的问题", exact: true }).isDisabled(), true);
    await page.getByRole("button", { name: "开始练习", exact: true }).click();
    await page.getByRole("region", { name: "当前题目" }).waitFor();
    assert.equal(await page.getByRole("button", { name: "提交答案", exact: true }).isDisabled(), true);
    await page.locator("#practice-workspace").focus();
    await page.keyboard.press("1");
    assert.equal(await page.getByRole("radio").first().isChecked(), true);
    if (screenshotDir) await page.screenshot({ path: path.join(screenshotDir, "ui-question-desktop.png") });
    await page.getByRole("button", { name: "提交答案", exact: true }).click();
    await page.getByText("还差一步，一起理清思路", { exact: true }).waitFor();
    assert.equal(await page.locator(".option.incorrect").count(), 1);
    const main = await page.locator(".workspace-scroll").boundingBox();
    const assistant = await page.locator(".assistant-sidebar").boundingBox();
    assert.ok(assistant.x >= main.x + main.width - 1, "Assistant should be to the right of practice");
    await page.locator(".workspace-scroll").evaluate((node) => { node.scrollTop = node.scrollHeight; });
    assert.deepEqual(await page.locator(".assistant-sidebar").boundingBox(), assistant, "Practice scrolling must not move assistant");
    const textbox = page.getByRole("textbox", { name: "你的问题", exact: true });
    await page.getByRole("button", { name: /先给我一点提示/ }).click();
    assert.match(await textbox.inputValue(), /不要直接告诉我答案/);
    await textbox.fill("先看分组");
    await textbox.press("Shift+Enter");
    await textbox.press("End");
    await page.keyboard.type("next");
    assert.match(await textbox.inputValue(), /\n/);
    const beforeIme = state.calls;
    await textbox.evaluate((node) => node.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, isComposing: true })));
    assert.equal(state.calls, beforeIme, "Chinese composition Enter must not submit");
    await textbox.evaluate((node) => node.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229, bubbles: true })));
    assert.equal(state.calls, beforeIme, "Safari composition Enter must not submit");
    const submittedText = (await textbox.inputValue()).trim();
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText("助教正在思考…", { exact: true }).waitFor();
    assert.equal(await textbox.inputValue(), "", "Sending must clear the composer before the response");
    assert.equal(await page.locator(".user-message").last().textContent(), submittedText);
    assert.equal(await page.getByRole("button", { name: "下一题", exact: true }).isDisabled(), true);
    const composer = await page.locator(".chat-composer").boundingBox();
    assert.ok(composer.y + composer.height <= 1001, "Composer must remain within viewport");
    await waitFor(() => state.release !== null, "Tutor request was not sent");
    state.release(); state.release = null;
    await page.getByText("LLM 助教", { exact: true }).waitFor();
    assert.equal(await page.locator(".assistant-message img").count(), 0, "Generated content must be rendered as text");
    assert.equal(await textbox.inputValue(), "");
    await textbox.fill("超时"); await textbox.press("Enter");
    await waitFor(() => state.release !== null, "Fallback request was not sent"); state.release(); state.release = null;
    await page.getByText("助教响应超时，先为你提供课程提示。你可以重新提问。", { exact: true }).waitFor();
    assert.equal(await textbox.inputValue(), "", "A completed fallback reply must leave the composer empty");
    await textbox.fill("回看第 1 轮"); await textbox.press("Enter");
    await waitFor(() => state.release !== null, "History request was not sent"); state.release(); state.release = null;
    await page.getByText("本题第 1 轮对话", { exact: true }).waitFor();
    const failedDraft = "  网络失败  ";
    await textbox.fill(failedDraft); await textbox.press("Enter");
    await page.getByText("助教正在思考…", { exact: true }).waitFor();
    assert.equal(await textbox.inputValue(), "", "Keyboard submission must also clear the composer immediately");
    await waitFor(() => state.release !== null, "Failing request was not sent"); state.release(); state.release = null;
    await page.getByRole("alert").filter({ hasText: "辅导服务暂不可用" }).waitFor();
    assert.equal(await textbox.inputValue(), failedDraft, "A failed request must restore the original draft");
    await page.getByRole("tab", { name: /错题教练/ }).click();
    await page.getByText("该题暂无实验教练，可切换到普通助教继续提问。", { exact: true }).waitFor();
    await page.getByRole("tab", { name: /错题教练/ }).press("ArrowLeft");
    assert.equal(await page.getByRole("tab", { name: "对话辅导", exact: true }).getAttribute("aria-selected"), "true");
    await page.locator(".lab-disclosure > summary").click();
    await page.getByRole("textbox", { name: "你的判断", exact: true }).waitFor();
    await page.getByRole("button", { name: "换一组数据练练", exact: true }).click();
    const transfer = page.getByRole("region", { name: "迁移练习", exact: true });
    await transfer.getByRole("radio").first().check();
    await transfer.getByRole("button", { name: "提交迁移题", exact: true }).click();
    await transfer.getByText(/两个分组返回两行/).waitFor();
    assert.equal(state.history.length, 1);
    await page.getByRole("button", { name: /^学习记录/ }).click();
    await page.locator(".learning-memories > summary").click();
    await page.getByRole("button", { name: "修改", exact: true }).click();
    await page.getByRole("textbox", { name: "修改复习要点" }).fill("只保留确认过的复习要点。");
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.getByText("只保留确认过的复习要点。", { exact: true }).waitFor();
    await page.getByRole("button", { name: "删除", exact: true }).click();
    assert.equal(state.deletes, 0, "Deleting a note requires confirmation");
    await page.getByRole("button", { name: "取消", exact: true }).click();
    await page.getByRole("button", { name: "删除", exact: true }).click();
    await page.getByRole("button", { name: "确认删除", exact: true }).click();
    await page.getByText("还没有已确认的记录。", { exact: true }).waitFor();
    assert.equal(state.deletes, 1);
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("dialog").count(), 0);
    state.failNext = true;
    await page.getByRole("button", { name: "下一题", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "选题服务暂不可用" }).waitFor();
    assert.equal(await page.locator(".workspace-scroll").evaluate((node) => node.scrollTop), 0);
    assert.equal(state.history.length, 1, "Failed next request must not advance progress");
    await page.getByRole("button", { name: "下一题", exact: true }).click();
    await page.getByText("EpiKT 推荐", { exact: true }).waitFor();
    await page.locator("#practice-workspace").focus(); await page.keyboard.press("2");
    await page.getByRole("button", { name: "上一题", exact: true }).click();
    await page.getByText(/正在回看第 1 题/).waitFor();
    assert.equal(await page.getByRole("button", { name: "提交答案", exact: true }).count(), 0);
    assert.equal(await page.getByRole("textbox", { name: "你的问题", exact: true }).count(), 0);
    await page.getByRole("button", { name: "返回当前进度", exact: true }).click();
    assert.equal(await page.getByRole("region", { name: "当前题目" }).getByRole("radio").nth(1).isChecked(), true);
    for (const width of [1440, 1024, 820, 390, 320]) {
      await page.setViewportSize({ width, height: 850 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false, `No global horizontal overflow at ${width}px`);
      if (width <= 900) {
        await page.getByRole("navigation", { name: "切换学习面板" }).getByRole("button", { name: "助教", exact: true }).click();
        assert.equal(await page.locator(".workspace-scroll").isVisible(), false);
        assert.equal(await page.locator(".assistant-sidebar").isVisible(), true);
        if (width === 390 && screenshotDir) await page.screenshot({ path: path.join(screenshotDir, "ui-assistant-mobile.png") });
        await page.getByRole("button", { name: "返回练习", exact: true }).click();
        assert.equal(await page.locator(".workspace-scroll").isVisible(), true);
        if (width === 390 && screenshotDir) await page.screenshot({ path: path.join(screenshotDir, "ui-question-mobile.png") });
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole("button", { name: "提交答案", exact: true }).click();
    await page.getByText("回答正确，继续保持", { exact: true }).waitFor();
    assert.equal(await textbox.isDisabled(), true);
    await page.getByRole("button", { name: "下一题", exact: true }).click();
    await page.getByText("这一轮，完成了", { exact: true }).waitFor();
    await page.getByRole("button", { name: "回看上一题", exact: true }).click();
    await page.getByText(/正在回看第 2 题/).waitFor();
    await page.getByRole("button", { name: "返回当前进度", exact: true }).click();
    await page.getByText("这一轮，完成了", { exact: true }).waitFor();
    assert.deepEqual(pageErrors, []);
    const retryContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const retryState = await fixtures(retryContext);
    retryState.coachAvailable = true;
    const retryPage = await retryContext.newPage();
    await retryPage.goto(base);
    await retryPage.getByRole("button", { name: "开始练习", exact: true }).click();
    await retryPage.getByRole("radio").first().check();
    await retryPage.getByRole("button", { name: "提交答案", exact: true }).click();
    await retryPage.getByRole("tab", { name: /错题教练/ }).click();
    await retryPage.getByRole("button", { name: "带我弄懂这题", exact: true }).click();
    const coachInput = retryPage.getByRole("textbox", { name: "错题教练：你的疑问" });
    await coachInput.fill("请解释相同的两条查询为什么需要边界数据");
    await retryPage.getByRole("button", { name: "请教错题教练", exact: true }).click();
    await retryPage.getByRole("alert").filter({ hasText: "教练响应暂时中断" }).waitFor();
    const savedDraft = await coachInput.inputValue();
    await retryPage.getByRole("button", { name: "重试", exact: true }).click();
    await retryPage.getByText("已经保存的教练结论。", { exact: true }).waitFor();
    assert.equal(await coachInput.inputValue(), savedDraft);
    await retryPage.getByRole("button", { name: "请教错题教练", exact: true }).click();
    await waitFor(() => retryState.coachKeys.length === 2, "Expected retry request");
    assert.equal(retryState.coachKeys[0], retryState.coachKeys[1], "Lost response retry must reuse idempotency key");
    assert.equal(retryState.coachRuns.length, 1);
    await retryContext.close();
    console.log(JSON.stringify({ suite: "ui-redesign", backend: "mocked", passed: true,
      covered: ["welcome", "keyboard answer", "fixed right assistant", "IME", "pending", "fallback", "request error", "XSS rendering", "tabs", "diagnosis disclosure", "transfer", "memory edit/delete confirmation", "history/draft", "failed next recovery", "coach idempotent retry", "mobile 320-820", "desktop 1024-1440", "completion"] }));
    await context.close();
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
