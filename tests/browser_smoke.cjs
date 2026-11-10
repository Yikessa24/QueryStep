const assert = require("node:assert/strict");
const { chromium } = require("playwright");

async function smoke() {
  const baseUrl = process.env.QUERYSTEP_TEST_WEB_URL || "http://127.0.0.1:5173";
  const expectModel = process.env.QUERYSTEP_TEST_TUTOR_LLM === "1";
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(baseUrl);
    await page.getByRole("button", { name: "开始练习", exact: true }).click();
    const title = page.getByRole("heading", { level: 1 });
    await page.getByText("规则推荐", { exact: true }).waitFor();
    const firstTitle = await title.innerText();

    await page.getByRole("radio").nth(1).check();
    await page.getByRole("button", { name: "提交答案" }).click();
    const input = page.getByRole("textbox", { name: "你的问题" });
    await input.fill("我以为 SELECT 会返回所有列。");
    await page.getByRole("button", { name: "发送" }).click();
    const source = expectModel ? "LLM 助教" : "审核提示";
    await page.getByText(source, { exact: true }).first().waitFor();
    await input.fill("能给一个独立例子吗？");
    await page.getByRole("button", { name: "发送" }).click();
    await page.getByText(source, { exact: true }).nth(1).waitFor();
    if (expectModel) {
      await page.getByRole("link", { name: "课程规则" }).waitFor();
      await page.getByText("审核例题", { exact: true }).waitFor();
    }

    await page.reload();
    await page.getByText("能给一个独立例子吗？", { exact: false }).waitFor();
    assert.equal(await title.innerText(), firstTitle);
    const before = await (await context.request.get(baseUrl + "/api/practice/progress")).json();
    assert.equal(before.total, 1);
    assert.equal(before.last.turns.length, 2);
    await page.getByRole("button", { name: "查看选题记录" }).click();
    await page.getByText(/本轮实际题号/).waitFor();
    const other = await browser.newContext();
    await other.request.post(baseUrl + "/api/session", { data: {} });
    const replay = await other.request.get(
      baseUrl + "/api/practice/" + before.last.presentation.decision_id + "/replay",
    );
    assert.equal(replay.status(), 404);
    await other.close();

    await page.getByRole("button", { name: "下一题" }).click();
    await page.getByRole("button", { name: "提交答案" }).waitFor();
    assert.notEqual(await title.innerText(), firstTitle);
    await page.getByRole("radio").nth(1).check();
    await page.getByRole("button", { name: "提交答案" }).click();
    await page.getByText("回答正确。可以继续练习。", { exact: true }).waitFor();
    const after = await (await context.request.get(baseUrl + "/api/practice/progress")).json();
    assert.equal(after.total, 2);
    assert.equal(after.correct, 1);
    assert.deepEqual(errors, []);
    console.log("Browser smoke passed: start, grade, tutor twice, reload, isolation, replay and next.");
  } finally {
    await browser.close();
  }
}

smoke().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
