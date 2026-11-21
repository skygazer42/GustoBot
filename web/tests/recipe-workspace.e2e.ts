import { test } from "@e2e-dev/web";
import type { Browser, WebRoute } from "@e2e-dev/web";
import { expect } from "e2e";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { FactResult, SourceSummary } from "../src/admin/contracts";

const domain = {
  id: "recipes", name: "菜谱验收空间", version: "recipe-test-1", description: "资料与真实关系", interpretation_notes: [],
  classes: Object.fromEntries([["RecipeVariant", "具体做法"], ["Ingredient", "食材"], ["Dish", "菜品"], ["DishType", "分类"], ["Flavor", "口味"], ["CookingMethod", "烹饪方法"], ["CookingStep", "制作步骤"]].map(([type, label]) =>
    [type, { label, description: label, grain: "一条来源记录", properties: {} }])),
  allowed_edges: {
    HAS_MAIN_INGREDIENT: { domain: ["RecipeVariant"], range: ["Ingredient"], description: "使用主料", properties: {} },
    HAS_AUX_INGREDIENT: { domain: ["RecipeVariant"], range: ["Ingredient"], description: "使用辅料", properties: {} },
    HAS_STEP: { domain: ["RecipeVariant"], range: ["CookingStep"], description: "制作步骤", properties: {} },
    HAS_FLAVOR: { domain: ["RecipeVariant"], range: ["Flavor"], description: "具有口味", properties: {} },
    USES_METHOD: { domain: ["RecipeVariant"], range: ["CookingMethod"], description: "采用工艺", properties: {} },
    BELONGS_TO_TYPE: { domain: ["RecipeVariant"], range: ["DishType"], description: "归属分类", properties: {} },
    VARIANT_OF: { domain: ["RecipeVariant"], range: ["Dish"], description: "所属菜品", properties: {} },
  },
};

function recipe(index: number, title: string, ingredient: string): SourceSummary & { ingredient: string } {
  return {
    domain_id: domain.id, source_id: `recipe-source-${index}`, version: `${index.toString(16).padStart(8, "0")}-content`,
    uri: `${title}原始资料`, title, kind: "recipe", status: "graph_ready", ontology_version: domain.version,
    created_at: "2026-11-21T01:00:00", updated_at: "2026-11-21T01:00:00", chunks: null, entities: 2, relations: 1,
    latest_job: null, ingredient,
  };
}

const recipes = [
  recipe(0, "番茄炒蛋", "番茄"),
  recipe(1, "清炒菠菜", "菠菜"),
  recipe(2, "番茄炒蛋", "西红柿"),
  recipe(3, "醋溜土豆丝", "土豆"),
  recipe(4, "蒜蓉西兰花", "西兰花"),
  recipe(5, "丝瓜炒蛋", "丝瓜"),
  recipe(6, "清炒油麦菜", "油麦菜"),
  recipe(7, "香菇青菜", "香菇"),
];

function sourceText(source: typeof recipes[number]): string {
  return `${source.title}使用${source.ingredient}，保留该来源的原文用量。来源编号 ${source.source_id}。`;
}

function factsFor(source: typeof recipes[number]): FactResult {
  const evidence = [{ source_id: source.source_id, quote: sourceText(source) }];
  return {
    entities: [
      { id: `${source.source_id}:variant`, type: "RecipeVariant", name: source.title, aliases: [], properties: {}, evidence },
      { id: `${source.source_id}:ingredient`, type: "Ingredient", name: source.ingredient, aliases: [], properties: {}, evidence },
    ],
    relations: [{ id: `${source.source_id}:main`, source_id: `${source.source_id}:variant`, target_id: `${source.source_id}:ingredient`, type: "HAS_MAIN_INGREDIENT", properties: { amount: 0 }, evidence }],
    sources: [{ id: source.source_id, uri: source.uri, text: sourceText(source) }],
    total: 3, truncated: false, ontology_version: domain.version,
  };
}

async function fulfill(route: WebRoute, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function gate() {
  let release!: () => void;
  let announce!: () => void;
  let finish!: () => void;
  return {
    blocked: new Promise<void>((resolve) => { release = resolve; }),
    entered: new Promise<void>((resolve) => { announce = resolve; }),
    finished: new Promise<void>((resolve) => { finish = resolve; }),
    release: () => release(), announce: () => announce(), finish: () => finish(),
  };
}

async function installRecipes(browser: Browser) {
  const state = {
    sources: recipes.map((source) => ({ ...source })), catalogFailure: false, factsFailure: false,
    catalogRequests: [] as { q: string; offset: number; kind: string | null }[],
    factsRequests: [] as { source_id: string; version: string | null }[],
    catalogGates: new Map<string, ReturnType<typeof gate>>(), factsGates: new Map<string, ReturnType<typeof gate>>(),
    graphs: new Map<string, FactResult>(),
  };
  await browser.route("**/api/v1/admin/session", (route) => fulfill(route, { authenticated: false, configured: false }));
  await browser.route("**/api/v1/ontology/domain", (route) => fulfill(route, domain));
  await browser.route("**/api/v1/knowledge/admin/**", async (route) => {
    const url = new URL(route.request.url);
    if (url.pathname.endsWith("/sources")) {
      const q = url.searchParams.get("q") ?? "";
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 6);
      const kind = url.searchParams.get("kind");
      state.catalogRequests.push({ q, offset, kind });
      if (state.catalogFailure) return fulfill(route, { detail: "菜谱目录暂时不可用" }, 503);
      const matching = state.sources.filter((source) => source.title.includes(q) && (kind === "all" || kind === source.kind));
      const filter = url.searchParams.get("state") ?? "all";
      const filtered = matching.filter((source) => filter === "all" || source.status === filter || (filter === "ready" && source.status === "graph_ready"));
      const response = {
        domain, items: filtered.slice(offset, offset + limit), total: filtered.length, offset, limit,
        stats: { total: matching.length, ready: matching.filter((source) => ["ready", "graph_ready"].includes(source.status)).length, pending: 0, processing: 0, failed: 0, withdrawn: 0 },
      };
      const pending = state.catalogGates.get(q);
      if (pending) {
        pending.announce();
        await pending.blocked;
        try { await fulfill(route, response); } finally { pending.finish(); }
        return;
      }
      return fulfill(route, response);
    }
    const source = state.sources.find((item) => item.source_id === url.searchParams.get("source_id") && item.version === url.searchParams.get("version"));
    if (!source) return fulfill(route, { detail: "菜谱来源版本不存在" }, 404);
    return fulfill(route, { source, text: sourceText(source), text_truncated: false, jobs: [] });
  });
  await browser.route("**/api/v1/ontology/admin/source-facts?**", async (route) => {
    const url = new URL(route.request.url);
    const sourceId = url.searchParams.get("source_id") ?? "";
    const version = url.searchParams.get("version");
    state.factsRequests.push({ source_id: sourceId, version });
    const source = state.sources.find((item) => item.source_id === sourceId && item.version === version);
    if (!source) return fulfill(route, { detail: "图谱来源版本不存在" }, 404);
    if (state.factsFailure) return fulfill(route, { detail: "菜谱图谱暂时不可用" }, 503);
    const response = state.graphs.get(sourceId) ?? factsFor(source);
    const pending = state.factsGates.get(sourceId);
    if (pending) {
      pending.announce();
      await pending.blocked;
      try { await fulfill(route, response); } finally { pending.finish(); }
      return;
    }
    return fulfill(route, response);
  });
  return state;
}

for (const width of [1440, 768, 390]) {
  test(`admin navigation keeps the same layout while switching all views at ${width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport({ width, height: 900 });
    await installRecipes(browser);
    await browser.route("**/api/v1/ontology/query", (route) => fulfill(route, { entities: [], relations: [], sources: [], total: 0, truncated: false, ontology_version: domain.version }));
    await browser.route("**/api/v1/admin/conversations?**", (route) => fulfill(route, { items: [], total: 0, offset: 0, limit: 12 }));
    await app.open("/admin.html?view=library");
    await expect(screen.getByRole("navigation", "后台导航", { exact: true })).toBeVisible();
    await browser.evaluate(async () => { await document.fonts.ready; return null; });
    const baseline = await browser.evaluate(() => {
      const sidebar = document.querySelector(".admin-sidebar")!.getBoundingClientRect();
      return {
        width: sidebar.width, height: sidebar.height,
        mainLeft: document.querySelector(".admin-main")!.getBoundingClientRect().left,
        links: [...document.querySelectorAll<HTMLAnchorElement>(".admin-sidebar nav > a")].map((link) => {
          const bounds = link.getBoundingClientRect();
          return { text: link.innerText.trim(), x: Math.round(bounds.x), y: Math.round(bounds.y), width: Math.round(bounds.width), height: Math.round(bounds.height) };
        }),
      };
    });
    for (const view of [
      { id: "recipes", label: "菜谱与做法" }, { id: "ontology", label: "本体与图谱" },
      { id: "test", label: "问答测试" }, { id: "conversations", label: "对话记录" },
      { id: "library", label: "向量知识库" },
    ]) {
      await screen.getByRole("navigation", "后台导航", { exact: true }).getByRole("link", view.label, { exact: true }).tap();
      await expect(browser.locator(`.admin-sidebar nav a[href='/admin.html?view=${view.id}']`)).toHaveAttribute("aria-current", "page");
      const current = await browser.evaluate(() => {
        const sidebar = document.querySelector(".admin-sidebar")!.getBoundingClientRect();
        return {
          width: sidebar.width, height: sidebar.height,
          mainLeft: document.querySelector(".admin-main")!.getBoundingClientRect().left,
          links: [...document.querySelectorAll<HTMLAnchorElement>(".admin-sidebar nav > a")].map((link) => {
            const bounds = link.getBoundingClientRect();
            return { text: link.innerText.trim(), x: Math.round(bounds.x), y: Math.round(bounds.y), width: Math.round(bounds.width), height: Math.round(bounds.height) };
          }),
        };
      });
      expect(current).toEqual(baseline);
      expect(await browser.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (view.id === "recipes") await app.screenshot(`stable-navigation-${width}`);
    }
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`recipe graph workspace chooses a source and keeps graph, facts and original aligned at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    const state = await installRecipes(browser);
    await app.open("/admin.html?view=recipes");
    await expect(screen.getByRole("button", "选择菜谱", { exact: true })).toBeVisible();
    await expect(browser.locator(".graph-node")).toHaveCount(2);
    await expect(screen.getByRole("heading", recipes[0].title, { exact: true })).toBeVisible();
    await screen.getByRole("button", `实体：${recipes[0].ingredient}（食材）`, { exact: true }).tap();
    await expect(browser.locator(".graph-inspector")).toContainText(sourceText(recipes[0]));
    expect(state.factsRequests.some((request) => request.source_id === recipes[0].source_id && request.version === recipes[0].version)).toBe(true);
    expect(state.factsRequests.filter((request) => request.source_id === recipes[0].source_id && request.version === recipes[0].version).length).toBe(1);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await app.screenshot(`recipe-graph-${viewport.width}`);

    await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
    const picker = screen.getByRole("dialog", "选择菜谱", { exact: true });
    await expect(picker).toBeVisible();
    await expect(picker.getByRole("button", /^核对资料：/)).toHaveCount(6);
    expect(await browser.evaluate(() => {
      const dialog = document.querySelector("dialog[open]")!.getBoundingClientRect();
      return dialog.left >= 0 && dialog.right <= window.innerWidth && dialog.top >= 0 && dialog.bottom <= window.innerHeight;
    })).toBe(true);
    await app.screenshot(`recipe-picker-${viewport.width}`);
    await picker.getByRole("button", `核对资料：${recipes[1].title}`, { exact: true }).tap();
    await expect(browser.locator("dialog[open]")).toHaveCount(0);
    await expect(screen.getByRole("heading", recipes[1].title, { exact: true })).toBeVisible();
    await expect(screen.getByRole("button", `实体：${recipes[1].ingredient}（食材）`, { exact: true })).toBeVisible();
    await screen.getByRole("button", `实体：${recipes[1].ingredient}（食材）`, { exact: true }).tap();
    await expect(browser.locator(".graph-inspector")).toContainText(sourceText(recipes[1]));
    await expect(screen.getByRole("button", `实体：${recipes[0].ingredient}（食材）`, { exact: true })).toHaveCount(0);
    expect(state.factsRequests.some((request) => request.source_id === recipes[1].source_id && request.version === recipes[1].version)).toBe(true);
    await app.screenshot(`recipe-selected-${viewport.width}`);

    await screen.getByRole("button", "事实", { exact: true }).tap();
    await expect(browser.locator(".graph-review")).toContainText(recipes[1].ingredient);
    await screen.getByRole("button", "来源原文", { exact: true }).tap();
    await expect(browser.locator(".admin-source-text")).toContainText(sourceText(recipes[1]));
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("recipe picker searches all pages and distinguishes equal dish names by exact identity", async ({ app, browser, screen }) => {
  const state = await installRecipes(browser);
  await app.open("/admin.html?view=recipes");
  await expect(browser.locator(".graph-node")).toHaveCount(2);
  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  const picker = screen.getByRole("dialog", "选择菜谱", { exact: true });
  await picker.getByRole("button", "下一页", { exact: true }).tap();
  await expect(picker.getByRole("button", /^核对资料：/)).toHaveCount(2);
  await picker.getByRole("button", `核对资料：${recipes[7].title}`, { exact: true }).tap();
  await expect(screen.getByRole("button", `实体：${recipes[7].ingredient}（食材）`, { exact: true })).toBeVisible();
  expect(state.catalogRequests.some((request) => request.offset === 6 && request.kind === "recipe")).toBe(true);

  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  await picker.getByLabel("搜索做法名称", { exact: true }).fill("番茄炒蛋");
  const matches = picker.getByRole("button", "核对资料：番茄炒蛋", { exact: true });
  await expect(matches).toHaveCount(2);
  await expect(matches.nth(0)).toContainText(recipes[0].version.slice(0, 8));
  await expect(matches.nth(1)).toContainText(recipes[2].version.slice(0, 8));
  await matches.nth(1).tap();
  await expect(screen.getByRole("button", `实体：${recipes[2].ingredient}（食材）`, { exact: true })).toBeVisible();
  expect(state.factsRequests.some((request) => request.source_id === recipes[2].source_id && request.version === recipes[2].version)).toBe(true);
  expect(state.catalogRequests.some((request) => request.q === "番茄炒蛋" && request.offset === 0)).toBe(true);

  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  await picker.getByLabel("搜索做法名称", { exact: true }).fill("不存在的菜谱");
  await expect(picker.getByRole("heading", "没有符合条件的记录", { exact: true })).toBeVisible();
  await picker.getByRole("button", "清除筛选", { exact: true }).tap();
  await expect(picker.getByRole("button", /^核对资料：/)).toHaveCount(6);
});

test("recipe picker closes with Escape or its close action and returns focus without changing the source", async ({ app, browser, screen }) => {
  const state = await installRecipes(browser);
  await app.open("/admin.html?view=recipes");
  await expect(browser.locator(".graph-node")).toHaveCount(2);
  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  await expect(screen.getByRole("dialog", "选择菜谱", { exact: true })).toBeVisible();
  await browser.keyboard.press("Escape");
  await expect(browser.locator("dialog[open]")).toHaveCount(0);
  expect(await browser.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? null)).toBe("选择菜谱");
  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  await screen.getByRole("button", "关闭菜谱选择", { exact: true }).tap();
  await expect(browser.locator("dialog[open]")).toHaveCount(0);
  expect(await browser.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? null)).toBe("选择菜谱");
  await expect(screen.getByRole("heading", recipes[0].title, { exact: true })).toBeVisible();
  expect(state.factsRequests.every((request) => request.source_id === recipes[0].source_id)).toBe(true);
});

test("recipe catalog failure is distinct from empty and can recover through the picker", async ({ app, browser, screen }) => {
  const state = await installRecipes(browser);
  state.catalogFailure = true;
  await app.open("/admin.html?view=recipes");
  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  const picker = screen.getByRole("dialog", "选择菜谱", { exact: true });
  await expect(picker).toContainText("菜谱目录暂时不可用");
  await expect(picker.getByRole("heading", "还没有菜谱", { exact: true })).toHaveCount(0);
  state.catalogFailure = false;
  await picker.getByRole("button", "重试列表", { exact: true }).tap();
  await expect(picker.getByRole("button", /^核对资料：/)).toHaveCount(6);
  await picker.getByRole("button", `核对资料：${recipes[1].title}`, { exact: true }).tap();
  await expect(screen.getByRole("button", `实体：${recipes[1].ingredient}（食材）`, { exact: true })).toBeVisible();
});

test("an empty recipe collection keeps adding and choosing available without a fabricated graph", async ({ app, browser, screen }) => {
  const state = await installRecipes(browser);
  state.sources = [];
  await app.open("/admin.html?view=recipes");
  await expect(screen.getByRole("heading", "还没有菜谱", { exact: true })).toBeVisible();
  await expect(screen.getByRole("button", "添加菜谱", { exact: true }).first()).toBeVisible();
  await expect(browser.locator(".graph-node")).toHaveCount(0);
  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  await expect(screen.getByRole("dialog", "选择菜谱", { exact: true })).toContainText("还没有菜谱");
  expect(state.factsRequests).toEqual([]);
  await app.screenshot("recipe-empty");
});

test("recipe graph failures can retry the same exact source", async ({ app, browser, screen }) => {
  const state = await installRecipes(browser);
  state.factsFailure = true;
  await app.open("/admin.html?view=recipes");
  await expect(screen.getByRole("alert")).toContainText("菜谱图谱暂时不可用");
  await expect(browser.locator(".graph-node")).toHaveCount(0);
  const attempts = state.factsRequests.length;
  state.factsFailure = false;
  await screen.getByRole("button", "重试图谱读取", { exact: true }).tap();
  await expect(browser.locator(".graph-node")).toHaveCount(2);
  expect(state.factsRequests.length > attempts).toBe(true);
  expect(state.factsRequests.every((request) => request.source_id === recipes[0].source_id && request.version === recipes[0].version)).toBe(true);
});

test("a late graph response for a previously selected recipe cannot replace the new recipe", async ({ app, browser, screen }) => {
  const state = await installRecipes(browser);
  await app.open("/admin.html?view=recipes");
  await expect(browser.locator(".graph-node")).toHaveCount(2);
  const pending = gate();
  state.factsGates.set(recipes[1].source_id, pending);
  try {
    await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
    await screen.getByRole("dialog", "选择菜谱", { exact: true }).getByRole("button", `核对资料：${recipes[1].title}`, { exact: true }).tap();
    await pending.entered;
    await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
    await screen.getByRole("dialog", "选择菜谱", { exact: true }).getByRole("button", `核对资料：${recipes[3].title}`, { exact: true }).tap();
    await expect(screen.getByRole("button", `实体：${recipes[3].ingredient}（食材）`, { exact: true })).toBeVisible();
    pending.release();
    await pending.finished;
    await expect(screen.getByRole("heading", recipes[3].title, { exact: true })).toBeVisible();
    await expect(screen.getByRole("button", `实体：${recipes[1].ingredient}（食材）`, { exact: true })).toHaveCount(0);
    await screen.getByRole("button", `实体：${recipes[3].ingredient}（食材）`, { exact: true }).tap();
    await expect(browser.locator(".graph-inspector")).toContainText(sourceText(recipes[3]));
  } finally {
    pending.release();
  }
});

test("a late picker search response cannot overwrite the current search results", async ({ app, browser, screen }) => {
  const state = await installRecipes(browser);
  await app.open("/admin.html?view=recipes");
  await expect(browser.locator(".graph-node")).toHaveCount(2);
  const pending = gate();
  state.catalogGates.set("菠菜", pending);
  try {
    await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
    const picker = screen.getByRole("dialog", "选择菜谱", { exact: true });
    await picker.getByLabel("搜索做法名称", { exact: true }).fill("菠菜");
    await pending.entered;
    await picker.getByLabel("搜索做法名称", { exact: true }).fill("土豆");
    await expect(picker.getByRole("button", /^核对资料：/)).toHaveCount(1);
    await expect(picker.getByRole("button", /^核对资料：/)).toContainText(recipes[3].title);
    pending.release();
    await pending.finished;
    await expect(picker.getByRole("button", /^核对资料：/)).toHaveCount(1);
    await expect(picker.getByRole("button", /^核对资料：/)).toContainText(recipes[3].title);
  } finally {
    pending.release();
  }
});

test("desktop recipe graph uses the full workspace and keeps the inspector and canvas controls in view", async ({ app, browser }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await installRecipes(browser);
  await app.open("/admin.html?view=recipes");
  await expect(browser.locator(".graph-node")).toHaveCount(2);
  expect(await browser.evaluate(() => {
    const contentArea = document.querySelector(".admin-main")!.getBoundingClientRect();
    const main = document.querySelector(".recipe-main")!.getBoundingClientRect();
    const workspace = document.querySelector(".graph-workspace")!.getBoundingClientRect();
    const canvas = document.querySelector(".graph-canvas")!.getBoundingClientRect();
    const inspector = document.querySelector(".graph-inspector")!.getBoundingClientRect();
    const controls = document.querySelector(".graph-canvas-tools")!.getBoundingClientRect();
    const footer = document.querySelector(".graph-workspace-footer")!.getBoundingClientRect();
    const tabs = document.querySelector(".recipe-view-tabs")!.getBoundingClientRect();
    return {
      sourceUsesAvailableWidth: Math.abs(main.width - contentArea.width) <= 1,
      graphUsesAvailableWidth: Math.abs(workspace.width - contentArea.width) <= 1,
      canvasHasWorkingSpace: canvas.width >= window.innerWidth * 0.55,
      inspectorHasReadableWidth: inspector.width >= 260,
      canvasAndInspectorShareARow: canvas.right <= inspector.left + 1 && Math.abs(canvas.top - inspector.top) <= 1,
      workspaceFitsViewport: workspace.right <= window.innerWidth + 1 && workspace.bottom <= window.innerHeight + 1,
      controlsRemainVisible: controls.left >= 0 && controls.top >= 0 && controls.right <= window.innerWidth && controls.bottom <= window.innerHeight,
      footerRemainsVisible: footer.left >= 0 && footer.right <= window.innerWidth && footer.bottom <= window.innerHeight + 1,
      viewActionsRemainVisible: tabs.left >= 0 && tabs.right <= window.innerWidth && tabs.bottom <= window.innerHeight,
    };
  })).toEqual({
    sourceUsesAvailableWidth: true,
    graphUsesAvailableWidth: true,
    canvasHasWorkingSpace: true,
    inspectorHasReadableWidth: true,
    canvasAndInspectorShareARow: true,
    workspaceFitsViewport: true,
    controlsRemainVisible: true,
    footerRemainsVisible: true,
    viewActionsRemainVisible: true,
  });
  await app.screenshot("recipe-desktop-layout");
});

test("a fifteen-node recipe remains readable on mobile and its offscreen relationships can be inspected through search", async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 390, height: 844 });
  const state = await installRecipes(browser);
  const source = recipes[0];
  const snapshot = JSON.parse(readFileSync(fileURLToPath(new URL("./fixtures/recipe-graph.json", import.meta.url)), "utf8")) as FactResult;
  const graph: FactResult = {
    ...snapshot,
    entities: snapshot.entities.map((entity) => ({ ...entity, evidence: entity.evidence.map((item) => ({ ...item, source_id: source.source_id })) })),
    relations: snapshot.relations.map((relation) => ({ ...relation, evidence: relation.evidence.map((item) => ({ ...item, source_id: source.source_id })) })),
    sources: snapshot.sources.map((item) => ({ ...item, id: source.source_id, uri: source.uri })),
    ontology_version: domain.version,
  };
  state.sources = [{ ...source, entities: graph.entities.length, relations: graph.relations.length }];
  state.graphs.set(source.source_id, graph);
  await app.open("/admin.html?view=recipes");
  await expect(browser.locator(".graph-node")).toHaveCount(15);
  await expect(browser.locator(".graph-edge")).toHaveCount(14);
  await expect(browser.locator(".graph-canvas.is-card-graph")).toBeVisible();
  await browser.evaluate(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    return null;
  });
  expect(await browser.evaluate(() => {
    const cards = [...document.querySelectorAll(".graph-node-body")].map((card) => card.getBoundingClientRect());
    const names = [...document.querySelectorAll(".graph-node-name")].map((name) => name.getBoundingClientRect());
    const canvas = document.querySelector(".graph-canvas")!.getBoundingClientRect();
    const selectedNames = [...document.querySelectorAll(".graph-node.is-highlighted .graph-node-name")].map((name) => name.getBoundingClientRect());
    const controls = document.querySelector(".graph-canvas-tools")!.getBoundingClientRect();
    const selectedCards = [...document.querySelectorAll(".graph-node.is-highlighted .graph-node-body")].map((card) => card.getBoundingClientRect());
    const stepNames = [...document.querySelectorAll(".graph-node")]
      .filter((node) => node.getAttribute("aria-label")?.endsWith("（制作步骤）"))
      .map((node) => node.querySelector(".graph-node-name")?.textContent?.trim() ?? "");
    return {
      allCardsRetained: cards.length === 15,
      cardsDoNotOverlap: cards.every((card, index) => cards.slice(index + 1).every((other) =>
        card.right <= other.left || card.left >= other.right || card.bottom <= other.top || card.top >= other.bottom)),
      namesRemainReadable: names.length === 15 && names.every((name) => name.height >= 11),
      initialRelationNamesAreVisible: selectedNames.length === 2 && selectedNames.every((name) =>
        name.left >= canvas.left && name.right <= canvas.right && name.top >= canvas.top && name.bottom <= canvas.bottom),
      initialSelectionAvoidsControls: selectedCards.every((card) =>
        card.right <= controls.left || card.left >= controls.right || card.bottom <= controls.top || card.top >= controls.bottom),
      stepActionsAreNumbered: stepNames.length === 6 && stepNames.every((name) => /^[1-6]\.\s*\S/.test(name) && !name.includes("Step") && !name.includes("番茄炒蛋")),
      noHorizontalPageOverflow: document.documentElement.scrollWidth <= window.innerWidth,
    };
  })).toEqual({ allCardsRetained: true, cardsDoNotOverlap: true, namesRemainReadable: true, initialRelationNamesAreVisible: true, initialSelectionAvoidsControls: true, stepActionsAreNumbered: true, noHorizontalPageOverflow: true });
  await app.screenshot("recipe-fifteen-nodes-mobile");

  await browser.setViewport({ width: 1440, height: 900 });
  const steps = graph.entities.filter((entity) => typeof entity.properties.order === "number")
    .sort((left, right) => Number(left.properties.order) - Number(right.properties.order));
  const stepGroup = browser.locator(`.graph-node-group[data-entity-type="${steps[0].type}"]`);
  await expect(stepGroup).toHaveCount(1);
  await expect(stepGroup).toContainText("制作步骤");
  await expect(browser.locator(".graph-node.is-grouped")).toHaveCount(10);
  await screen.getByRole("button", "实体：2. 蛋液两边摊匀，煎好捞出备用。（制作步骤）", { exact: true }).tap();
  await expect(browser.locator(".graph-inspector h3")).toHaveText("2. 蛋液两边摊匀，煎好捞出备用。");
  await app.screenshot("recipe-grouped-steps-selected-desktop");
  await browser.setViewport({ width: 390, height: 844 });
  await browser.evaluate(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    return null;
  });
  await screen.getByRole("button", "实体：3. 锅中油预热，放入番茄煸炒。（制作步骤）", { exact: true }).focus();
  await browser.keyboard.press("Enter");
  await expect(browser.locator(".graph-inspector h3")).toHaveText("3. 锅中油预热，放入番茄煸炒。");
  expect(await browser.evaluate(() => {
    const canvas = document.querySelector(".graph-canvas")!.getBoundingClientRect();
    const selected = document.querySelector(".graph-node.is-grouped.is-selected")!;
    const type = selected.getAttribute("aria-label")?.match(/（(.+)）$/)?.[1];
    const group = [...document.querySelectorAll(".graph-node-group")].find((item) => item.querySelector(".graph-group-title")?.textContent === type)!.getBoundingClientRect();
    const controls = document.querySelector(".graph-canvas-tools")!.getBoundingClientRect();
    return {
      groupInsideCanvas: group.left >= canvas.left && group.right <= canvas.right && group.top >= canvas.top && group.bottom <= canvas.bottom,
      groupAvoidsControls: group.right <= controls.left || group.left >= controls.right || group.bottom <= controls.top || group.top >= controls.bottom,
    };
  })).toEqual({ groupInsideCanvas: true, groupAvoidsControls: true });
  await browser.evaluate(() => { window.scrollTo(0, 0); return null; });
  await app.screenshot("recipe-grouped-steps-selected-mobile");

  const relation = graph.relations.find((item) => item.type === "HAS_MAIN_INGREDIENT")!;
  const target = graph.entities.find((entity) => entity.id === relation.target_id)!;
  await screen.getByLabel("搜索当前图谱实体", { exact: true }).fill(target.name);
  await screen.getByRole("button", `${target.name} · 食材`, { exact: true }).tap();
  await expect(browser.locator(".graph-inspector h3")).toHaveText(target.name);
  await browser.locator(".graph-connection").first().tap();
  await expect(browser.locator(".graph-inspector")).toContainText(relation.type);
  await expect(browser.locator(".graph-inspector")).toContainText(relation.evidence[0].quote);
  await app.screenshot("recipe-fifteen-node-selected-evidence-mobile");
});

test("real recipe workspace reads stored identities and supports the source picker at desktop and mobile sizes", async ({ app, browser, screen }) => {
  const password = process.env.GUSTOBOT_TEST_ADMIN_PASSWORD;
  if (!password) throw new Error("GUSTOBOT_TEST_ADMIN_PASSWORD is required for the real recipe workspace test.");
  await browser.setViewport({ width: 1440, height: 900 });
  const response = browser.waitForResponse("**/api/v1/ontology/admin/source-facts?**", { timeout: 30_000 });
  await app.open("/admin.html?view=recipes");
  await screen.getByLabel("管理员密码", { exact: true }).fill(password);
  await screen.getByRole("button", "登录", { exact: true }).tap();
  const returned = await response;
  expect(returned.status).toBe(200);
  const facts = await returned.json() as FactResult;
  expect(facts.entities.length > 0).toBe(true);
  await expect(browser.locator(".graph-node")).toHaveCount(facts.entities.length);
  await expect(browser.locator(".graph-edge")).toHaveCount(facts.relations.length);
  if (facts.relations.length) {
    const relation = facts.relations[0];
    const source = facts.entities.find((entity) => entity.id === relation.source_id)!;
    const target = facts.entities.find((entity) => entity.id === relation.target_id)!;
    await screen.getByRole("button", `关系：${relation.type}，${source.name} → ${target.name}`, { exact: true }).first().tap();
    await expect(browser.locator(".graph-inspector")).toContainText(relation.type);
    if (relation.evidence.length) await expect(browser.locator(".graph-inspector")).toContainText(relation.evidence[0].quote);
  }
  await app.screenshot("real-recipe-graph-1440");
  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  const picker = screen.getByRole("dialog", "选择菜谱", { exact: true });
  await expect(picker.getByRole("button", /^核对资料：/).first()).toBeVisible();
  await app.screenshot("real-recipe-picker-1440");
  await browser.keyboard.press("Escape");
  await expect(browser.locator("dialog[open]")).toHaveCount(0);
  expect(await browser.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? null)).toBe("选择菜谱");

  await browser.setViewport({ width: 390, height: 844 });
  await browser.evaluate(() => { window.scrollTo(0, 0); return null; });
  await expect(browser.locator(".graph-node")).toHaveCount(facts.entities.length);
  expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await app.screenshot("real-recipe-graph-390");
  await screen.getByRole("button", "选择菜谱", { exact: true }).tap();
  await expect(picker.getByRole("button", /^核对资料：/).first()).toBeVisible();
  expect(await browser.evaluate(() => {
    const dialog = document.querySelector("dialog[open]")!.getBoundingClientRect();
    return dialog.left >= 0 && dialog.right <= window.innerWidth && dialog.top >= 0 && dialog.bottom <= window.innerHeight;
  })).toBe(true);
  await app.screenshot("real-recipe-picker-390");
  await screen.getByRole("button", "关闭菜谱选择", { exact: true }).tap();
  await expect(browser.locator("dialog[open]")).toHaveCount(0);
  expect(await browser.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? null)).toBe("选择菜谱");
});
