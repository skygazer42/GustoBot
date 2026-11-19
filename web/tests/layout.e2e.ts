import { test } from "@e2e-dev/web";
import { expect } from "e2e";

for (const viewport of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
  test(`four pages remain readable at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    for (const page of ["reading", "workspace", "technology", "about"]) {
      await app.open(page === "reading" ? "/" : `/?page=${page}`);
      await expect(screen.getByRole("navigation", "主导航")).toBeVisible();
      expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await app.screenshot(`${page}-${viewport.width}`);
    }
  });

  test(`long recipe stays usable at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    await browser.route("**/src/data/recipe.ts*", async (route) => {
      const upstream = await route.fetch();
      const module = await upstream.text();
      await route.fulfill({ contentType: "text/javascript", body: `${module}\n
        recipe.ingredients.splice(0, recipe.ingredients.length, ...Array.from({ length: 15 }, (_, i) => ({
          ...recipe.ingredients[i % 2], id: 'long-ingredient-' + i, name: '备菜 ' + (i + 1), quantity: String(i + 1)
        })));
        recipe.steps.splice(0, recipe.steps.length, ...Array.from({ length: 8 }, (_, i) => ({
          ...recipe.steps[i % 2], id: 'long-step-' + i, title: '依次备菜与下锅 · 第 ' + (i + 1) + ' 步'
        })));
      ` });
    });
    await app.open("/");
    await expect(screen.getByRole("button", "打开陶陶对话")).toBeVisible();
    await expect(browser.locator(".ingredient-row")).toHaveCount(15);
    await expect(browser.locator(".step")).toHaveCount(8);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const position = await browser.evaluate(() => getComputedStyle(document.querySelector(".ingredients")!).position);
    expect(position).toBe(viewport.width > 900 ? "sticky" : "static");
    await app.screenshot(`long-recipe-${viewport.width}`);
    await browser.evaluate(() => { document.querySelector(".step:last-child")!.scrollIntoView({ block: "center" }); return null; });
    await screen.getByRole("button", "专注第 8 步：依次备菜与下锅 · 第 8 步").tap();
    await expect(browser.locator(".step-active-note")).toBeVisible();
    expect(await browser.evaluate(() => document.querySelector(".product-header")!.getBoundingClientRect().top)).toBe(0);
    await app.screenshot(`long-recipe-focused-${viewport.width}`);
  });
}

test("servings and inline questions share state across reading and conversation", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1366, height: 768 });
  await app.open("/");
  await expect(screen.getByRole("button", "打开陶陶对话")).toBeVisible({ timeout: 2000 });
  const closedCanvas = await browser.evaluate(() => {
    const reading = document.querySelector(".recipe-page")!.getBoundingClientRect();
    return [reading.left, reading.width];
  });
  await screen.getByRole("button", "增加一人份").tap();
  await expect(screen.getByRole("checkbox", "鸡蛋 4.5个")).toBeVisible();
  await screen.getByRole("button", "专注第 1 步：先炒鸡蛋，留一点嫩").tap();
  await expect(browser.locator(".step-active-note")).toBeVisible();
  await browser.locator(".step").first().getByRole("button", "追问：怎么判断鸡蛋刚凝固？").tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("怎么判断鸡蛋刚凝固？");
  await expect(browser.locator(".recipe-context-bar")).toContainText("当前食谱 · 3 人份");
  await expect(browser.locator(".robot-launcher")).toHaveCount(0);
  expect(await browser.evaluate(() => {
    const reading = document.querySelector(".recipe-page")!.getBoundingClientRect();
    return [reading.left, reading.width];
  })).toEqual(closedCanvas);
  await screen.getByRole("button", "展开到完整工作台").tap();
  await expect(browser.locator(".paper-note .recipe-meta")).toContainText("3 人份");
  await screen.getByLabel("想问的问题").fill("这道菜有哪些食材？");
  let submittedMessage = "";
  await browser.route("**/api/v1/chat/", async (route) => {
    submittedMessage = (JSON.parse(route.request.postData!) as { message: string }).message;
    await route.fulfill({ json: {
      message: "这份食谱用到番茄和鸡蛋，另备原记录中的调味料。", session_id: "ui-preference-session", route: "knowledge-query"
    } });
  });
  await screen.getByRole("button", "发送问题").tap();
  await expect(browser.locator(".assistant-message")).toContainText("番茄和鸡蛋");
  expect(submittedMessage.includes("当前调整为3人份")).toBe(true);
  expect(submittedMessage.includes("鸡蛋4.5个")).toBe(true);
  await expect(browser.locator(".followups").getByRole("button", "这道菜有哪些食材？")).toHaveCount(0);
  await expect(browser.locator(".workspace-panel.is-compact")).toHaveCount(1);
  await app.screenshot("compact-first-answer");
  await browser.route("**/api/v1/chat/", (route) => route.fulfill({ json: {
    message: "还需要明确或补充这些条件：少油（低油用量偏好）", session_id: "ui-preference-session", route: "clarification",
    metadata: { plan: { unsupported_conditions: ["少油（低油用量偏好）"] } }
  } }));
  await screen.getByLabel("想问的问题").fill("少油一点怎么做？");
  await screen.getByRole("button", "发送问题").tap();
  await expect(browser.locator(".assistant-message").last()).toContainText("资料还不足以确认");
  await browser.route("**/api/v1/chat/", (route) => route.fulfill({ json: {
    message: "请选择一个做法", session_id: "ui-preference-session", route: "clarification",
    metadata: { choices: [
      { id: "version-a", name: "番茄炒蛋", summary: { cook_time: "十分钟" } },
      { id: "version-b", name: "番茄炒蛋", summary: { cook_time: "十五分钟" } }
    ] }
  } }));
  await screen.getByLabel("想问的问题").fill("有哪些做法？");
  await screen.getByRole("button", "发送问题").tap();
  await expect(screen.getByRole("button", "2. 番茄炒蛋 · 十五分钟")).toBeVisible();
  await screen.getByRole("button", "2. 番茄炒蛋 · 十五分钟").tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("第 2 份");
  await expect(browser.locator(".workspace-panel.is-compact")).toHaveCount(0);
  expect(await browser.evaluate(() => document.querySelector(".send-button")!.getBoundingClientRect().bottom <= window.innerHeight)).toBe(true);
  await app.screenshot("conversation-choices");
  await browser.route("**/api/v1/chat/", (route) => route.fulfill({ json: {
    message: "先核对当前做法的食材与步骤。\n".repeat(20), session_id: "ui-preference-session", route: "knowledge-query"
  } }));
  for (let turn = 0; turn < 3; turn++) {
    await screen.getByLabel("想问的问题").fill(`继续核对第 ${turn + 1} 个问题`);
    await screen.getByRole("button", "发送问题").tap();
    await expect(browser.locator(".assistant-message")).toHaveCount(turn + 4);
  }
  expect(await browser.evaluate(() => {
    const history = document.querySelector(".workspace-history")!;
    return history.scrollHeight > history.clientHeight;
  })).toBe(true);
  expect(await browser.evaluate(() => [...document.querySelectorAll<HTMLButtonElement>(".clarification-options button")].every((button) => button.disabled))).toBe(true);
  expect(await browser.evaluate(() => document.querySelector(".send-button")!.getBoundingClientRect().bottom <= window.innerHeight)).toBe(true);
  await app.screenshot("long-conversation");
  await screen.getByLabel("想问的问题").fill("最后还要再放盐吗？");
  await screen.getByRole("button", "返回食谱").tap();
  await expect(browser.locator(".step-active-note")).toHaveText("正在做这一步");
  await screen.getByRole("button", "继续编辑未发送的问题").tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("最后还要再放盐吗？");
});

test("technology paths reveal evidence and about leads back to the recipe", async ({ app, browser, screen }) => {
  await app.open("/?page=technology");
  await screen.getByRole("button", "文档检索", { exact: true }).tap();
  await expect(browser.locator(".architecture-answer")).toContainText("锅中油预热，放入蛋液");
  await screen.getByRole("button", "事实与关系", { exact: true }).tap();
  await expect(browser.locator(".architecture-answer")).toContainText("HAS_STEP");
  await app.screenshot("technology-selected-path");
  await screen.getByRole("navigation", "主导航").getByRole("link", "关于", { exact: true }).tap();
  await screen.getByRole("link", "翻开今天的食谱").tap();
  await expect(screen.getByRole("heading", "番茄炒蛋", { exact: true })).toBeVisible();
});
