import type { Browser, WebRoute } from "@e2e-dev/web";
import { CHAT_RUN_URL, chatRunRequest, fulfillChatRun } from "./chat-run";

export function createRecipe(id: string, name: string) {
  const image = {
    url: "/src/assets/tomato-eggs.jpg", original_url: "https://example.test/tomato-eggs.jpg",
    source_url: "https://example.test/recipes/tomato-eggs", alt: "番茄与鸡蛋的原文配图",
    role: "hero", step_index: null as number | null, width: 1280, height: 800,
    license: "Unlicense", license_status: "repository_declared", author: "验收资料作者",
  };
  return {
    id, version: "a".repeat(64), name, categories: ["家常菜"], cuisines: [] as string[], tags: [] as string[],
    ingredient_names: ["番茄", "鸡蛋"], step_count: 2,
    servings: "2人份" as string | null, servings_count: 2 as number | null,
    durations: { prep: null as string | null, cook: null as string | null, total: "15分钟" as string | null },
    cover_image: image as typeof image | null,
    source: { provider: "howtocook", record_id: id, url: `https://example.test/recipes/${id}`,
      original_url: `https://example.test/recipes/${id}`, license: "Unlicense", license_url: "https://example.test/license",
      license_status: "repository_declared", attribution: "验收资料作者", revision: "fixture-revision" },
    description: "按原文记录的用料和步骤制作。" as string | null,
    ingredients: [
      { name: "番茄", amount: "2" as string | null, unit: "个" as string | null, role: "main" },
      { name: "鸡蛋", amount: "3" as string | null, unit: "个" as string | null, role: "main" },
    ],
    steps: ["鸡蛋打散，热油下锅，炒至刚凝固后盛出。", "番茄炒软出汁，倒回鸡蛋，加盐翻匀。"],
    tips: ["少许食用油和盐，按原文记录处理。"], images: [image],
  };
}

export type RecipeFixture = ReturnType<typeof createRecipe>;

export async function fulfillRecipe(route: WebRoute, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export async function installPublicRecipes(browser: Browser) {
  const tomato = createRecipe("recipe-tomato", "番茄炒蛋");
  const noodles = createRecipe("recipe-noodles", "青菜汤面");
  noodles.version = "b".repeat(64);
  noodles.categories = ["主食"];
  noodles.ingredient_names = ["面条", "青菜"];
  noodles.ingredients = [
    { name: "面条", amount: "一把", unit: null, role: "main" },
    { name: "青菜", amount: null, unit: null, role: "aux" },
  ];
  noodles.steps = ["将面条放入沸水中煮熟。", "加入青菜，按原文记录调味后盛出。"];
  noodles.servings = "1批（原作者未注明人数）";
  noodles.servings_count = null;
  noodles.durations = { prep: null, cook: null, total: null };
  noodles.cover_image = null;
  noodles.images = [];
  const state = {
    recipes: [tomato, noodles, ...Array.from({ length: 12 }, (_, index) => {
      const recipe = createRecipe(`recipe-batch-${index}`, `家常做法 ${index + 1}`);
      recipe.cover_image = null;
      recipe.images = [];
      return recipe;
    })],
    catalogFailed: false,
    detailFailures: new Set<string>(),
    detailGates: new Map<string, Promise<void>>(),
    catalogRequests: [] as Array<{ q: string; category: string; offset: number }>,
    detailRequests: [] as string[],
    chatRequests: [] as Array<{ message: string; session_id?: string; recipe_id?: string; recipe_version?: string; recipe_servings?: number }>,
  };
  await browser.route("**/api/v1/recipes**", async (route) => {
    const url = new URL(route.request.url);
    if (url.pathname === "/api/v1/recipes" || url.pathname === "/api/v1/recipes/") {
      if (state.catalogFailed) return fulfillRecipe(route, { detail: "菜谱目录暂时不可用" }, 503);
      const q = url.searchParams.get("q") ?? "";
      const category = url.searchParams.get("category") ?? "";
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 12);
      state.catalogRequests.push({ q, category, offset });
      const terms = q.trim().split(/\s+/).filter(Boolean);
      const matching = state.recipes.filter((recipe) => (
        (!category || recipe.categories.includes(category))
        && terms.every((term) => [recipe.name, ...recipe.ingredient_names, ...recipe.categories].join(" ").includes(term))
      ));
      const counts = new Map<string, number>();
      for (const recipe of state.recipes) for (const name of recipe.categories) counts.set(name, (counts.get(name) ?? 0) + 1);
      return fulfillRecipe(route, { items: matching.slice(offset, offset + limit), total: matching.length, offset, limit,
        categories: [...counts].map(([name, count]) => ({ name, count })), dataset_version: "d".repeat(64) });
    }
    const id = decodeURIComponent(url.pathname.slice("/api/v1/recipes/".length));
    state.detailRequests.push(id);
    const recipe = state.recipes.find((item) => item.id === id);
    if (!recipe) return fulfillRecipe(route, { detail: "菜谱不存在" }, 404);
    const gate = state.detailGates.get(id);
    if (gate) await gate;
    if (state.detailFailures.has(id)) return fulfillRecipe(route, { detail: "这份菜谱暂时无法读取" }, 503);
    return fulfillRecipe(route, recipe);
  });
  await browser.route(CHAT_RUN_URL, (route) => {
    const request = chatRunRequest(route) as typeof state.chatRequests[number];
    state.chatRequests.push(request);
    const recipe = state.recipes.find((item) => item.id === request.recipe_id);
    return fulfillChatRun(route, { message: recipe ? `已根据《${recipe.name}》原文核对当前问题。` : "请说明要核对哪份资料。",
      session_id: `session-${state.chatRequests.length}`, route: recipe ? "recipe-query" : "knowledge-query",
      sources: recipe ? [{ name: recipe.name, source: recipe.name, url: recipe.source.url, recipe_id: recipe.id, recipe_version: recipe.version }] : [],
      metadata: { status: "success" } });
  });
  return state;
}
