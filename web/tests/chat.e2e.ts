import { test } from "@e2e-dev/web";
import { expect } from "e2e";
import { fileURLToPath } from "node:url";
import { installPublicRecipes } from "./fixtures/public-recipes";
import { CHAT_RUN_URL, fulfillChatRun } from "./fixtures/chat-run";

test("real recipe question shows an answer and a source, then starts a new conversation", async ({ app, screen, browser }) => {
  const catalog = await fetch("http://127.0.0.1:5174/api/v1/recipes?q=%E9%B8%A1%E8%9B%8B&limit=1");
  expect(catalog.status).toBe(200);
  const { items } = await catalog.json() as { items: { id: string; name: string }[] };
  expect(items.length).toBe(1);
  await app.open(`/?page=workspace&recipe=${encodeURIComponent(items[0]!.id)}`);
  await expect(screen.getByRole("heading", items[0]!.name, { exact: true })).toBeVisible();
  await expect(browser.locator(".widget-panel")).toBeVisible();
  await screen.getByRole("button", "这道菜有哪些食材？").tap();
  const response = browser.waitForResponse(CHAT_RUN_URL);
  await screen.getByRole("button", "发送问题").tap();
  const result = await response;
  expect(result.status).toBe(200);
  const frames = (await result.text()).split("\n").filter((line) => line.startsWith("data: "));
  const reply = JSON.parse(frames[frames.length - 1]!.slice(6)).result as { route: string; sources: { backend: string; recipe_id: string }[] };
  expect(reply.route).toBe("recipe-query");
  expect(reply.sources[0]!.backend).toBe("recipe-library");
  expect(reply.sources[0]!.recipe_id).toBe(items[0]!.id);
  await expect(browser.locator(".assistant-message").last()).toContainText("鸡蛋");
  await expect(browser.locator(".message-sources")).toBeVisible();
  await app.screenshot("real-recipe-answer");
  await screen.getByRole("button", "新对话").tap();
  await expect(browser.locator(".assistant-message")).toHaveCount(0);
  await expect(screen.getByLabel("想问的问题")).toHaveValue("");
});

test("chat panel keeps a draft across collapse and supports a narrow viewport", async ({ app, screen, browser }) => {
  await installPublicRecipes(browser);
  await browser.setViewport({ width: 390, height: 844 });
  await app.open("/?recipe=recipe-tomato");
  await expect(browser.locator(".ingredient-row")).toHaveCount(2);
  expect(await browser.evaluate(() => {
    const launcher = document.querySelector(".launcher-wrap")!.getBoundingClientRect();
    const ingredient = document.querySelector(".ingredient-row input[type='checkbox']")!.getBoundingClientRect();
    return launcher.bottom <= ingredient.top || launcher.top >= ingredient.bottom || launcher.right <= ingredient.left || launcher.left >= ingredient.right;
  })).toBe(true);
  await screen.getByRole("button", "打开陶陶对话").tap();
  await screen.getByLabel("想问的问题").fill("我的问题草稿");
  await screen.getByRole("button", "收起对话，保留草稿").tap();
  await screen.getByRole("button", "继续编辑未发送的问题").tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("我的问题草稿");
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await app.screenshot("mobile-draft");
});

test("uploaded attachment is read through the real chat API", async ({ app, screen, browser }) => {
  await app.open("/?page=workspace");
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  let assetId: string | undefined;
  try {
    const uploaded = browser.waitForResponse("**/api/v1/upload/file");
    await screen.getByLabel("上传文件").setInputFiles([fileURLToPath(new URL("./fixtures/acceptance.txt", import.meta.url))]);
    const uploadResponse = await uploaded;
    expect(uploadResponse.status).toBe(200);
    const asset = await uploadResponse.json() as { asset_id: string };
    assetId = asset.asset_id;
    await expect(screen.getByRole("status")).toHaveText("已上传：acceptance.txt");
    await screen.getByLabel("想问的问题").fill("附件中的校验码是什么？");
    const answered = browser.waitForResponse(CHAT_RUN_URL);
    await screen.getByRole("button", "发送问题").tap();
    const response = await answered;
    expect(response.status).toBe(200);
    await expect(browser.locator(".assistant-message")).toContainText("QY-719");
    await app.screenshot("real-attachment-answer");
  } finally {
    if (assetId) {
      const removed = await fetch(`http://127.0.0.1:5174/api/v1/upload/${assetId}`, { method: "DELETE" });
      expect(removed.status).toBe(200);
    }
  }
});

test("a failed send preserves the question and a retry does not duplicate it", async ({ app, screen, browser }) => {
  await installPublicRecipes(browser);
  await app.open("/?page=workspace");
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await browser.route(CHAT_RUN_URL, (request) => request.fulfill({ status: 503, json: { detail: "acceptance injected failure" } }));
  await screen.getByLabel("想问的问题").fill("番茄炒蛋怎么做？");
  await screen.getByRole("button", "发送问题").tap();
  await expect(browser.locator("#chat-error")).toContainText("请求出错");
  await expect(screen.getByLabel("想问的问题")).toHaveValue("番茄炒蛋怎么做？");
  await browser.route(CHAT_RUN_URL, (route) => fulfillChatRun(route, {
    message: "番茄炒蛋使用番茄和鸡蛋。", session_id: "retry-session", route: "knowledge-query"
  }));
  const answered = browser.waitForResponse(CHAT_RUN_URL);
  await screen.getByRole("button", "发送问题").tap();
  const result = await answered;
  expect(result.status).toBe(200);
  await expect(browser.locator(".message-user")).toHaveCount(1);
  await expect(browser.locator(".assistant-message").last()).toContainText("鸡蛋");
});
