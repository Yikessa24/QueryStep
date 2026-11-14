const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const url = process.env.QUERYSTEP_TEST_WEB_URL || "http://127.0.0.1:5173";

async function verify(browser, answers, itemId, ruleId, question) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.goto(url);
    await page.getByRole("button", { name: "开始练习" }).click();
    for (const [index, option] of answers.entries()) {
      const submit = page.getByRole("button", { name: "提交答案" });
      await submit.waitFor();
      await page.getByRole("radio").nth(option).check();
      await submit.click();
      const next = page.getByRole("button", { name: "下一题" });
      await next.waitFor();
      if (index < answers.length - 1) await next.click();
    }
    await page.getByRole("button", { name: "查看选题记录" }).click();
    await page.getByText(new RegExp(`本轮实际题号 ${itemId}.*规则对照题号 ${ruleId}`)).waitFor();
    const panel = page.getByRole("region", { name: "自主错题教练" });
    await panel.getByRole("button", { name: "带我弄懂这题" }).click();
    await panel.getByRole("textbox").fill(question);
    const submit = page.waitForResponse((response) => response.request().method() === "POST" &&
      response.url().endsWith("/coach"));
    await panel.getByRole("button", { name: "请教错题教练" }).click();
    const submitted = await submit;
    assert.equal(submitted.status(), 202);
    const resultPath = submitted.url();
    await panel.getByText("两次查询结果相同。", { exact: false }).first().waitFor();
    await panel.getByText("两次查询结果不同。", { exact: false }).first().waitFor();
    await panel.getByRole("link", { name: "依据 1" }).waitFor();
    const saved = (await (await page.request.get(resultPath)).json()).runs.at(-1);
    assert.equal(saved.status, "complete");
    assert.equal(saved.result.status, "hint");
    assert.ok(saved.result.trace.some((step) => step.retrieval === "hybrid"));
    assert.deepEqual(saved.result.trace.filter((step) => "same" in step).map((step) => step.same), [true, false]);
    assert.equal((await (await page.request.get(`${url}/api/practice/progress`)).json()).total, answers.length);
    const other = await browser.newPage();
    try {
      await other.request.post(`${url}/api/session`);
      assert.equal((await other.request.get(resultPath)).status(), 404);
    } finally {
      await other.close();
    }
    await page.reload();
    await panel.getByRole("link", { name: "依据 1" }).waitFor();
    assert.deepEqual(errors, []);
    console.log(`Browser ${itemId} vs rule ${ruleId}: hybrid retrieval, same→different, refresh, isolation.`);
  } finally {
    await page.close();
  }
}

(async () => {
  const browser = await chromium.launch();
  try {
    await verify(browser, [0, 1, 0, 2, 0, 0], 81, 70,
      "查询课程规则，验证把右表状态条件从 ON 移到 WHERE 为什么可能少一行。");
    await verify(browser, [1, 0, 0, 0], 75, 69,
      "查找课程规则并执行对照，HAVING COUNT(*) >= 2 和 > 2 为什么有时结果一样？");
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
