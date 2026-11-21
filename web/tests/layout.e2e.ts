import { test } from "@e2e-dev/web";
import { expect } from "e2e";
import { installPublicRecipes } from "./fixtures/public-recipes";
import { CHAT_RUN_URL, chatRunRequest, fulfillChatRun } from "./fixtures/chat-run";

for (const viewport of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
  test(`three pages remain readable at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    await installPublicRecipes(browser);
    for (const page of ["catalog", "reading", "assistant"]) {
      await app.open(page === "catalog" ? "/" : "/?recipe=recipe-tomato");
      if (page === "assistant") await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
      await expect(browser.locator(".product-header")).toBeVisible();
      expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await app.screenshot(`${page}-${viewport.width}`);
    }
  });

  test(`long recipe stays usable at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    const fixture = await installPublicRecipes(browser);
    const recipe = fixture.recipes[0]!;
    recipe.ingredients = Array.from({ length: 15 }, (_, index) => ({ name: `备菜 ${index + 1}`, amount: String(index + 1), unit: "克", role: "main" }));
    recipe.ingredient_names = recipe.ingredients.map((ingredient) => ingredient.name);
    recipe.steps = Array.from({ length: 8 }, (_, index) => `依次备菜与下锅，第 ${index + 1} 步。核对食材后按原文制作。`);
    recipe.step_count = recipe.steps.length;
    await app.open("/?recipe=recipe-tomato");
    await expect(screen.getByRole("button", "打开陶陶对话")).toBeVisible();
    await expect(browser.locator(".ingredient-row")).toHaveCount(15);
    await expect(browser.locator(".step")).toHaveCount(8);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const position = await browser.evaluate(() => getComputedStyle(document.querySelector(".ingredients")!).position);
    expect(position).toBe(viewport.width > 900 ? "sticky" : "static");
    await app.screenshot(`long-recipe-${viewport.width}`);
    await browser.evaluate(() => { document.querySelector(".step:last-child")!.scrollIntoView({ block: "center" }); return null; });
    await screen.getByRole("button", /^专注第\s*8\s*步/).tap();
    await expect(browser.locator(".step-active-note")).toBeVisible();
    expect(await browser.evaluate(() => document.querySelector(".product-header")!.getBoundingClientRect().top)).toBe(0);
    await app.screenshot(`long-recipe-focused-${viewport.width}`);
  });
}

test("servings and inline questions share state across reading and conversation", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1366, height: 768 });
  await installPublicRecipes(browser);
  await app.open("/?recipe=recipe-tomato");
  await expect(screen.getByRole("button", "打开陶陶对话")).toBeVisible({ timeout: 2000 });
  const closedCanvas = await browser.evaluate(() => {
    const reading = document.querySelector(".recipe-page")!.getBoundingClientRect();
    return [reading.left, reading.width];
  });
  await screen.getByRole("button", "增加一人份").tap();
  await expect(screen.getByRole("checkbox", "鸡蛋 4.5个")).toBeVisible();
  await screen.getByRole("button", /^专注第\s*1\s*步/).tap();
  await expect(browser.locator(".step-active-note")).toBeVisible();
  await browser.locator(".step").first().getByRole("button", /^追问：/).tap();
  expect((await screen.getByLabel("想问的问题").inputValue()).length > 0).toBe(true);
  await expect(browser.locator(".recipe-context-bar")).toContainText("3 人份");
  await expect(browser.locator(".robot-launcher")).toHaveCount(0);
  expect(await browser.evaluate(() => {
    const reading = document.querySelector(".recipe-page")!.getBoundingClientRect();
    return [reading.left, reading.width];
  })).toEqual(closedCanvas);
  await expect(screen.getByRole("button", "展开到完整工作台")).toHaveCount(0);
  await screen.getByLabel("想问的问题").fill("这道菜有哪些食材？");
  let submitted: { message?: string; recipe_id?: string; recipe_version?: string; recipe_servings?: number } = {};
  await browser.route(CHAT_RUN_URL, async (route) => {
    submitted = chatRunRequest(route);
    await fulfillChatRun(route, {
      message: "这份食谱用到番茄和鸡蛋，另备原记录中的调味料。", session_id: "ui-preference-session", route: "knowledge-query"
    });
  });
  await screen.getByRole("button", "发送问题").tap();
  await expect(browser.locator(".assistant-message")).toContainText("番茄和鸡蛋");
  expect(submitted.message).toBe("这道菜有哪些食材？");
  expect(submitted.recipe_id).toBe("recipe-tomato");
  expect(submitted.recipe_version).toBe("a".repeat(64));
  expect(submitted.recipe_servings).toBe(3);
  await expect(browser.locator(".followups").getByRole("button", "这道菜有哪些食材？")).toHaveCount(0);
  await expect(browser.locator(".widget-panel")).toHaveCount(1);
  await app.screenshot("compact-first-answer");
  await browser.route(CHAT_RUN_URL, (route) => fulfillChatRun(route, {
    message: "还需要明确或补充这些条件：少油（低油用量偏好）", session_id: "ui-preference-session", route: "clarification",
    metadata: { plan: { unsupported_conditions: ["少油（低油用量偏好）"] } }
  }));
  await screen.getByLabel("想问的问题").fill("少油一点怎么做？");
  await screen.getByRole("button", "发送问题").tap();
  await expect(browser.locator(".assistant-message").last()).toContainText("资料还不足以确认");
  await browser.route(CHAT_RUN_URL, (route) => fulfillChatRun(route, {
    message: "请选择一个做法", session_id: "ui-preference-session", route: "clarification",
    metadata: { choices: [
      { id: "version-a", name: "番茄炒蛋", summary: { cook_time: "十分钟" } },
      { id: "version-b", name: "番茄炒蛋", summary: { cook_time: "十五分钟" } }
    ] }
  }));
  await screen.getByLabel("想问的问题").fill("有哪些做法？");
  await screen.getByRole("button", "发送问题").tap();
  await expect(screen.getByRole("button", "2. 番茄炒蛋 · 十五分钟")).toBeVisible();
  await screen.getByRole("button", "2. 番茄炒蛋 · 十五分钟").tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("第 2 份");
  expect(await browser.evaluate(() => document.querySelector(".send-button")!.getBoundingClientRect().bottom <= window.innerHeight)).toBe(true);
  await app.screenshot("conversation-choices");
  await browser.route(CHAT_RUN_URL, (route) => fulfillChatRun(route, {
    message: "先核对当前做法的食材与步骤。\n".repeat(20), session_id: "ui-preference-session", route: "knowledge-query"
  }));
  for (let turn = 0; turn < 3; turn++) {
    await screen.getByLabel("想问的问题").fill(`继续核对第 ${turn + 1} 个问题`);
    await screen.getByRole("button", "发送问题").tap();
    await expect(browser.locator(".assistant-message")).toHaveCount(turn + 4);
  }
  expect(await browser.evaluate(() => {
    const history = document.querySelector(".widget-history")!;
    return history.scrollHeight > history.clientHeight;
  })).toBe(true);
  expect(await browser.evaluate(() => [...document.querySelectorAll<HTMLButtonElement>(".clarification-options button")].every((button) => button.disabled))).toBe(true);
  expect(await browser.evaluate(() => document.querySelector(".send-button")!.getBoundingClientRect().bottom <= window.innerHeight)).toBe(true);
  await app.screenshot("long-conversation");
  await screen.getByLabel("想问的问题").fill("最后还要再放盐吗？");
  await screen.getByRole("button", "收起对话，保留草稿").tap();
  await expect(browser.locator(".step-active-note")).toHaveText("正在做这一步");
  await screen.getByRole("button", "继续编辑未发送的问题").tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("最后还要再放盐吗？");
});

test("retired pages return to the catalog and the assistant stays in its floating panel", async ({ app, screen, browser }) => {
  await installPublicRecipes(browser);
  await app.open("/?page=technology");
  await expect(screen.getByRole("heading", "菜谱", { exact: true })).toBeVisible();
  await expect(screen.getByRole("link", "技术路线", { exact: true })).toHaveCount(0);
  await expect(screen.getByRole("link", "关于", { exact: true })).toHaveCount(0);
  await expect(screen.getByRole("link", "餐桌对话", { exact: true })).toHaveCount(0);
  await app.open("/?page=about");
  await expect(screen.getByRole("heading", "菜谱", { exact: true })).toBeVisible();
  await expect(screen.getByRole("heading", "关于陶陶", { exact: true })).toHaveCount(0);
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await expect(browser.locator(".widget-panel")).toBeVisible();
  await expect(screen.getByRole("button", "展开到完整工作台")).toHaveCount(0);
});
