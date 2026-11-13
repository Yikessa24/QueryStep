const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const question = "为什么分组后还要检查 HAVING？请用严格大于 1 的示例。";

async function openWrongAnswer(page, url) {
  await page.goto(url);
  await page.getByRole("button", { name: "开始练习" }).click();
  for (const [index, option] of [1, 0, 0, 0].entries()) {
    await page.getByRole("button", { name: "提交答案" }).waitFor();
    await page.getByText(index === 3 ? "EpiKT 推荐" : "规则推荐", { exact: true }).waitFor();
    await page.getByRole("radio").nth(option).check();
    await page.getByRole("button", { name: "提交答案" }).click();
    await page.getByRole("button", { name: "下一题" }).waitFor();
    if (index < 3) await page.getByRole("button", { name: "下一题" }).click();
  }
  await page.getByRole("textbox", { name: "你的判断" }).waitFor();
}

async function timeEvidence(page) {
  await page.getByRole("textbox", { name: "你的判断" }).fill(question);
  await page.getByRole("button", { name: "运行诊断" }).click();
  const start = await page.evaluate(() => performance.getEntriesByName("diagnosis-click").at(-1).startTime);
  await page.getByText("被筛除的分组：D", { exact: true }).waitFor();
  await page.getByRole("link", { name: "HAVING 筛选分组", exact: true }).waitFor();
  return Math.round(await page.evaluate(() => performance.now()) - start);
}

async function benchmark(browser, url) {
  const samples = Number(process.env.QUERYSTEP_TEST_BENCHMARK_SAMPLES);
  const concurrency = Number(process.env.QUERYSTEP_TEST_CONCURRENCY || 1);
  const values = [];
  for (let batch = 0; batch < samples; batch += concurrency) {
    const pages = await Promise.all(Array.from({ length: Math.min(concurrency, samples - batch) }, () => browser.newPage()));
    try {
      for (const page of pages) {
        await openWrongAnswer(page, url);
        await page.getByRole("button", { name: "运行诊断" }).evaluate((button) => {
          button.addEventListener("click", () => performance.mark("diagnosis-click"));
        });
      }
      values.push(...await Promise.all(pages.map(timeEvidence)));
    } finally {
      await Promise.all(pages.map((page) => page.close()));
    }
  }
  const sorted = values.toSorted((a, b) => a - b);
  const percentile = (p) => {
    const index = (sorted.length - 1) * p;
    return Math.round(sorted[Math.floor(index)] * (1 - index % 1) + sorted[Math.ceil(index)] * (index % 1));
  };
  console.log(JSON.stringify({ samples, concurrency, elapsed_ms: values, p50_ms: percentile(.5), p95_ms: percentile(.95) }));
}

async function main() {
  const url = process.env.QUERYSTEP_TEST_WEB_URL || "http://127.0.0.1:5173";
  const browser = await chromium.launch();
  try {
    if (process.env.QUERYSTEP_TEST_BENCHMARK_SAMPLES) {
      await benchmark(browser, url);
      return;
    }
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const health = await (await page.request.get(`${url}/healthz`)).json();
    assert.equal(health.epikt_ready, true);
    assert.equal(health.diagnostics_ready, true);
    await openWrongAnswer(page, url);
    await page.getByRole("button", { name: "查看选题记录" }).click();
    await page.getByText(/本轮实际题号 75.*规则对照题号 69/).waitFor();
    await page.getByRole("textbox", { name: "你的判断" }).fill(question);
    const started = page.waitForResponse((response) => response.request().method() === "POST" &&
      response.url().endsWith("/diagnosis"));
    await page.getByRole("button", { name: "运行诊断" }).click();
    const queued = await (await started).json();
    assert.ok(queued.run_id);
    await page.getByText(/^诊断完成(，学习记录待确认。)?$/).waitFor({ timeout: 48000 });
    const run = await (await page.request.get(`${url}/api/diagnosis/${queued.run_id}`)).json();
    if (run.result.mode !== "full" && process.env.QUERYSTEP_TEST_ALLOW_PARTIAL === "1") {
      assert.equal(run.result.mode, "partial");
      await page.getByText("本轮仅展示已取得的证据或课程提示。", { exact: true }).waitFor();
      await page.getByRole("button", { name: "比较结果" }).click();
      await page.getByText("两次查询未移除任何结果键。", { exact: true }).last().waitFor();
      assert.equal((await (await page.request.get(`${url}/api/practice/progress`)).json()).total, 4);
      assert.deepEqual(errors, []);
      console.log("Browser: partial diagnosis, parameter experiment, and unchanged grading ledger.");
      return;
    }
    assert.equal(run.result.mode, "full", JSON.stringify(run.result.branch_failures));
    assert.equal(run.result.comparison.before_row_count, 4);
    assert.equal(run.result.comparison.after_row_count, 3);
    assert.deepEqual(run.result.comparison.removed_keys, ["D"]);
    assert.equal(run.result.model_calls, 0);
    assert.ok(run.result.trace.course.some((event) => event.tool === "search_course_notes"));
    assert.ok(run.result.trace.experiment.some((event) => event.tool === "compare_example_results"));
    await page.getByRole("link", { name: "HAVING 筛选分组", exact: true }).waitFor();
    await page.getByText("被筛除的分组：D", { exact: true }).waitFor();
    if (process.env.QUERYSTEP_TEST_REQUIRE_EXPLANATION === "1") {
      assert.equal(run.result.explanation.status, "pending");
      await page.getByRole("region", { name: "Gemini 补充讲解" }).waitFor({ timeout: 6500 });
      const explained = await (await page.request.get(`${url}/api/diagnosis/${queued.run_id}`)).json();
      assert.equal(explained.result.explanation.status, "ready");
      assert.deepEqual(explained.result.comparison, run.result.comparison);
      console.log(`Browser: Gemini explanation ready in ${explained.result.explanation.elapsed_ms} ms after SQL evidence.`);
    }
    await page.reload();
    await page.getByText("诊断完成，学习记录待确认。", { exact: true }).waitFor();
    await page.getByRole("button", { name: "比较结果" }).click();
    await page.getByText("两次查询未移除任何结果键。", { exact: true }).waitFor();
    const transfer = page.getByRole("region", { name: "迁移练习" });
    await transfer.getByRole("button", { name: "换一组数据练练" }).click();
    await transfer.getByRole("radio", { name: "河西和城南", exact: true }).check();
    await transfer.getByRole("button", { name: "提交迁移题" }).click();
    await transfer.getByText(/答对了。河西有 2 条借阅/).waitFor();
    await page.reload();
    await transfer.getByText(/答对了。河西有 2 条借阅/).waitFor();
    await page.getByRole("button", { name: "确认保存" }).click();
    await page.getByText("学习记录已保存。", { exact: true }).waitFor();
    await page.getByText("已确认的学习记录", { exact: true }).click();
    await page.getByText("复习 GROUP BY 得到分组后，怎样用 HAVING 筛选各组。", { exact: true }).waitFor();
    const progress = await (await page.request.get(`${url}/api/practice/progress`)).json();
    assert.equal(progress.total, 4);
    await page.getByRole("button", { name: "下一题" }).click();
    await page.getByRole("button", { name: "提交答案" }).waitFor();
    await page.getByRole("radio").first().check();
    await page.getByRole("button", { name: "提交答案" }).click();
    let reply;
    for (let attempt = 0; attempt < 2; attempt++) {
      const recalled = page.waitForResponse((response) => response.request().method() === "POST" &&
        response.url().endsWith("/tutor"), { timeout: 45000 });
      await page.getByRole("textbox", { name: "你的问题" }).fill("请调用 retrieve_course_notes，再给一句简短的 GROUP BY 提示。");
      await page.getByRole("button", { name: "发送" }).click();
      reply = await (await recalled).json();
      if (reply.source === "llm" || reply.fallback_reason !== "llm_timeout" || !health.tutor_ready) break;
      if (attempt === 0) console.log("Browser: next-item tutor timed out; retrying once.");
    }
    if (reply.source === "llm") {
      assert.equal(reply.memory_ids.length, 1);
      await page.getByText("本轮辅导读取了已确认的学习记录", { exact: true }).waitFor();
      console.log("Browser: Gemini recalled the confirmed note on the next related item.");
    } else {
      assert.equal(reply.source, "template");
      assert.ok(reply.fallback_reason);
      assert.ok(reply.text);
      console.log(`Browser: next-item tutor returned a reviewed hint (${reply.fallback_reason}).`);
    }
    assert.deepEqual(errors, []);
    console.log("Browser: EpiKT 75 vs rule 69, MCP 4→3, transfer submission, reload, and saved memory.");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
