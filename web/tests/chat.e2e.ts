import { test } from "@e2e-dev/web";
import { expect } from "e2e";
import { fileURLToPath } from "node:url";
import type { Browser } from "@e2e-dev/web";
import type { Screen } from "e2e";

async function selectRecipeVersion(payload: unknown, browser: Browser, screen: Screen): Promise<void> {
  const result = payload as { metadata?: { choices?: unknown[] } };
  if (!result.metadata?.choices?.length) return;
  await browser.locator(".clarification-options button").last().tap();
  const answer = browser.waitForResponse("**/api/v1/chat/", { timeout: 90_000 });
  await screen.getByRole("button", "发送问题").tap();
  expect((await answer).status).toBe(200);
}

test("real recipe question shows an answer and a source, then starts a new conversation", async ({ app, screen, browser }) => {
  await app.open("/?page=workspace");
  await expect(screen.getByRole("heading", "餐桌对话", { exact: true })).toBeVisible();
  await screen.getByRole("button", "这道菜有哪些食材？").tap();
  const response = browser.waitForResponse("**/api/v1/chat/");
  await screen.getByRole("button", "发送问题").tap();
  const result = await response;
  expect(result.status).toBe(200);
  await selectRecipeVersion(await result.json(), browser, screen);
  await expect(browser.locator(".assistant-message").last()).toContainText("鸡蛋");
  await expect(browser.locator(".message-sources")).toBeVisible();
  await app.screenshot("real-recipe-answer");
  await screen.getByRole("button", "新对话").tap();
  await expect(browser.locator(".assistant-message")).toHaveCount(0);
  await expect(screen.getByLabel("想问的问题")).toHaveValue("");
});

test("chat panel keeps a draft across collapse and supports a narrow viewport", async ({ app, screen, browser }) => {
  await browser.setViewport({ width: 390, height: 844 });
  await app.open("/");
  expect(await browser.evaluate(() => {
    const launcher = document.querySelector(".launcher-wrap")!.getBoundingClientRect();
    const ingredient = document.querySelector(".ingredient-row")!.getBoundingClientRect();
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
    const answered = browser.waitForResponse("**/api/v1/chat/");
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
  await app.open("/?page=workspace");
  await browser.route("**/api/v1/chat/", (request) => request.fulfill({ status: 503, json: { detail: "acceptance injected failure" } }));
  await screen.getByLabel("想问的问题").fill("番茄炒蛋怎么做？");
  await screen.getByRole("button", "发送问题").tap();
  await expect(browser.locator("#chat-error")).toContainText("请求出错");
  await expect(screen.getByLabel("想问的问题")).toHaveValue("番茄炒蛋怎么做？");
  await browser.unrouteAll();
  const answered = browser.waitForResponse("**/api/v1/chat/");
  await screen.getByRole("button", "发送问题").tap();
  const result = await answered;
  expect(result.status).toBe(200);
  await expect(browser.locator(".message-user")).toHaveCount(1);
  await selectRecipeVersion(await result.json(), browser, screen);
  await expect(browser.locator(".assistant-message").last()).toContainText("鸡蛋");
});
