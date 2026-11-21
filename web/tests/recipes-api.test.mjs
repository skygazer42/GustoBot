import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "./load-typescript.mjs";

const recipeData = loadTypeScript("../src/data/recipe.ts");

function source() {
  return {
    provider: "test-catalog", record_id: "source-17", url: "https://example.com/recipe/17",
    original_url: null, license: "CC BY 4.0", license_url: "https://creativecommons.org/licenses/by/4.0/",
    license_status: "upstream-declared", attribution: "测试作者", revision: "revision-2"
  };
}

function image() {
  return {
    url: "/api/v1/recipes/media/recipe-17.jpg", original_url: "https://example.com/recipe-17.jpg",
    source_url: "https://example.com/recipe/17", alt: "原文步骤图", role: "step", step_index: 2,
    width: 640, height: 480, license: null, license_status: null, author: null
  };
}

function summary() {
  return {
    id: "recipe-17", version: "a".repeat(64), name: "测试豆腐汤", categories: ["汤"], cuisines: [],
    tags: ["豆腐"], ingredient_names: ["豆腐", "水"], step_count: 2, servings: null,
    servings_count: null, durations: { prep: null, cook: "约十分钟", total: null },
    cover_image: null, source: source()
  };
}

function detail() {
  return {
    ...summary(), description: null,
    ingredients: [
      { name: "豆腐", amount: "1–2", unit: "块", role: "main" },
      { name: "水", amount: "适量", unit: null, role: "other" },
      { name: "盐", amount: null, unit: null, role: "seasoning" }
    ],
    steps: ["豆腐切块。", "加入水煮至原文注明状态。"], tips: [], images: [image()]
  };
}

function page() {
  return {
    items: [summary()], total: 1, offset: 0, limit: 12,
    categories: [{ name: "汤", count: 1 }], dataset_version: "catalog-version-2"
  };
}

function createApi(data) {
  const requests = [];
  const axios = {
    async get(url, config) {
      requests.push({ url, config });
      return { data };
    }
  };
  return { ...loadTypeScript("../src/lib/recipes.ts", { axios }), requests };
}

test("recipe pages preserve real empty results, zero counts and pagination", () => {
  const api = createApi();
  const empty = { ...page(), items: [], total: 0, offset: 24, categories: [{ name: "汤", count: 0 }] };
  assert.deepEqual(api.parseRecipePage(empty), empty);
  assert.deepEqual(api.parseRecipePage(page()), page());
});

test("unknown recipe metadata and original qualitative quantities stay unknown", () => {
  const api = createApi();
  const parsed = api.parseRecipeDetail(detail());
  assert.deepEqual(parsed, detail());
  assert.equal(parsed.servings, null);
  assert.equal(parsed.servings_count, null);
  assert.equal(parsed.cover_image, null);
  assert.equal(parsed.description, null);
  assert.deepEqual(parsed.durations, { prep: null, cook: "约十分钟", total: null });
  assert.deepEqual(parsed.ingredients.map((ingredient) => ingredient.amount), ["1–2", "适量", null]);
  assert.deepEqual(parsed.source, source());
  assert.equal(parsed.images[0].role, "step");
  assert.equal(parsed.images[0].step_index, 2);
});

test("recipe parsers reject malformed outer data and missing recipe identity", () => {
  const api = createApi();
  for (const value of [null, [], "invalid", { ...page(), items: {} }, { ...page(), categories: null }]) {
    assert.throws(() => api.parseRecipePage(value));
  }
  for (const value of [
    { ...summary(), id: " " }, { ...summary(), version: "" }, { ...summary(), name: null },
    { ...summary(), categories: "汤" }, { ...summary(), ingredient_names: [3] }
  ]) {
    assert.throws(() => api.parseRecipePage({ ...page(), items: [value] }));
  }
});

test("recipe parsers reject invalid counts without replacing them with defaults", () => {
  const api = createApi();
  for (const value of [
    { ...page(), total: -1 }, { ...page(), offset: 1.5 }, { ...page(), limit: 0 },
    { ...page(), total: "1" }, { ...page(), total: Infinity },
    { ...page(), categories: [{ name: "汤", count: -1 }] },
    { ...page(), items: [{ ...summary(), servings_count: 0 }] },
    { ...page(), items: [{ ...summary(), step_count: -1 }] }
  ]) {
    assert.throws(() => api.parseRecipePage(value));
  }
});

test("recipe detail validates nested ingredients, steps, duration and source fields", () => {
  const api = createApi();
  for (const value of [
    { ...detail(), ingredients: null }, { ...detail(), ingredients: [{ name: "水", amount: 3, unit: null, role: "main" }] },
    { ...detail(), steps: [null] }, { ...detail(), tips: {} }, { ...detail(), images: null },
    { ...detail(), durations: { prep: null, cook: 10, total: null } },
    { ...detail(), source: { ...source(), provider: null } }
  ]) {
    assert.throws(() => api.parseRecipeDetail(value));
  }
});

test("image parsing rejects executable URL schemes and invalid image dimensions", () => {
  const api = createApi();
  for (const url of ["javascript:alert(1)", "data:image/svg+xml,<svg>", "file:///tmp/photo.jpg", "//example.com/photo.jpg"]) {
    assert.throws(() => api.parseRecipeDetail({ ...detail(), images: [{ ...image(), url }] }));
  }
  for (const invalid of [{ ...image(), width: 0 }, { ...image(), step_index: -1 }, { ...image(), height: "480" }]) {
    assert.throws(() => api.parseRecipeDetail({ ...detail(), images: [invalid] }));
  }
  assert.equal(api.parseRecipeDetail({ ...detail(), images: [{ ...image(), width: null, height: null }] }).images[0].width, null);
});

test("catalog requests forward filters and abort signals and validate returned data", async () => {
  const api = createApi(page());
  const filters = { q: "豆腐 水", category: "汤", offset: 12, limit: 12 };
  const controller = new AbortController();
  assert.deepEqual(await api.listRecipes(filters, controller.signal), page());
  assert.equal(api.requests[0].url, "/api/v1/recipes");
  assert.deepEqual(api.requests[0].config.params, filters);
  assert.equal(api.requests[0].config.signal, controller.signal);
  assert.ok(api.requests[0].config.timeout > 0);
  await assert.rejects(() => createApi({ items: [] }).listRecipes(filters));
});

test("detail requests encode recipe identity as one path segment and preserve cancellation", async () => {
  const api = createApi(detail());
  const controller = new AbortController();
  assert.deepEqual(await api.readRecipe("来源/豆腐?variant=2", controller.signal), detail());
  assert.equal(api.requests[0].url, `/api/v1/recipes/${encodeURIComponent("来源/豆腐?variant=2")}`);
  assert.equal(api.requests[0].config.signal, controller.signal);
  await assert.rejects(() => createApi({ id: "partial" }).readRecipe("partial"));
});

test("network and missing recipe failures remain failures without static fallback data", async () => {
  const failure = new Error("catalog unavailable");
  const api = loadTypeScript("../src/lib/recipes.ts", { axios: { get: async () => { throw failure; } } });
  await assert.rejects(() => api.listRecipes({ q: "", category: "", offset: 0, limit: 12 }), (error) => error === failure);
  await assert.rejects(() => api.readRecipe("missing-recipe"), (error) => error === failure);
});

test("recipe labels preserve missing quantities and only use recorded durations and links", () => {
  assert.equal(recipeData.ingredientQuantity({ name: "水", amount: null, unit: null, role: "main" }, null, null), "用量未注明");
  assert.equal(recipeData.ingredientQuantity({ name: "豆腐", amount: "1–2", unit: "块", role: "main" }, 4, 2), "1–2块");
  assert.equal(recipeData.ingredientQuantity({ name: "盐", amount: "0", unit: "克", role: "seasoning" }, 4, 2), "0克");
  assert.equal(recipeData.recipeDuration(summary()), "约十分钟");
  assert.equal(recipeData.recipeDuration({ ...summary(), durations: { prep: null, cook: null, total: null } }), null);
  assert.equal(recipeData.sourceUrl(source()), source().url);
  assert.equal(recipeData.sourceUrl({ ...source(), url: null, original_url: "https://example.com/original" }), "https://example.com/original");
  for (const url of ["javascript:alert(1)", "file:///tmp/recipe", "//example.com/recipe"]) {
    assert.equal(recipeData.sourceUrl({ ...source(), url }), null);
  }
});
