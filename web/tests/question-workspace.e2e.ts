import { test } from "@e2e-dev/web";
import type { Browser, WebRoute } from "@e2e-dev/web";
import { expect } from "e2e";

const domain = {
  id: "process", name: "工艺知识空间", version: "process-1", description: "设备与工艺记录", interpretation_notes: [],
  classes: { Equipment: { label: "设备", description: "工艺设备", grain: "一台设备", properties: {} } },
  allowed_edges: {},
};
const question = "萃取釜的目标温度有原文记录吗？";
const expected = "工艺记录写明目标温度为0°C。";
const message = "工艺记录中写明，萃取釜的目标温度为0°C，仍需按具体批次核对。";

async function fulfill(route: WebRoute, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installQuestions(browser: Browser) {
  const state = { failed: false, status: "success", message, gate: null as Promise<void> | null, questions: [] as string[] };
  await browser.route("**/api/v1/admin/session", (route) => fulfill(route, { authenticated: false, configured: false }));
  await browser.route("**/api/v1/ontology/domain", (route) => fulfill(route, domain));
  await browser.route("**/api/v1/knowledge/query", async (route) => {
    const body = JSON.parse(route.request.postData!) as { question: string };
    state.questions.push(body.question);
    if (state.gate) await state.gate;
    if (state.failed) return fulfill(route, { detail: "检索服务暂时不可用，请稍后重试" }, 503);
    return fulfill(route, {
      message: state.message, route: "graph-query", route_logic: "核对实际工艺记录",
      sources: [{ source_id: "process-notes", name: "工艺记录.txt", uri: "工艺记录.txt" }],
      metadata: { status: state.status, model_calls: 0, route_logic: "已有记录检索" },
    });
  });
  return state;
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`question workspace presents inputs and returned evidence at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    const state = await installQuestions(browser);
    await app.open("/admin.html?view=test");
    await expect(screen.getByLabel("测试问题", { exact: true })).toBeVisible();
    await expect(screen.getByRole("button", "运行问答", { exact: true })).toBeDisabled();
    await expect(browser.locator(".test-answer")).toHaveCount(0);
    await app.screenshot(`question-empty-${viewport.width}`);
    await screen.getByLabel("测试问题", { exact: true }).fill(question);
    await screen.getByText("添加预期回答，人工对照", { exact: true }).tap();
    await screen.getByLabel("预期回答", { exact: true }).fill(expected);
    await screen.getByRole("button", "运行问答", { exact: true }).tap();
    await expect(browser.locator(".test-answer")).toHaveText(message);
    await expect(browser.locator(".expected-result")).toContainText(expected);
    await expect(browser.locator(".test-sources")).toContainText("工艺记录.txt");
    await expect(browser.locator(".test-result")).toContainText("大模型 0 次");
    await expect(browser.locator(".test-result header strong")).toHaveText("已返回回答");
    expect(state.questions).toEqual([question]);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await app.screenshot(`question-answer-${viewport.width}`);
    expect(await browser.evaluate(() => {
      const setup = document.querySelector(".question-setup")?.getBoundingClientRect();
      const output = document.querySelector(".question-output")?.getBoundingClientRect();
      if (!setup || !output) return false;
      return window.innerWidth > 1100
        ? setup.right < output.left && output.bottom <= window.innerHeight && setup.bottom <= window.innerHeight && output.right >= window.innerWidth - 40
        : setup.bottom <= output.top;
    })).toBe(true);
    if (viewport.width === 390) {
      await browser.evaluate(() => { document.querySelector(".question-output")?.scrollIntoView({ block: "start" }); return null; });
      await app.screenshot("question-mobile-reading");
    }
  });
}

test("running a question preserves its submitted snapshots while the draft changes", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  const state = await installQuestions(browser);
  let release!: () => void;
  state.gate = new Promise<void>((resolve) => { release = resolve; });
  await app.open("/admin.html?view=test");
  await screen.getByLabel("测试问题", { exact: true }).fill(question);
  await screen.getByText("添加预期回答，人工对照", { exact: true }).tap();
  await screen.getByLabel("预期回答", { exact: true }).fill(expected);
  await screen.getByRole("button", "运行问答", { exact: true }).tap();
  await expect(screen.getByRole("button", "正在查询…", { exact: true })).toBeDisabled();
  await app.screenshot("question-running");
  await screen.getByLabel("测试问题", { exact: true }).fill("下一批次的温度是多少？");
  await screen.getByLabel("预期回答", { exact: true }).fill("这段是尚未提交的新预期。");
  release();
  await expect(browser.locator(".test-answer")).toHaveText(message);
  await expect(browser.locator(".question-snapshot")).toContainText(question);
  await expect(browser.locator(".expected-result")).toContainText(expected);
  await expect(screen.getByLabel("测试问题", { exact: true })).toHaveValue("下一批次的温度是多少？");
  await expect(screen.getByLabel("预期回答", { exact: true })).toHaveValue("这段是尚未提交的新预期。");
});

test("request failures keep the draft, permit retry and identify a retained previous answer", async ({ app, browser, screen }) => {
  const state = await installQuestions(browser);
  state.failed = true;
  await app.open("/admin.html?view=test");
  await screen.getByLabel("测试问题", { exact: true }).fill(question);
  await screen.getByRole("button", "运行问答", { exact: true }).tap();
  await expect(screen.getByRole("alert")).toContainText("检索服务暂时不可用");
  await expect(screen.getByLabel("测试问题", { exact: true })).toHaveValue(question);
  await expect(browser.locator(".test-answer")).toHaveCount(0);
  await expect(screen.getByText("尚未运行问题，回答与来源将在这里显示。", { exact: true })).toHaveCount(0);
  await app.screenshot("question-first-failure");
  state.failed = false;
  await screen.getByRole("button", "运行问答", { exact: true }).tap();
  await expect(browser.locator(".test-answer")).toHaveText(message);
  state.failed = true;
  await screen.getByLabel("测试问题", { exact: true }).fill("另一份记录是什么？");
  await screen.getByRole("button", "运行问答", { exact: true }).tap();
  await expect(screen.getByRole("alert")).toContainText("检索服务暂时不可用");
  await expect(browser.locator(".question-output")).toContainText("下方保留上次返回的结果");
  await expect(browser.locator(".test-answer")).toHaveText(message);
  await expect(browser.locator(".question-snapshot")).toContainText(question);
  await app.screenshot("question-retained-result");
});

test("long answers keep returned sources and execution details reachable without claiming answer quality", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1366, height: 768 });
  const state = await installQuestions(browser);
  state.status = "needs_clarification";
  state.message = "请确认具体设备和批次，现有记录不足以唯一确定。\n\n".repeat(45);
  await app.open("/admin.html?view=test");
  await screen.getByLabel("测试问题", { exact: true }).fill(question);
  await screen.getByRole("button", "运行问答", { exact: true }).tap();
  await expect(browser.locator(".test-result header strong")).toHaveText("需要确认条件");
  expect(await browser.evaluate(() => {
    const body = document.querySelector(".question-output-body");
    return body !== null && body.scrollHeight > body.clientHeight;
  })).toBe(true);
  await screen.getByText("查看检索与执行明细", { exact: true }).tap();
  await expect(browser.locator(".test-trace pre")).toContainText('"model_calls": 0');
  await expect(browser.locator(".test-sources")).toContainText("工艺记录.txt");
  await app.screenshot("question-long-answer-trace");
});
