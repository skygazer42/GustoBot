import { test } from "@e2e-dev/web";
import type { Browser, WebRoute } from "@e2e-dev/web";
import { expect } from "e2e";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { KnowledgeGraph, SourceSummary } from "../src/admin/contracts";

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
  const state = { sources: [sourceA, sourceB], catalogFailure: false, catalogGate: null as Promise<void> | null, factsFailure: false, uploadCalls: 0, ingestCalls: 0, failFirstIngest: false, extractCalls: 0, validateCalls: 0, saveCalls: 0, savedGraph: null as KnowledgeGraph | null, validatedGraph: null as KnowledgeGraph | null };
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
      return fulfill(route, { domain, items, total: items.length, offset: 0, limit: 6, stats });
    }
    const source = state.sources.find((item) => item.source_id === url.searchParams.get("source_id"));
    if (!source) return fulfill(route, { detail: "资料不存在" }, 404);
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
  return state;
}

test("the single library reads stored slices and keeps recipes in their own view", async ({ app, browser, screen }) => {
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
  await screen.getByRole("button", "下一片", { exact: true }).tap();
  await expect(browser.locator(".admin-chunk-text")).toContainText("资料甲.txt 的第二段切片");
  await screen.getByRole("button", /^失败/).tap();
  await expect(browser.locator(".admin-source-name")).toHaveCount(1);
  await expect(browser.locator(".admin-source-name")).toContainText("失败记录.txt");
  await screen.getByRole("navigation").getByRole("link", "菜谱与做法", { exact: true }).tap();
  await expect(browser.locator(".admin-source-name")).toHaveCount(1);
  await expect(browser.locator(".admin-source-name")).toContainText("结构化做法记录");
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
  const state = await installFixtures(browser);
  state.failFirstIngest = true;
  await app.open("/admin.html");
  await screen.getByRole("button", "添加文档", { exact: true }).tap();
  const dialog = screen.getByRole("dialog");
  await screen.getByLabel("选择文档").setInputFiles([fileURLToPath(new URL("./fixtures/admin-knowledge.txt", import.meta.url))]);
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
  await screen.getByRole("link", "回到餐桌手记", { exact: true }).tap();
  await expect(browser.locator(".admin-content > .admin-error")).toContainText("正在提交入库");
  await expect(screen.getByRole("dialog")).toHaveCount(0);
  releaseWrite();
  await expect(browser.locator(".candidate-panel")).toHaveCount(0);
  await screen.getByRole("link", "回到餐桌手记", { exact: true }).tap();
  await expect(screen.getByRole("heading", "番茄炒蛋", { exact: true })).toBeVisible();
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
  await expect(browser.locator(".admin-source-name").first()).toBeVisible();
  let importedSourceId: string | undefined;
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
    const receipt = await ingestion;
    expect(receipt.status).toBe(201);
    importedSourceId = (await receipt.json() as { source_id: string }).source_id;
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
    expect((await recipe).status).toBe(201);
    await expect(browser.locator(".graph-review")).toContainText("番茄");
    await expect(browser.locator(".graph-review")).toContainText("鸡蛋");
    await app.screenshot("admin-real-recipe-facts");
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
      const removed = await fetch(`http://127.0.0.1:5174/api/v1/knowledge/sources/${encodeURIComponent(importedSourceId)}`, { method: "DELETE" });
      expect(removed.status).toBe(200);
    }
    if (assetId) {
      const removed = await fetch(`http://127.0.0.1:5174/api/v1/upload/${assetId}`, { method: "DELETE" });
      expect(removed.status).toBe(200);
    }
  }
});
