import axios from "axios";
import type { RecipeDetail, RecipeFilters, RecipeImage, RecipePage, RecipeSource, RecipeSummary } from "../data/recipe";

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("菜谱响应格式无效");
  }
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("菜谱文字格式无效");
  return value;
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function count(value: unknown, minimum = 0): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) throw new Error("菜谱数量格式无效");
  return value;
}

function nullableCount(value: unknown): number | null {
  return value === null ? null : count(value, 1);
}

function texts(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error("菜谱列表格式无效");
  return value.map(text);
}

function parseSource(value: unknown): RecipeSource {
  const source = record(value);
  return {
    provider: text(source.provider), record_id: text(source.record_id), url: nullableText(source.url),
    original_url: nullableText(source.original_url), license: nullableText(source.license),
    license_url: nullableText(source.license_url), license_status: nullableText(source.license_status),
    attribution: nullableText(source.attribution), revision: nullableText(source.revision)
  };
}

function parseImage(value: unknown): RecipeImage {
  const image = record(value);
  const url = text(image.url);
  if (!/^\/(?!\/)/.test(url) && !/^https?:\/\//i.test(url)) throw new Error("菜谱图片地址无效");
  return {
    url, original_url: nullableText(image.original_url), source_url: nullableText(image.source_url),
    alt: text(image.alt), role: text(image.role), step_index: nullableCount(image.step_index),
    width: nullableCount(image.width), height: nullableCount(image.height), license: nullableText(image.license),
    license_status: nullableText(image.license_status), author: nullableText(image.author)
  };
}

function parseSummary(value: unknown): RecipeSummary {
  const recipe = record(value);
  const durations = record(recipe.durations);
  const id = text(recipe.id);
  const version = text(recipe.version);
  const name = text(recipe.name);
  if (!id.trim() || !version.trim() || !name.trim()) throw new Error("菜谱身份无效");
  return {
    id, version, name, categories: texts(recipe.categories), cuisines: texts(recipe.cuisines), tags: texts(recipe.tags),
    ingredient_names: texts(recipe.ingredient_names), step_count: count(recipe.step_count),
    servings: nullableText(recipe.servings), servings_count: nullableCount(recipe.servings_count),
    durations: { prep: nullableText(durations.prep), cook: nullableText(durations.cook), total: nullableText(durations.total) },
    cover_image: recipe.cover_image === null ? null : parseImage(recipe.cover_image), source: parseSource(recipe.source)
  };
}

export function parseRecipePage(value: unknown): RecipePage {
  const page = record(value);
  if (!Array.isArray(page.items) || !Array.isArray(page.categories)) throw new Error("菜谱目录响应无效");
  return {
    items: page.items.map(parseSummary), total: count(page.total), offset: count(page.offset), limit: count(page.limit, 1),
    categories: page.categories.map((value) => {
      const category = record(value);
      return { name: text(category.name), count: count(category.count) };
    }), dataset_version: text(page.dataset_version)
  };
}

export function parseRecipeDetail(value: unknown): RecipeDetail {
  const detail = record(value);
  if (!Array.isArray(detail.ingredients) || !Array.isArray(detail.images)) throw new Error("菜谱详情响应无效");
  return {
    ...parseSummary(value), description: nullableText(detail.description),
    ingredients: detail.ingredients.map((value) => {
      const ingredient = record(value);
      return { name: text(ingredient.name), amount: nullableText(ingredient.amount), unit: nullableText(ingredient.unit), role: text(ingredient.role) };
    }), steps: texts(detail.steps), tips: texts(detail.tips), images: detail.images.map(parseImage)
  };
}

export async function listRecipes(filters: RecipeFilters, signal?: AbortSignal): Promise<RecipePage> {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "";
  const { data } = await axios.get<unknown>(`${apiBaseUrl}/api/v1/recipes`, { params: filters, signal, timeout: 20_000 });
  return parseRecipePage(data);
}

export async function readRecipe(id: string, signal?: AbortSignal): Promise<RecipeDetail> {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "";
  const { data } = await axios.get<unknown>(`${apiBaseUrl}/api/v1/recipes/${encodeURIComponent(id)}`, { signal, timeout: 20_000 });
  return parseRecipeDetail(data);
}
