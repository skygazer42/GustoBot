import { test } from "@e2e-dev/web";
import type { Browser, WebRoute } from "@e2e-dev/web";
import { expect } from "e2e";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { FactResult, KnowledgeGraph, SourceSummary } from "../src/admin/contracts";

const domain = {
  id: "recipes", name: "验收菜谱空间", version: "test-1", description: "菜谱、做法与原文证据", interpretation_notes: [],
  classes: Object.fromEntries([["RecipeVariant", "具体做法"], ["Ingredient", "食材"], ["CookingStep", "步骤"]].map(([key, label]) => [key, { label, description: label, grain: "一项记录", properties: {} }])),
  allowed_edges: { HAS_MAIN_INGREDIENT: { domain: ["RecipeVariant"], range: ["Ingredient"], description: "做法使用主料", properties: {} } }
};
const sourceA: SourceSummary = { domain_id: "recipes", source_id: "ui-source-a", version: "v1", uri: "资料甲.txt", title: "资料甲.txt", kind: "document", status: "ready", ontology_version: "test-1", created_at: "2026-11-18T02:00:00", updated_at: "2026-11-18T02:00:00", chunks: 2, entities: null, relations: null, latest_job: null };
const sourceB: SourceSummary = { ...sourceA, source_id: "ui-source-b", uri: "资料乙.txt", title: "资料乙.txt" };
const text = "冰糖少许。红枣洗净后加入。";

async function fulfill(route: WebRoute, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installFixtures(browser: Browser) {
  const state = { sources: [sourceA, sourceB], catalogFailure: false, catalogGate: null as Promise<void> | null, factsFailure: false, uploadCalls: 0, ingestCalls: 0, failFirstIngest: false, deleteRequests: [] as string[], deleteVersions: [] as string[], deleteFailure: false, deleteConflict: false, deleteAfterRemovalFailure: false, extractCalls: 0, validateCalls: 0, saveCalls: 0, savedGraph: null as KnowledgeGraph | null, validatedGraph: null as KnowledgeGraph | null };
  const editing = { text, requests: [] as { source_id: string; version: string; title: string; text: string }[], failure: false, readGate: null as Promise<void> | null };
  await browser.route("**/api/v1/admin/session", (route) => fulfill(route, { authenticated: false, configured: false }));
  await browser.route("**/api/v1/ontology/domain", (route) => fulfill(route, domain));
  await browser.route("**/api/v1/knowledge/admin/**", async (route) => {
    const url = new URL(route.request.url);
    if (url.pathname.endsWith("/sources")) {
      if (state.catalogFailure) return fulfill(route, { detail: "目录暂时不可用" }, 503);
      if (state.catalogGate) await state.catalogGate;
      const q = url.searchParams.get("q") ?? "";
      const kind = url.searchParams.get("kind");
      const filter = url.searchParams.get("state") ?? "all";
      const matching = state.sources.filter((source) => source.title.includes(q) && (kind === "all" || source.kind === kind));
      const items = matching.filter((source) =>
        filter === "all" ||
        source.status === filter ||
        (filter === "ready" && source.status === "graph_ready"),
      );
      const stats = {
        total: matching.length,
        ready: matching.filter((source) => source.status === "ready" || source.status === "graph_ready").length,
        processing: matching.filter((source) => source.status === "processing").length,
        failed: matching.filter((source) => source.status === "failed").length,
        withdrawn: matching.filter((source) => source.status === "withdrawn").length,
        pending: matching.filter((source) => ["pending", "processing", "failed", "cancelled"].includes(source.status)).length
      };
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 6);
      return fulfill(route, { domain, items: items.slice(offset, offset + limit), total: items.length, offset, limit, stats });
    }
    if (url.pathname.endsWith("/document")) {
      const body = route.request.method === "PUT" ? JSON.parse(route.request.postData!) : null;
      const document = state.sources.find((item) => item.source_id === (body?.source_id ?? url.searchParams.get("source_id")));
      if (!document) return fulfill(route, { detail: "资料不存在" }, 404);
      if (body) {
        editing.requests.push(body);
        if (editing.failure) return fulfill(route, { detail: "版本冲突，请刷新后核对。" }, 409);
        editing.text = body.text;
        state.sources = state.sources.map((item) => item.source_id === document.source_id ? { ...item, title: body.title, version: "v2" } : item);
        return fulfill(route, { job_id: "edited-job", domain_id: "recipes", source_id: document.source_id, version: "v2", ontology_version: "test-1", kind: "document", status: "ready", error: null, details: {} });
      }
      if (editing.readGate) await editing.readGate;
      return fulfill(route, { source_id: document.source_id, version: document.version, revision: "a".repeat(64), title: document.title, text: editing.text });
    }
    const source = state.sources.find((item) => item.source_id === url.searchParams.get("source_id"));
    if (!source) return fulfill(route, { detail: "资料不存在" }, 404);
    if (url.pathname.endsWith("/source") && route.request.method === "DELETE") {
      if ([...url.searchParams.keys()].some((key) => key !== "source_id" && key !== "version") || !url.searchParams.has("version")) {
        return fulfill(route, { detail: "删除必须确认文档版本" }, 422);
      }
      if (url.searchParams.get("version") !== source.version) {
        return fulfill(route, { detail: "文档版本已更新，请刷新后再删除。" }, 409);
      }
      state.deleteRequests.push(source.source_id);
      state.deleteVersions.push(url.searchParams.get("version")!);
      if (state.deleteConflict) {
        state.deleteConflict = false;
        state.sources = state.sources.map((item) => item.source_id === source.source_id ? { ...item, version: "v2", title: "资料甲新版.txt" } : item);
        return fulfill(route, { detail: "文档版本已更新，请刷新后再删除。" }, 409);
      }
      if (state.deleteFailure) return fulfill(route, { detail: "文档暂时无法删除，请稍后重试。" }, 503);
      const versions = state.sources.filter((item) => item.source_id === source.source_id).length;
      state.sources = state.sources.filter((item) => item.source_id !== source.source_id);
      if (state.deleteAfterRemovalFailure) return fulfill(route, { detail: "删除结果暂时无法确认，请刷新核对。" }, 503);
      return fulfill(route, { source_id: source.source_id, versions });
    }
    if (url.searchParams.has("version") && url.searchParams.get("version") !== source.version) {
      return fulfill(route, { detail: "来源版本不存在" }, 404);
    }
    if (url.pathname.endsWith("/chunk")) {
      const number = Number(url.searchParams.get("number"));
      return fulfill(route, { number, total: 2, content: number === 1 ? `${source.title} 的第一段切片` : `${source.title} 的第二段切片` });
    }
    return fulfill(route, { source, text, text_truncated: false, jobs: [] });
  });
  await browser.route("**/api/v1/upload/file", (route) => { state.uploadCalls++; return fulfill(route, { success: true, asset_id: "ui-asset" }); });
  await browser.route("**/api/v1/knowledge/documents", async (route) => {
    state.ingestCalls++;
    if (state.failFirstIngest && state.ingestCalls === 1) return fulfill(route, { detail: "文档索引暂时不可用" }, 503);
    const uploaded = { ...sourceA, source_id: "asset:ui-asset", uri: "admin-knowledge.txt", title: "admin-knowledge.txt" };
    state.sources = [uploaded, ...state.sources];
    return fulfill(route, { job_id: "ui-job", domain_id: "recipes", source_id: uploaded.source_id, version: uploaded.version, ontology_version: "test-1", kind: "document", status: "ready", details: {}, error: null }, 201);
  });
  await browser.route("**/api/v1/ontology/admin/**", async (route) => {
    const url = new URL(route.request.url);
    if (url.pathname.endsWith("/source-facts")) {
      if (state.factsFailure) return fulfill(route, { detail: "图谱暂时不可用" }, 503);
      return fulfill(route, { ...(state.savedGraph ?? { entities: [], relations: [], sources: [] }), total: state.savedGraph ? 3 : 0, truncated: false, ontology_version: "test-1" });
    }
    if (url.pathname.endsWith("/extract")) {
      state.extractCalls++;
      const selection = JSON.parse(route.request.postData!) as { source_id: string };
      const activeSource = state.sources.find((source) => source.source_id === selection.source_id);
      if (!activeSource) return fulfill(route, { detail: "来源不存在" }, 404);
      return fulfill(route, { graph: { entities: [
        { id: "recipe", type: "RecipeVariant", name: "佛跳墙", aliases: [], properties: {}, evidence: [{ source_id: activeSource.source_id, quote: "冰糖少许" }] },
        { id: "date", type: "CookingStep", name: "红枣", aliases: [], properties: {}, evidence: [{ source_id: activeSource.source_id, quote: "红枣洗净后加入" }] }
      ], relations: [{ id: "edge", source_id: "recipe", target_id: "date", type: "HAS_MAIN_INGREDIENT", properties: {}, evidence: [{ source_id: activeSource.source_id, quote: "红枣洗净后加入" }] }], sources: [{ id: activeSource.source_id, text, uri: activeSource.uri }] }, validation: { valid: false, errors: ["主料关系的目标应为食材"] } });
    }
    const body = JSON.parse(route.request.postData!) as { graph: KnowledgeGraph };
    if (url.pathname.endsWith("/validate")) {
      state.validateCalls++;
      state.validatedGraph = body.graph;
      return fulfill(route, { graph: body.graph, validation: { valid: body.graph.entities[1].type === "Ingredient", errors: [] } });
    }
    state.saveCalls++;
    state.savedGraph = body.graph;
    return fulfill(route, { entities: 2, relations: 1, sources: 1 });
  });
  return Object.assign(state, { editing });
}

test("document editor keeps the full original and publishes a pinned revision", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  state.editing.text = "完整原文。".repeat(4500) + "不可丢失的末尾";
  await app.open("/admin.html?view=library");
  await screen.getByRole("button", "编辑原文", { exact: true }).tap();
  await expect(screen.getByRole("heading", "编辑文档", { exact: true })).toBeVisible();
  await expect(screen.getByLabel("原文", { exact: true })).toHaveValue(state.editing.text);
  await screen.getByLabel("资料名称", { exact: true }).fill("修订后的资料甲");
  const revised = state.editing.text + "\n本次修改。";
  await screen.getByLabel("原文", { exact: true }).fill(revised);
  await screen.getByRole("button", "保存并更新检索", { exact: true }).tap();
  await expect(screen.getByRole("heading", "编辑文档", { exact: true })).toHaveCount(0);
  await expect(screen.getByRole("heading", "修订后的资料甲", { exact: true })).toBeVisible();
  expect(state.editing.requests[0]).toEqual({ source_id: sourceA.source_id, version: "v1", revision: "a".repeat(64), title: "修订后的资料甲", text: revised });
});

test("document editor retains failed drafts and confirms discard", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  state.editing.failure = true;
  await app.open("/admin.html?view=library");
  await screen.getByRole("button", "编辑原文", { exact: true }).tap();
  await screen.getByLabel("原文", { exact: true }).fill("失败后应该保留的完整修改。");
  await screen.getByRole("button", "保存并更新检索", { exact: true }).tap();
  await expect(screen.getByRole("alert")).toContainText("版本冲突");
  await expect(screen.getByLabel("原文", { exact: true })).toHaveValue("失败后应该保留的完整修改。");
  await screen.getByRole("button", "关闭编辑文档", { exact: true }).tap();
  await expect(screen.getByRole("heading", "放弃文档修改？", { exact: true })).toBeVisible();
  await screen.getByRole("button", "取消", { exact: true }).last().tap();
  await expect(screen.getByLabel("原文", { exact: true })).toHaveValue("失败后应该保留的完整修改。");
  state.editing.failure = false;
  await screen.getByRole("button", "保存并更新检索", { exact: true }).tap();
  await expect(screen.getByRole("heading", "编辑文档", { exact: true })).toHaveCount(0);
  expect(state.editing.requests.length).toBe(2);
});

test("document list deletion names the chosen document and waits for confirmation", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  await app.open("/admin.html?view=library");
  await screen.getByRole("button", "删除文档：资料乙.txt", { exact: true }).tap();
  await expect(screen.getByRole("dialog", "删除文档记录？")).toContainText("资料乙.txt");
  expect(state.deleteRequests).toEqual([]);
  await screen.getByRole("button", "确认删除", { exact: true }).tap();
  await expect(screen.getByRole("button", "核对资料：资料乙.txt", { exact: true })).toHaveCount(0);
  await expect(screen.getByRole("button", "核对资料：资料甲.txt", { exact: true })).toBeVisible();
  expect(state.deleteRequests).toEqual([sourceB.source_id]);
});

test("cancelling an editor read preserves the separate new document draft", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  await app.open("/admin.html?view=library");
  await screen.getByRole("button", "添加文档", { exact: true }).tap();
  await screen.getByRole("button", "粘贴文本", { exact: true }).tap();
  await screen.getByLabel("资料名称", { exact: true }).fill("未发送的新资料");
  await screen.getByLabel("原文", { exact: true }).fill("新增文档尚未发送的正文。");
  await screen.getByRole("button", "关闭添加文档", { exact: true }).tap();
  let release!: () => void;
  state.editing.readGate = new Promise<void>((resolve) => { release = resolve; });
  try {
    await screen.getByRole("button", "编辑原文", { exact: true }).tap();
    await expect(screen.getByRole("status")).toContainText("正在读取完整原文");
    await screen.getByRole("button", "关闭编辑文档", { exact: true }).tap();
    await screen.getByRole("button", "添加文档", { exact: true }).tap();
    release();
    await expect(screen.getByLabel("资料名称", { exact: true })).toHaveValue("未发送的新资料");
    await expect(screen.getByLabel("原文", { exact: true })).toHaveValue("新增文档尚未发送的正文。");
    expect(state.editing.requests).toEqual([]);
  } finally { release(); }
});

test("document editor remains usable on a narrow screen", async ({ app, browser, screen }) => {
  await installFixtures(browser);
  await browser.setViewport({ width: 390, height: 844 });
  await app.open("/admin.html?view=library");
  await screen.getByRole("button", "编辑原文", { exact: true }).tap();
  await expect(screen.getByLabel("原文", { exact: true })).toHaveValue(text);
  await expect(screen.getByRole("button", "保存并更新检索", { exact: true })).toBeVisible();
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await app.screenshot("document-editor-mobile");
});

test("admin signs in, restores the requested view on refresh, and signs out", async ({ app, browser, screen }) => {
  await installFixtures(browser);
  let authenticated = false;
  await browser.route("**/api/v1/admin/session", async (route) => {
    if (route.request.method === "POST") {
      const { password } = JSON.parse(route.request.postData!) as { password: string };
      if (password !== "browser-test-password") {
        return fulfill(route, { detail: "Invalid administrator password" }, 401);
      }
      authenticated = true;
      return route.fulfill({ status: 204 });
    }
    if (route.request.method === "DELETE") {
      authenticated = false;
      return route.fulfill({ status: 204 });
    }
    return fulfill(route, { authenticated, configured: true });
  });

  await app.open("/admin.html?view=recipes");
  await expect(screen.getByRole("heading", "后台登录")).toBeVisible();
  await expect(screen.getByRole("navigation", "后台导航")).toHaveCount(0);
  const password = screen.getByLabel("管理员密码", { exact: true });
  await password.fill("wrong-password");
  await screen.getByRole("button", "显示密码").tap();
  await expect(screen.getByRole("button", "隐藏密码")).toBeVisible();
  await screen.getByRole("button", "隐藏密码").tap();
  await expect(screen.getByRole("button", "显示密码")).toBeVisible();
  await screen.getByRole("button", "登录", { exact: true }).tap();
  await expect(screen.getByRole("alert")).toContainText("密码不正确");
  await password.fill("browser-test-password");
  await screen.getByRole("button", "登录", { exact: true }).tap();
  await expect(screen.getByRole("heading", "菜谱与做法", { exact: true })).toBeVisible();
  await app.open("/admin.html?view=recipes");
  await expect(screen.getByRole("heading", "菜谱与做法", { exact: true })).toBeVisible();
  await screen.getByRole("button", "退出登录").tap();
  await expect(screen.getByRole("heading", "后台登录")).toBeVisible();
});

test("the single library reads stored slices and keeps recipes in their own view", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1920, height: 1080 });
  const state = await installFixtures(browser);
  state.sources.push(
    { ...sourceA, source_id: "failed-doc", title: "失败记录.txt", status: "failed", chunks: null },
    { ...sourceA, source_id: "recipe", title: "结构化做法记录", status: "graph_ready", kind: "recipe" },
  );
  await app.open("/admin.html?view=sources");
  await expect(screen.getByRole("navigation").getByRole("link", "向量知识库", { exact: true })).toHaveCount(1);
  await expect(browser.locator(".admin-source-name")).toHaveCount(3);
  await screen.getByRole("button", "核对资料：资料甲.txt", { exact: true }).tap();
  await expect(browser.locator(".admin-chunk-text")).toContainText("资料甲.txt 的第一段切片");
  await app.screenshot("library-workspace");
  await screen.getByRole("button", "下一片", { exact: true }).tap();
  await expect(browser.locator(".admin-chunk-text")).toContainText("资料甲.txt 的第二段切片");
  await screen.getByRole("button", /^失败/).tap();
  await expect(browser.locator(".admin-source-name")).toHaveCount(1);
  await expect(browser.locator(".admin-source-name")).toContainText("失败记录.txt");
  await screen.getByRole("navigation").getByRole("link", "菜谱与做法", { exact: true }).tap();
  await expect(browser.locator(".admin-source-name")).toHaveCount(1);
  await expect(browser.locator(".admin-source-name")).toContainText("结构化做法记录");
});

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`recipe source management selects the first record and shows stored graph facts at ${viewport.width} pixels`, async ({ app, browser }) => {
    await browser.setViewport(viewport);
    const state = await installFixtures(browser);
    const recipe: SourceSummary = { ...sourceA, source_id: "recipe-review", title: "番茄炒蛋", kind: "recipe", status: "graph_ready", entities: 2, relations: 1 };
    state.sources = [recipe];
    state.savedGraph = {
      entities: [
        { id: "variant", type: "RecipeVariant", name: "番茄炒蛋", aliases: [], properties: {}, evidence: [{ source_id: recipe.source_id, quote: "番茄炒蛋使用番茄。" }] },
        { id: "tomato", type: "Ingredient", name: "番茄", aliases: [], properties: {}, evidence: [{ source_id: recipe.source_id, quote: "番茄炒蛋使用番茄。" }] },
      ],
      relations: [{ id: "uses-tomato", source_id: "variant", target_id: "tomato", type: "HAS_MAIN_INGREDIENT", properties: {}, evidence: [{ source_id: recipe.source_id, quote: "番茄炒蛋使用番茄。" }] }],
      sources: [{ id: recipe.source_id, text: "番茄炒蛋使用番茄。", uri: recipe.uri }],
    };
    await app.open("/admin.html?view=recipes");
    await expect(browser.locator(".admin-source-name")).toHaveCount(1);
    await expect(browser.locator(".graph-node")).toHaveCount(2);
    await expect(browser.locator(".graph-edge")).toHaveCount(1);
    await expect(browser.locator(".recipe-source-heading")).toContainText(recipe.title);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await app.screenshot(`recipe-source-workspace-${viewport.width}`);
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
  test(`library workspace uses the available space at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    const state = await installFixtures(browser);
    state.sources.push({ ...sourceB, source_id: "long-document", title: "菜谱来源、处理说明与历史修订记录-2026年11月.txt" });
    await app.open("/admin.html");
    await expect(browser.locator(".admin-chunk-text")).toContainText("资料甲.txt 的第一段切片");
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (viewport.width > 1100) {
      expect(await browser.evaluate(() => {
        const directory = document.querySelector(".admin-collection")!.getBoundingClientRect();
        const review = document.querySelector(".library-review")!.getBoundingClientRect();
        return directory.right < review.left && review.right >= window.innerWidth - 40 && review.bottom <= window.innerHeight;
      })).toBe(true);
    }
    await app.screenshot(`library-${viewport.width}`);
    await screen.getByRole("button", "核对资料：资料乙.txt", { exact: true }).tap();
    await expect(browser.locator(".admin-chunk-text")).toContainText("资料乙.txt 的第一段切片");
    if (viewport.width <= 700) await app.screenshot("library-mobile-reading");
  });
}

test("duplicate document names keep their identity and support keyboard selection", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  const state = await installFixtures(browser);
  state.sources = [
    { ...sourceA, source_id: "withdrawn-new", title: "admin-knowledge.txt", status: "withdrawn", chunks: null, updated_at: "2026-11-21T00:34:00" },
    { ...sourceA, source_id: "withdrawn-old", title: "admin-knowledge.txt", status: "withdrawn", chunks: 1, updated_at: "2026-11-21T00:28:00" },
    sourceA, sourceB,
    { ...sourceB, source_id: "long-title", title: "跨领域知识服务与语义检索的来源、处理说明及历史修订记录-2026年11月.txt" },
  ];
  await app.open("/admin.html");
  await expect(screen.getByRole("button", "核对资料：admin-knowledge.txt", { exact: true })).toHaveCount(2);
  await expect(browser.locator(".admin-document-chunks").first()).toHaveText("—");
  await browser.locator(".admin-document-row").first().tap();
  await browser.keyboard.press("Tab");
  expect(await browser.evaluate(() => document.activeElement?.matches(".admin-document-delete:focus-visible") ?? false)).toBe(true);
  await browser.keyboard.press("Tab");
  expect(await browser.evaluate(() => document.activeElement?.matches(".admin-document-row:focus-visible") ?? false)).toBe(true);
  await browser.keyboard.press("Enter");
  await expect(browser.locator(".admin-document-row").nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect(browser.locator(".admin-review-meta time")).toHaveAttribute("datetime", "2026-11-21T00:28:00");
  await app.screenshot("directory-keyboard-selection");
});

test("source review stays within library and ontology when switching to conversation history", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  const state = await installFixtures(browser);
  state.sources = [{ ...sourceA, status: "withdrawn" }, sourceB];
  await browser.route("**/api/v1/admin/conversations**", (route) => fulfill(route, { items: [], total: 0, offset: 0, limit: 12 }));
  await app.open("/admin.html?view=library");
  await screen.getByRole("button", "核对资料：资料甲.txt", { exact: true }).tap();
  await expect(browser.locator(".admin-review[aria-label='来源核对']")).toHaveCount(1);
  await screen.getByRole("link", "对话记录", { exact: true }).tap();
  await expect(screen.getByRole("heading", "对话记录", { exact: true })).toBeVisible();
  await expect(browser.locator(".conversation-workspace")).toBeVisible();
  await app.screenshot("conversation-after-source-selection");
  await expect(browser.locator(".admin-review[aria-label='来源核对']")).toHaveCount(0);
  await screen.getByRole("link", "向量知识库", { exact: true }).tap();
  await expect(browser.locator(".admin-review[aria-label='来源核对']")).toHaveCount(1);
  await screen.getByRole("link", "本体与图谱", { exact: true }).tap();
  await expect(browser.locator(".admin-review[aria-label='来源核对']")).toHaveCount(0);
  await screen.getByRole("button", "来源映射核对", { exact: true }).tap();
  await expect(browser.locator(".admin-review[aria-label='来源核对']")).toHaveCount(1);
});

test("an empty library keeps its add action and reading placeholder", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  state.sources = [];
  await app.open("/admin.html");
  await expect(screen.getByRole("heading", "还没有文档", { exact: true })).toBeVisible();
  await expect(screen.getByRole("heading", "文档阅读区", { exact: true })).toBeVisible();
  await app.screenshot("library-empty");
});

test("document deletion requires confirmation and keeps withdrawn records available after a failure", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  const state = await installFixtures(browser);
  state.sources = [{ ...sourceA, status: "withdrawn" }, sourceB];
  await app.open("/admin.html");
  await screen.getByRole("button", "核对资料：资料甲.txt", { exact: true }).tap();
  await expect(screen.getByRole("button", "恢复文档入库", { exact: true })).toBeVisible();
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  const confirmation = screen.getByRole("dialog");
  await expect(confirmation).toContainText("全部版本");
  await expect(confirmation).toContainText("入库任务");
  await expect(confirmation).toContainText("向量切片");
  await expect(confirmation).toContainText("图谱事实");
  await expect(confirmation).toContainText("证据");
  await expect(confirmation).toContainText("文件会保留");
  await app.screenshot("library-delete-confirmation");
  await confirmation.getByRole("button", "取消", { exact: true }).tap();
  expect(state.deleteRequests).toEqual([]);
  await expect(browser.locator(".admin-review-heading")).toContainText(sourceA.title);

  state.deleteFailure = true;
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  await confirmation.getByRole("button", "确认删除", { exact: true }).tap();
  await expect(browser.locator(".admin-content > .admin-error")).toContainText("文档暂时无法删除");
  await expect(browser.locator(".admin-source-name")).toHaveCount(2);
  await expect(browser.locator(".admin-review-heading")).toContainText(sourceA.title);
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceA.title);
  await app.screenshot("library-delete-failure");

  state.deleteFailure = false;
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  await confirmation.getByRole("button", "确认删除", { exact: true }).tap();
  await expect(browser.locator(".admin-source-name")).toHaveCount(1);
  await expect(browser.locator(".admin-source-name")).toContainText(sourceB.title);
  await expect(browser.locator(".admin-content > .admin-error")).toHaveCount(0);
  await expect(screen.getByRole("heading", sourceA.title, { exact: true })).toHaveCount(0);
  expect(state.deleteRequests).toEqual([sourceA.source_id, sourceA.source_id]);
  expect(state.deleteVersions).toEqual([sourceA.version, sourceA.version]);
  await app.screenshot("library-deleted-record");
  await screen.getByRole("button", "核对资料：资料乙.txt", { exact: true }).tap();
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceB.title);
});

for (const pending of [
  { name: "pending source", status: "pending", jobStatus: null },
  { name: "processing source", status: "processing", jobStatus: null },
  { name: "ready source with processing job", status: "ready", jobStatus: "processing" },
  { name: "ready source with pending job", status: "ready", jobStatus: "pending" },
]) {
  test(`documents with active ingestion cannot be deleted: ${pending.name}`, async ({ app, browser, screen }) => {
    const state = await installFixtures(browser);
    state.sources = [{
      ...sourceA,
      status: pending.status,
      latest_job: pending.jobStatus === null ? null : {
        id: "active-job", status: pending.jobStatus, error: null, created_at: sourceA.created_at, updated_at: sourceA.updated_at,
      },
    }];
    await app.open("/admin.html");
    await expect(browser.locator(".admin-review-heading")).toContainText(sourceA.title);
    await expect(screen.getByRole("button", "删除文档记录", { exact: true })).toBeDisabled();
    expect(state.deleteRequests).toEqual([]);
  });
}

test("a deletion version conflict refreshes the latest document before another confirmation", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  state.sources = [sourceA];
  state.deleteConflict = true;
  await app.open("/admin.html");
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceA.title);
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  await screen.getByRole("dialog").getByRole("button", "确认删除", { exact: true }).tap();
  await expect(browser.locator(".admin-content > .admin-error")).toContainText("文档版本已更新");
  await expect(browser.locator(".admin-review-heading")).toContainText("资料甲新版.txt");
  await expect(browser.locator(".admin-chunk-text")).toContainText("资料甲新版.txt");
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  await expect(screen.getByRole("dialog")).toContainText("资料甲新版.txt");
  await screen.getByRole("dialog").getByRole("button", "确认删除", { exact: true }).tap();
  await expect(screen.getByRole("heading", "还没有文档", { exact: true })).toBeVisible();
  expect(state.deleteVersions).toEqual(["v1", "v2"]);
});

test("a failed deletion response clears stale details when the source was already removed", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  state.sources = [sourceA];
  state.deleteAfterRemovalFailure = true;
  await app.open("/admin.html");
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceA.title);
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  await screen.getByRole("dialog").getByRole("button", "确认删除", { exact: true }).tap();
  await expect(browser.locator(".admin-content > .admin-error")).toContainText("删除结果暂时无法确认");
  await expect(screen.getByRole("heading", "还没有文档", { exact: true })).toBeVisible();
  await expect(browser.locator(".admin-chunk-text")).toHaveCount(0);
  await expect(screen.getByRole("button", "删除文档记录", { exact: true })).toHaveCount(0);
});

test("document deletion confirmation stays usable on a narrow screen", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 390, height: 844 });
  await installFixtures(browser);
  await app.open("/admin.html");
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceA.title);
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  const confirmation = screen.getByRole("dialog");
  await expect(confirmation).toContainText("全部版本");
  await expect(confirmation.getByRole("button", "确认删除", { exact: true })).toBeVisible();
  expect(await browser.evaluate(() => {
    const dialog = document.querySelector(".admin-confirm")!.getBoundingClientRect();
    return dialog.left >= 0 && dialog.right <= window.innerWidth && dialog.top >= 0 && dialog.bottom <= window.innerHeight;
  })).toBe(true);
  await app.screenshot("library-delete-confirmation-mobile");
  await confirmation.getByRole("button", "取消", { exact: true }).tap();
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceA.title);
});

test("deleting the only document on the last page returns to the preceding page", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  state.sources = Array.from({ length: 7 }, (_, index) => ({
    ...sourceA, source_id: `delete-page-${index}`, title: `分页文档-${index + 1}.txt`,
  }));
  await app.open("/admin.html");
  await expect(browser.locator(".admin-source-name")).toHaveCount(6);
  await screen.getByRole("button", "下一页", { exact: true }).tap();
  await expect(browser.locator(".admin-source-name")).toHaveCount(1);
  await screen.getByRole("button", "核对资料：分页文档-7.txt", { exact: true }).tap();
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  await screen.getByRole("dialog").getByRole("button", "确认删除", { exact: true }).tap();
  await expect(browser.locator(".admin-source-name")).toHaveCount(6);
  await expect(screen.getByRole("button", "核对资料：分页文档-1.txt", { exact: true })).toBeVisible();
  await expect(screen.getByRole("button", "核对资料：分页文档-7.txt", { exact: true })).toHaveCount(0);
  await expect(browser.locator(".admin-pagination")).toHaveCount(0);
  await expect(screen.getByRole("heading", "分页文档-7.txt", { exact: true })).toHaveCount(0);
  expect(state.deleteRequests).toEqual(["delete-page-6"]);
});

test("deleting the final document shows the empty library without stale details", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  state.sources = [sourceA];
  await app.open("/admin.html");
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceA.title);
  await screen.getByRole("button", "删除文档记录", { exact: true }).tap();
  await screen.getByRole("dialog").getByRole("button", "确认删除", { exact: true }).tap();
  await expect(screen.getByRole("heading", "还没有文档", { exact: true })).toBeVisible();
  await expect(screen.getByRole("heading", "文档阅读区", { exact: true })).toBeVisible();
  await expect(browser.locator(".admin-chunk-text")).toHaveCount(0);
  await expect(screen.getByRole("button", "删除文档记录", { exact: true })).toHaveCount(0);
  expect(state.deleteRequests).toEqual([sourceA.source_id]);
});

test("a full directory and long text keep pagination and source actions reachable", async ({ app, browser }) => {
  await browser.setViewport({ width: 1366, height: 768 });
  const state = await installFixtures(browser);
  state.sources = Array.from({ length: 7 }, (_, index) => ({
    ...sourceA, source_id: `long-source-${index}`, title: `菜谱历史来源与导入说明文档-第${index + 1}份.txt`,
  }));
  await browser.route("**/api/v1/knowledge/admin/sources?**", (route) => fulfill(route, {
    domain, items: state.sources.slice(0, 6), total: 7, offset: 0, limit: 6,
    stats: { total: 7, ready: 7, processing: 0, failed: 0, withdrawn: 0, pending: 0 },
  }));
  await browser.route("**/api/v1/knowledge/admin/chunk?**", (route) => fulfill(route, {
    number: 1, total: 2, content: "长期文档保存来源与处理记录，便于逐段核对资料。\n\n".repeat(90),
  }));
  await app.open("/admin.html");
  await expect(browser.locator(".admin-source-name")).toHaveCount(6);
  await expect(browser.locator(".admin-chunk-text")).toContainText("长期文档");
  await app.screenshot("library-long-text");
  expect(await browser.evaluate(() => {
    const list = document.querySelector(".admin-table-wrap")!;
    const text = document.querySelector(".admin-chunk-text")!;
    const pagination = document.querySelector(".admin-pagination")!.getBoundingClientRect();
    const actions = document.querySelector(".review-actions")!.getBoundingClientRect();
    return {
      directoryScrolls: list.scrollHeight > list.clientHeight,
      textScrolls: text.scrollHeight > text.clientHeight,
      paginationVisible: pagination.bottom <= window.innerHeight,
      actionsVisible: actions.bottom <= window.innerHeight,
    };
  })).toEqual({ directoryScrolls: true, textScrolls: true, paginationVisible: true, actionsVisible: true });
});

test("admin keeps loaded sources visible when a refresh fails", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  await app.open("/admin.html");
  await expect(screen.getByRole("heading", "向量知识库", { exact: true })).toBeVisible();
  await expect(browser.locator(".admin-source-name")).toHaveCount(2);
  state.catalogFailure = true;
  await screen.getByRole("button", "刷新", { exact: true }).tap();
  await expect(browser.locator(".admin-list-error")).toContainText("目录暂时不可用");
  await expect(browser.locator(".admin-source-name")).toHaveCount(2);
  state.catalogFailure = false;
  await screen.getByRole("button", "重试列表").tap();
  await expect(browser.locator(".admin-list-error")).toHaveCount(0);
});

test("failed document indexing retries the same uploaded asset and preserves the form", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  const state = await installFixtures(browser);
  state.failFirstIngest = true;
  await app.open("/admin.html");
  await screen.getByRole("button", "添加文档", { exact: true }).tap();
  const dialog = screen.getByRole("dialog");
  await screen.getByLabel("选择文档").setInputFiles([fileURLToPath(new URL("./fixtures/admin-knowledge.txt", import.meta.url))]);
  await app.screenshot("admin-add-document-1440");
  await browser.setViewport({ width: 390, height: 844 });
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await app.screenshot("admin-add-document-390");
  await dialog.getByRole("button", "添加文档", { exact: true }).tap();
  await expect(dialog).toContainText("文档索引暂时不可用");
  await expect(screen.getByLabel("资料名称", { exact: true })).toHaveValue("admin-knowledge.txt");
  await dialog.getByRole("button", "添加文档", { exact: true }).tap();
  await expect(dialog).toHaveCount(0);
  await expect(browser.locator(".admin-review-heading")).toContainText("admin-knowledge.txt");
  expect(state.uploadCalls).toBe(1);
  expect(state.ingestCalls).toBe(2);
});

test("graph candidates must be revalidated after editing and extraction is not repeated", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  state.factsFailure = true;
  await app.open("/admin.html");
  await screen.getByRole("button", "核对资料：资料甲.txt", { exact: true }).tap();
  await screen.getByRole("button", "图谱核对", { exact: true }).tap();
  await expect(screen.getByRole("button", "重新读取图谱")).toBeVisible();
  state.factsFailure = false;
  await screen.getByRole("button", "重新读取图谱").tap();
  await expect(screen.getByRole("button", "重新读取图谱")).toHaveCount(0);
  await screen.getByRole("button", "抽取图谱候选").tap();
  await expect(browser.locator(".candidate-panel")).toContainText("主料关系的目标应为食材");
  await expect(screen.getByRole("button", "确认写入图谱")).toBeDisabled();
  await browser.locator(".candidate-item summary").nth(1).tap();
  await screen.getByLabel("类型", { exact: true }).selectOption({ value: "Ingredient" });
  await screen.getByLabel("属性 JSON", { exact: true }).fill('{"amount":0,"checked":false}');
  await screen.getByRole("button", "校验候选", { exact: true }).tap();
  await expect(screen.getByRole("button", "确认写入图谱")).toBeEnabled();
  await screen.getByLabel("名称", { exact: true }).fill("红枣（核对）");
  await expect(screen.getByRole("button", "确认写入图谱")).toBeDisabled();
  await screen.getByRole("button", "校验候选", { exact: true }).tap();
  await screen.getByRole("button", "确认写入图谱", { exact: true }).tap();
  await expect(browser.locator(".candidate-panel")).toHaveCount(0);
  expect(state.extractCalls).toBe(1);
  expect(state.validateCalls).toBe(2);
  expect(state.saveCalls).toBe(1);
  expect(state.savedGraph!.entities[1].properties.amount).toBe(0);
  expect(state.savedGraph!.entities[1].properties.checked).toBe(false);
  await expect(browser.locator(".graph-review")).toContainText("红枣（核对）");
  await app.screenshot("admin-reviewed-graph");
  await browser.setViewport({ width: 390, height: 844 });
  await browser.evaluate(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    return null;
  });
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await browser.evaluate(() => {
    const record = document.querySelector(".saved-facts .fact-item > summary")!.getBoundingClientRect();
    return record.top >= 0 && record.bottom <= window.innerHeight;
  })).toBe(true);
  await app.screenshot("admin-reviewed-graph-mobile");
  await browser.setViewport({ width: 1280, height: 720 });
  await screen.getByRole("button", "查看已入库图谱", { exact: true }).tap();
  await expect(browser.locator(".graph-node")).toHaveCount(2);
  await expect(browser.locator(".graph-edge")).toHaveCount(1);
  await expect(browser.locator(".graph-workspace-heading")).toContainText("资料甲.txt · 按来源版本核对");
  await app.screenshot("admin-source-version-graph");
  await browser.setViewport({ width: 390, height: 844 });
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await app.screenshot("admin-source-version-graph-mobile");
});

test("a delayed question result stays bound to its submitted source, including on mobile", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 390, height: 844 });
  await installFixtures(browser);
  let finishQuery: (() => void) | undefined;
  let announceQuery!: () => void;
  const queryStarted = new Promise<void>((resolve) => { announceQuery = resolve; });
  await browser.route("**/api/v1/knowledge/query", async (route) => {
    await new Promise<void>((resolve) => { finishQuery = resolve; announceQuery(); });
    await fulfill(route, { message: "原文只记录少许，没有克数。", route: "knowledge-query", route_logic: "原文检索", sources: [{ source_id: sourceA.source_id, name: sourceA.title }], metadata: {} });
  });
  await app.open("/admin.html");
  await screen.getByRole("button", "核对资料：资料甲.txt", { exact: true }).tap();
  await screen.getByText("查看来源原文", { exact: true }).tap();
  await expect(browser.locator(".admin-source-text")).toBeVisible();
  await screen.getByRole("navigation").getByRole("link", "问答测试", { exact: true }).tap();
  await screen.getByLabel("测试问题", { exact: true }).fill("糖有具体克数吗？");
  await screen.getByRole("button", "运行问答", { exact: true }).tap();
  await queryStarted;
  await screen.getByRole("navigation").getByRole("link", "向量知识库", { exact: true }).tap();
  await screen.getByRole("button", "核对资料：资料乙.txt", { exact: true }).tap();
  await expect(browser.locator(".admin-review-heading")).toContainText(sourceB.title);
  await screen.getByRole("navigation").getByRole("link", "问答测试", { exact: true }).tap();
  finishQuery!();
  await expect(browser.locator(".test-answer")).toContainText("没有克数");
  await expect(browser.locator(".citation-check")).toContainText(sourceA.title);
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await app.screenshot("admin-mobile-result");
});

test("a late import refresh cannot replace a newer document selection", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  await app.open("/admin.html");
  await expect(browser.locator(".admin-source-name")).toHaveCount(2);
  await screen.getByRole("button", "核对资料：资料甲.txt", { exact: true }).tap();
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceA.title);
  let resumeCatalog!: () => void;
  state.catalogGate = new Promise<void>((resolve) => { resumeCatalog = resolve; });
  await screen.getByRole("button", "添加文档", { exact: true }).tap();
  await screen.getByRole("button", "粘贴文本", { exact: true }).tap();
  await screen.getByLabel("资料名称", { exact: true }).fill("导入记录");
  await screen.getByLabel("原文", { exact: true }).fill("冰糖少许。");
  await screen.getByRole("button", "添加文本", { exact: true }).tap();
  await expect(screen.getByRole("dialog")).toHaveCount(0);
  await screen.getByRole("button", "核对资料：资料乙.txt", { exact: true }).tap();
  await expect(browser.locator(".admin-review-heading")).toContainText(sourceB.title);
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceB.title);
  state.catalogGate = null;
  resumeCatalog();
  await expect(browser.locator(".admin-source-name")).toHaveCount(3);
  await expect(browser.locator(".admin-refreshing")).toHaveCount(0);
  await expect(browser.locator(".admin-review-heading")).toContainText(sourceB.title);
  await expect(browser.locator(".admin-chunk-text")).toContainText(sourceB.title);
});

test("explicit navigation respects graph drafts and an in-flight write", async ({ app, browser, screen }) => {
  const state = await installFixtures(browser);
  await app.open("/admin.html");
  await screen.getByRole("button", "核对资料：资料甲.txt", { exact: true }).tap();
  await screen.getByRole("button", "图谱核对", { exact: true }).tap();
  await screen.getByRole("button", "抽取图谱候选").tap();
  await expect(browser.locator(".candidate-panel")).toBeVisible();
  await screen.getByRole("link", "回到餐桌手记", { exact: true }).tap();
  await expect(screen.getByRole("dialog")).toContainText("未入库");
  await screen.getByRole("dialog").getByRole("button", "取消", { exact: true }).tap();
  await expect(browser.locator(".candidate-panel")).toBeVisible();
  await browser.locator(".candidate-item summary").nth(1).tap();
  await screen.getByLabel("类型", { exact: true }).selectOption({ value: "Ingredient" });
  await screen.getByRole("button", "校验候选").tap();
  await expect(screen.getByRole("button", "确认写入图谱")).toBeEnabled();
  let releaseWrite!: () => void;
  let announceWrite!: () => void;
  const writeStarted = new Promise<void>((resolve) => { announceWrite = resolve; });
  const writeRelease = new Promise<void>((resolve) => { releaseWrite = resolve; });
  await browser.route("**/api/v1/ontology/admin/facts", async (route) => {
    announceWrite();
    await writeRelease;
    state.savedGraph = (JSON.parse(route.request.postData!) as { graph: KnowledgeGraph }).graph;
    await fulfill(route, { entities: 2, relations: 1, sources: 1 });
  });
  await screen.getByRole("button", "确认写入图谱").tap();
  await writeStarted;
  try {
    await screen.getByRole("link", "回到餐桌手记", { exact: true }).tap();
    await expect(browser.locator(".admin-content > .admin-error")).toContainText("等待结果后再切换");
    await expect(screen.getByRole("dialog")).toHaveCount(0);
  } finally {
    releaseWrite();
  }
  await expect(browser.locator(".candidate-panel")).toHaveCount(0);
  await screen.getByRole("link", "回到餐桌手记", { exact: true }).tap();
  await expect(screen.getByRole("heading", "菜谱", { exact: true })).toBeVisible();
});

test("confirming a return to the library discards a graph candidate", async ({ app, browser, screen }) => {
  await installFixtures(browser);
  await app.open("/admin.html");
  await screen.getByRole("button", "核对资料：资料甲.txt", { exact: true }).tap();
  await screen.getByRole("button", "图谱核对", { exact: true }).tap();
  await screen.getByRole("button", "抽取图谱候选").tap();
  await expect(browser.locator(".candidate-panel")).toBeVisible();
  await screen.getByRole("navigation").getByRole("link", "向量知识库", { exact: true }).tap();
  await screen.getByRole("button", "放弃并继续", { exact: true }).tap();
  await expect(screen.getByRole("heading", "向量知识库", { exact: true })).toBeVisible();
  await screen.getByRole("button", "图谱核对", { exact: true }).tap();
  await expect(browser.locator(".candidate-panel")).toHaveCount(0);
  await expect(screen.getByRole("button", "抽取图谱候选")).toBeVisible();
});

test("real admin imports a document and a recipe, reloads persisted facts, and runs a question", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open("/admin.html");
  const adminPassword = process.env.GUSTOBOT_TEST_ADMIN_PASSWORD;
  const cleanupHeaders: Record<string, string> = {};
  if (adminPassword) {
    await screen.getByLabel("管理员密码", { exact: true }).fill(adminPassword);
    await screen.getByRole("button", "登录", { exact: true }).tap();
    const session = await fetch("http://127.0.0.1:5174/api/v1/admin/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: adminPassword }),
    });
    expect(session.status).toBe(204);
    cleanupHeaders.Cookie = session.headers.get("set-cookie")!.split(";")[0];
  }
  await expect(browser.locator(".admin-source-name").first()).toBeVisible();
  await expect(browser.locator(".admin-chunk-text")).toBeVisible();
  await app.screenshot("library-live-workspace");
  let importedSourceId: string | undefined;
  let importedSourceVersion: string | undefined;
  let assetId: string | undefined;
  try {
    await screen.getByRole("button", "添加文档", { exact: true }).tap();
    await screen.getByLabel("选择文档").setInputFiles([fileURLToPath(new URL("./fixtures/admin-knowledge.txt", import.meta.url))]);
    const upload = browser.waitForResponse("**/api/v1/upload/file", { timeout: 90_000 });
    const ingestion = browser.waitForResponse("**/api/v1/knowledge/documents", { timeout: 90_000 });
    await screen.getByRole("dialog").getByRole("button", "添加文档", { exact: true }).tap();
    const uploadResponse = await upload;
    expect(uploadResponse.status).toBe(200);
    assetId = (await uploadResponse.json() as { asset_id: string }).asset_id;
    importedSourceId = `asset:${assetId}`;
    const receipt = await ingestion;
    expect(receipt.status).toBe(201);
    const imported = await receipt.json() as { source_id: string; version: string };
    importedSourceId = imported.source_id;
    importedSourceVersion = imported.version;
    await expect(browser.locator(".admin-chunk-text")).toContainText("ADMIN-1118");
    await app.open("/admin.html");
    await screen.getByRole("button", "核对资料：admin-knowledge.txt", { exact: true }).first().tap();
    await expect(browser.locator(".admin-chunk-text")).toContainText("ADMIN-1118");
    await expect(browser.locator(".ingestion-record")).toContainText("Milvus");
    await screen.getByRole("navigation").getByRole("link", "菜谱与做法", { exact: true }).tap();
    await screen.getByRole("button", "添加菜谱", { exact: true }).tap();
    await screen.getByLabel("菜名", { exact: true }).fill("番茄炒蛋");
    await screen.getByLabel("原始菜谱 JSON", { exact: true }).fill(readFileSync(fileURLToPath(new URL("./fixtures/admin-recipe.json", import.meta.url)), "utf8"));
    const recipe = browser.waitForResponse("**/api/v1/knowledge/recipes", { timeout: 90_000 });
    await screen.getByRole("button", "添加菜谱记录", { exact: true }).tap();
    const recipeResponse = await recipe;
    expect(recipeResponse.status).toBe(201);
    const recipeReceipt = await recipeResponse.json() as { source_id: string; version: string };
    const graphSelector = new URLSearchParams({ source_id: recipeReceipt.source_id, version: recipeReceipt.version });
    const graphResponse = await fetch(`http://127.0.0.1:5174/api/v1/ontology/admin/source-facts?${graphSelector}`, { headers: cleanupHeaders });
    expect(graphResponse.status).toBe(200);
    const stored = await graphResponse.json() as FactResult;
    await expect(browser.locator(".graph-node")).toHaveCount(stored.entities.length);
    await expect(browser.locator(".graph-edge")).toHaveCount(stored.relations.length);
    await expect(browser.locator(".recipe-source-heading")).toContainText("番茄炒蛋");
    await screen.getByRole("button", "事实", { exact: true }).tap();
    await expect(browser.locator(".graph-review")).toContainText("番茄");
    await expect(browser.locator(".graph-review")).toContainText("鸡蛋");
    await app.screenshot("admin-real-recipe-facts");
    await screen.getByRole("button", "查看已入库图谱", { exact: true }).tap();
    await expect(browser.locator(".graph-node")).toHaveCount(stored.entities.length);
    await expect(browser.locator(".graph-edge")).toHaveCount(stored.relations.length);
    const relation = stored.relations[0];
    const origin = stored.entities.find((entity) => entity.id === relation.source_id)!;
    const target = stored.entities.find((entity) => entity.id === relation.target_id)!;
    await screen.getByRole("button", `关系：${relation.type}，${origin.name} → ${target.name}`, { exact: true }).first().tap();
    await expect(browser.locator(".graph-inspector")).toContainText(relation.evidence[0].quote);
    await app.screenshot("admin-real-source-graph");
    await screen.getByRole("navigation").getByRole("link", "问答测试", { exact: true }).tap();
    await screen.getByLabel("测试问题", { exact: true }).fill("番茄炒蛋有哪些食材？");
    const question = browser.waitForResponse("**/api/v1/knowledge/query", { timeout: 90_000 });
    await screen.getByRole("button", "运行问答", { exact: true }).tap();
    const response = await question;
    expect(response.status).toBe(200);
    const answer = await response.json() as { message: string; metadata: { status: string } };
    await expect(browser.locator(".test-answer")).toHaveText(answer.message);
    await expect(browser.locator(".test-result header strong")).toBeVisible();
    if (answer.metadata.status === "needs_clarification") {
      await expect(browser.locator(".test-result header strong")).toHaveText("需要确认条件");
    }
    await app.screenshot("admin-real-question");
  } finally {
    if (importedSourceId) {
      const selector = new URLSearchParams({ source_id: importedSourceId });
      if (importedSourceVersion === undefined) {
        const detail = await fetch(`http://127.0.0.1:5174/api/v1/knowledge/admin/source?${selector}`, { headers: cleanupHeaders });
        if (detail.status !== 404) {
          expect(detail.status).toBe(200);
          importedSourceVersion = (await detail.json() as { source: { version: string } }).source.version;
        }
      }
      if (importedSourceVersion !== undefined) {
        selector.set("version", importedSourceVersion);
        const removed = await fetch(`http://127.0.0.1:5174/api/v1/knowledge/admin/source?${selector}`, { method: "DELETE", headers: cleanupHeaders });
        expect([200, 404].includes(removed.status)).toBe(true);
      }
    }
    if (assetId) {
      const removed = await fetch(`http://127.0.0.1:5174/api/v1/upload/${assetId}`, { method: "DELETE" });
      expect(removed.status).toBe(200);
    }
  }
});
