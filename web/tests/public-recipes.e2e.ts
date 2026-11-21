import { test } from "@e2e-dev/web";
import { expect } from "e2e";
import { installPublicRecipes } from "./fixtures/public-recipes";
import { CHAT_RUN_URL, fulfillChatRun } from "./fixtures/chat-run";

test("the public homepage lists backend recipes and opens distinct saved dishes", async ({ app, browser, screen }) => {
  await installPublicRecipes(browser);
  await app.open("/");
  await expect(screen.getByRole("heading", "菜谱", { exact: true })).toBeVisible();
  await expect(screen.getByRole("link", "查看做法：番茄炒蛋", { exact: true })).toBeVisible();
  await screen.getByRole("link", "查看做法：青菜汤面", { exact: true }).tap();
  await expect(screen.getByRole("heading", "青菜汤面", { exact: true })).toBeVisible();
  await expect(browser.locator(".recipe-page")).toContainText("将面条放入沸水中煮熟。");
  await expect(browser.locator(".recipe-page")).toContainText("原作者未注明人数");
  await expect(screen.getByRole("button", "增加一人份", { exact: true })).toHaveCount(0);
});

test("search, category, paging and recipe return preserve the catalog URL", async ({ app, browser, screen }) => {
  await installPublicRecipes(browser);
  await app.open("/");
  await expect(browser.locator(".recipe-card")).toHaveCount(12);
  await screen.getByRole("button", "下一页菜谱", { exact: true }).tap();
  await expect(browser.locator(".recipe-card")).toHaveCount(2);
  expect(await browser.evaluate(() => new URLSearchParams(location.search).get("offset"))).toBe("12");
  await screen.getByRole("button", "上一页菜谱", { exact: true }).tap();
  await screen.getByLabel("搜索菜名或食材", { exact: true }).fill("青菜");
  await screen.getByRole("button", "找菜", { exact: true }).tap();
  await expect(browser.locator(".recipe-card")).toHaveCount(1);
  await screen.getByLabel("菜谱分类", { exact: true }).selectOption({ value: "主食" });
  await screen.getByRole("link", "查看做法：青菜汤面", { exact: true }).tap();
  await expect(screen.getByRole("heading", "青菜汤面", { exact: true })).toBeVisible();
  expect(await browser.evaluate(() => {
    const query = new URLSearchParams(location.search);
    return [query.get("q"), query.get("category"), query.get("recipe")];
  })).toEqual(["青菜", "主食", "recipe-noodles"]);
  const detailUrl = await browser.evaluate(() => location.pathname + location.search);
  await app.open(detailUrl);
  await expect(screen.getByRole("heading", "青菜汤面", { exact: true })).toBeVisible();
  await screen.getByRole("link", "返回菜谱目录", { exact: true }).tap();
  await expect(browser.locator(".recipe-card")).toHaveCount(1);
  await expect(screen.getByLabel("搜索菜名或食材", { exact: true })).toHaveValue("青菜");
  await screen.getByRole("button", "清除筛选", { exact: true }).tap();
  await expect(browser.locator(".recipe-card")).toHaveCount(12);
});

test("catalog errors, a real empty catalog and no matches have distinct recovery", async ({ app, browser, screen }) => {
  const fixture = await installPublicRecipes(browser);
  fixture.catalogFailed = true;
  await app.open("/");
  await expect(screen.getByRole("heading", "菜谱暂时无法加载", { exact: true })).toBeVisible();
  await expect(browser.locator(".recipe-card")).toHaveCount(0);
  fixture.catalogFailed = false;
  await screen.getByRole("button", "重试菜谱目录", { exact: true }).tap();
  await expect(browser.locator(".recipe-card")).toHaveCount(12);
  await screen.getByLabel("搜索菜名或食材", { exact: true }).fill("没有这道菜");
  await screen.getByRole("button", "找菜", { exact: true }).tap();
  await expect(screen.getByRole("heading", "没有找到菜谱", { exact: true })).toBeVisible();
  await screen.getByRole("button", "清除筛选", { exact: true }).first().tap();
  await expect(browser.locator(".recipe-card")).toHaveCount(12);
  fixture.recipes.splice(0);
  await app.open("/");
  await expect(screen.getByRole("heading", "还没有菜谱", { exact: true })).toBeVisible();
  await expect(browser.locator(".recipe-card")).toHaveCount(0);
});

test("detail failures and unknown recipes never fall back to a saved tomato dish", async ({ app, browser, screen }) => {
  const fixture = await installPublicRecipes(browser);
  fixture.detailFailures.add("recipe-noodles");
  await app.open("/?recipe=recipe-noodles");
  await expect(screen.getByRole("button", "重试读取菜谱", { exact: true })).toBeVisible();
  await expect(browser.locator(".recipe-page")).toHaveCount(0);
  fixture.detailFailures.clear();
  await screen.getByRole("button", "重试读取菜谱", { exact: true }).tap();
  await expect(screen.getByRole("heading", "青菜汤面", { exact: true })).toBeVisible();
  await app.open("/?recipe=missing");
  await expect(browser.locator(".recipe-page")).toHaveCount(0);
  await expect(screen.getByRole("heading", "番茄炒蛋", { exact: true })).toHaveCount(0);
  await expect(screen.getByRole("link", "返回菜谱目录", { exact: true })).toBeVisible();
});

test("selected recipe questions send only the question and exact recipe reference", async ({ app, browser, screen }) => {
  const fixture = await installPublicRecipes(browser);
  fixture.recipes[0]!.steps = Array.from({ length: 30 }, (_, index) => `第${index + 1}处原文。${"按原文准备食材，检查火候并继续制作。".repeat(20)}`);
  fixture.recipes[0]!.step_count = 30;
  await app.open("/?page=workspace&recipe=recipe-tomato");
  await expect(screen.getByLabel("想问的问题")).toBeVisible();
  await expect(screen.getByLabel("上传文件", { exact: true })).toHaveCount(0);
  await screen.getByLabel("想问的问题").fill("最后一步需要注意什么？");
  await screen.getByRole("button", "发送问题", { exact: true }).tap();
  await expect(browser.locator(".assistant-message")).toContainText("《番茄炒蛋》");
  expect(fixture.chatRequests[0]).toEqual({ message: "最后一步需要注意什么？", stream: false, recipe_id: "recipe-tomato", recipe_version: "a".repeat(64), recipe_servings: 2 });
  await browser.locator(".message-sources summary").tap();
  await expect(browser.locator(".message-sources")).toContainText("番茄炒蛋");
});

test("recipe preferences and unsent questions belong to their own dishes", async ({ app, browser, screen }) => {
  const fixture = await installPublicRecipes(browser);
  await app.open("/?recipe=recipe-tomato");
  await screen.getByRole("button", "增加一人份", { exact: true }).tap();
  await screen.getByRole("checkbox", "鸡蛋 4.5个", { exact: true }).tap();
  await screen.getByRole("button", /^专注第\s*1\s*步/).tap();
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await screen.getByLabel("想问的问题").fill("鸡蛋还要炒多久？");
  await screen.getByRole("button", "发送问题", { exact: true }).tap();
  await expect(browser.locator(".assistant-message")).toHaveCount(1);
  await screen.getByLabel("想问的问题").fill("炒蛋的未发送问题");
  await screen.getByRole("button", "收起对话，保留草稿", { exact: true }).tap();
  await screen.getByRole("link", "返回菜谱目录", { exact: true }).tap();
  await screen.getByRole("link", "查看做法：青菜汤面", { exact: true }).tap();
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("");
  await expect(browser.locator(".assistant-message")).toHaveCount(0);
  await screen.getByLabel("想问的问题").fill("汤面要煮多久？");
  await screen.getByRole("button", "发送问题", { exact: true }).tap();
  await expect(browser.locator(".assistant-message")).toContainText("青菜汤面");
  expect(fixture.chatRequests[1]!.recipe_id).toBe("recipe-noodles");
  expect(fixture.chatRequests[1]!.session_id).toBeUndefined();
  expect(fixture.chatRequests[1]!.recipe_servings).toBeUndefined();
  await screen.getByLabel("想问的问题").fill("汤面的未发送问题");
  await screen.getByRole("button", "收起对话，保留草稿", { exact: true }).tap();
  await screen.getByRole("link", "返回菜谱目录", { exact: true }).tap();
  await screen.getByRole("link", "查看做法：番茄炒蛋", { exact: true }).tap();
  await expect(screen.getByRole("checkbox", "鸡蛋 4.5个", { exact: true })).toBeChecked();
  await expect(browser.locator(".step-active-note")).toBeVisible();
  await screen.getByRole("button", "继续编辑未发送的问题", { exact: true }).tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("炒蛋的未发送问题");
  await expect(browser.locator(".assistant-message")).toHaveCount(0);
});

test("an aborted reply from another dish cannot replace the current conversation", async ({ app, browser, screen }) => {
  await installPublicRecipes(browser);
  let releaseReply!: () => void;
  const replyGate = new Promise<void>((resolve) => { releaseReply = resolve; });
  let sent = false;
  await browser.route(CHAT_RUN_URL, async (route) => {
    sent = true;
    await replyGate;
    await fulfillChatRun(route, { message: "旧炒蛋回复", session_id: "old-tomato", route: "recipe-query" });
  });
  await app.open("/?recipe=recipe-tomato");
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await screen.getByLabel("想问的问题").fill("先问炒蛋");
  await screen.getByRole("button", "发送问题", { exact: true }).tap();
  await expect(screen.getByRole("button", "正在处理，请稍候", { exact: true })).toBeDisabled();
  expect(sent).toBe(true);
  await screen.getByRole("button", "收起对话，保留草稿", { exact: true }).tap();
  await screen.getByRole("link", "返回菜谱目录", { exact: true }).tap();
  await screen.getByRole("link", "查看做法：青菜汤面", { exact: true }).tap();
  releaseReply();
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await expect(browser.locator(".assistant-message")).toHaveCount(0);
  await expect(screen.getByLabel("想问的问题")).toHaveValue("");
});

test("a late detail cannot overwrite the recipe selected after returning to the catalog", async ({ app, browser, screen }) => {
  const fixture = await installPublicRecipes(browser);
  let releaseDetail!: () => void;
  fixture.detailGates.set("recipe-tomato", new Promise<void>((resolve) => { releaseDetail = resolve; }));
  try {
    await app.open("/");
    await screen.getByRole("link", "查看做法：番茄炒蛋", { exact: true }).tap();
    await expect(screen.getByRole("heading", "正在翻开这份菜谱…", { exact: true })).toBeVisible();
    await screen.getByRole("link", "返回菜谱目录", { exact: true }).tap();
    await screen.getByRole("link", "查看做法：青菜汤面", { exact: true }).tap();
    await expect(screen.getByRole("heading", "青菜汤面", { exact: true })).toBeVisible();
    releaseDetail();
    await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
    await expect(browser.locator(".recipe-context-bar")).toContainText("青菜汤面");
    await expect(screen.getByRole("heading", "番茄炒蛋", { exact: true })).toHaveCount(0);
  } finally {
    releaseDetail();
  }
});

test("the floating assistant and a catalog round trip preserve the long recipe reading position", async ({ app, browser, screen }) => {
  const fixture = await installPublicRecipes(browser);
  fixture.recipes[0]!.steps = Array.from({ length: 18 }, (_, index) => `第 ${index + 1} 处做法。${"按原文核对食材后继续操作。".repeat(8)}`);
  fixture.recipes[0]!.step_count = 18;
  await browser.setViewport({ width: 1366, height: 768 });
  await app.open("/?recipe=recipe-tomato");
  await expect(browser.locator(".step")).toHaveCount(18);
  await browser.evaluate(() => { document.querySelector(".step:last-child")!.scrollIntoView({ block: "center" }); return null; });
  const readingY = await browser.evaluate(() => scrollY);
  expect(readingY > 500).toBe(true);
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await screen.getByLabel("想问的问题").fill("长做法的未发送问题");
  await screen.getByRole("button", "收起对话，保留草稿", { exact: true }).tap();
  expect(await browser.evaluate(() => scrollY)).toBe(readingY);
  await screen.getByRole("link", "陶陶，餐桌手记", { exact: true }).tap();
  await screen.getByRole("link", "查看做法：番茄炒蛋", { exact: true }).tap();
  await expect(browser.locator(".step")).toHaveCount(18);
  expect(await browser.evaluate(() => scrollY)).toBe(readingY);
});

test("the catalog assistant and selected-recipe assistant keep their contexts and drafts separate", async ({ app, browser, screen }) => {
  const fixture = await installPublicRecipes(browser);
  await app.open("/");
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await expect(screen.getByLabel("上传文件", { exact: true })).toBeVisible();
  await screen.getByLabel("想问的问题").fill("想找一些做法");
  await screen.getByRole("button", "发送问题", { exact: true }).tap();
  await expect(browser.locator(".assistant-message")).toHaveCount(1);
  expect(fixture.chatRequests[0]!.recipe_id).toBeUndefined();
  await screen.getByLabel("想问的问题").fill("目录的未发送问题");
  await screen.getByRole("button", "收起对话，保留草稿", { exact: true }).tap();
  await screen.getByRole("link", "查看做法：青菜汤面", { exact: true }).tap();
  await screen.getByRole("button", "打开陶陶对话", { exact: true }).tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("");
  await expect(screen.getByLabel("上传文件", { exact: true })).toHaveCount(0);
  await screen.getByLabel("想问的问题").fill("汤面资料怎么说？");
  await screen.getByRole("button", "发送问题", { exact: true }).tap();
  await expect(browser.locator(".assistant-message")).toContainText("青菜汤面");
  expect(fixture.chatRequests[1]!.recipe_id).toBe("recipe-noodles");
  expect(fixture.chatRequests[1]!.session_id).toBeUndefined();
  await screen.getByRole("button", "收起对话，保留草稿", { exact: true }).tap();
  await screen.getByRole("link", "返回菜谱目录", { exact: true }).tap();
  await screen.getByRole("button", "继续编辑未发送的问题", { exact: true }).tap();
  await expect(screen.getByLabel("想问的问题")).toHaveValue("目录的未发送问题");
  await expect(browser.locator(".assistant-message")).toHaveCount(0);
  await expect(screen.getByLabel("上传文件", { exact: true })).toBeVisible();
});

for (const width of [1366, 390]) {
  test(`catalog and unknown metadata remain readable at ${width} pixels`, async ({ app, browser, screen }) => {
    await installPublicRecipes(browser);
    await browser.setViewport({ width, height: width === 390 ? 844 : 768 });
    await app.open("/");
    await expect(browser.locator(".recipe-card")).toHaveCount(12);
    expect(await browser.evaluate(() => {
      const launcher = document.querySelector(".robot-launcher")!.getBoundingClientRect();
      return launcher.right <= innerWidth && launcher.bottom <= innerHeight && launcher.left > innerWidth - 100 && launcher.top > innerHeight - 120;
    })).toBe(true);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await browser.evaluate(() => document.querySelector(".recipe-card")!.getBoundingClientRect().top < innerHeight)).toBe(true);
    await app.screenshot(`catalog-${width}`);
    await screen.getByRole("link", "查看做法：青菜汤面", { exact: true }).tap();
    await expect(browser.locator(".recipe-meta")).toContainText("原作者未注明人数");
    await expect(browser.locator(".recipe-meta")).not.toContainText("15");
    await expect(browser.locator(".recipe-photo")).toHaveCount(0);
    await expect(screen.getByRole("checkbox", "青菜 用量未注明", { exact: true })).toBeVisible();
    const source = browser.locator(".recipe-page").getByRole("link", "查看菜谱原文", { exact: true });
    await expect(source).toHaveAttribute("href", "https://example.test/recipes/recipe-noodles");
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await app.screenshot(`unknown-metadata-${width}`);
    await browser.locator(".recipe-deck a[href='#steps-title']").tap();
    expect(await browser.evaluate(() => location.hash)).toBe("#steps-title");
    expect(await browser.evaluate(() => {
      return document.getElementById("steps-title")!.getBoundingClientRect().top >= document.querySelector(".product-header")!.getBoundingClientRect().bottom
        && document.getElementById("steps-title")!.getBoundingClientRect().top < innerHeight;
    })).toBe(true);
  });
}

test("real readonly catalog, selected detail and local images agree through the frontend proxy", async ({ app, browser, screen }) => {
  const response = await fetch("http://127.0.0.1:5174/api/v1/recipes?q=&category=&offset=0&limit=12");
  expect(response.status).toBe(200);
  const page = await response.json() as {
    total: number;
    items: { id: string; name: string; ingredient_names: string[]; cover_image: { url: string } | null }[];
  };
  expect(page.total > 1).toBe(true);
  expect(page.items.length).toBe(12);
  await app.open("/");
  await expect(browser.locator(".recipe-card")).toHaveCount(12);
  const first = page.items[0]!;
  await screen.getByRole("link", `查看做法：${first.name}`, { exact: true }).tap();
  await expect(screen.getByRole("heading", first.name, { exact: true })).toBeVisible();
  await expect(browser.locator(".ingredient-row")).toHaveCount(first.ingredient_names.length);
  await expect(browser.locator(".recipe-provenance")).toContainText("HowToCook");
  if (first.cover_image) {
    const image = await fetch(`http://127.0.0.1:5174${first.cover_image.url}`);
    expect(image.status).toBe(200);
    expect(image.headers.get("content-type")?.startsWith("image/")).toBe(true);
  }
  expect(await browser.evaluate(() => !document.querySelector(".recipe-photo") || (document.querySelector(".recipe-photo") as HTMLImageElement).naturalWidth > 0)).toBe(true);
  await app.screenshot("real-recipe-detail");
});
