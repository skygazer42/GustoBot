export interface RecipeSource {
  provider: string;
  record_id: string;
  url: string | null;
  original_url: string | null;
  license: string | null;
  license_url: string | null;
  license_status: string | null;
  attribution: string | null;
  revision: string | null;
}

export interface RecipeImage {
  url: string;
  original_url: string | null;
  source_url: string | null;
  alt: string;
  role: string;
  step_index: number | null;
  width: number | null;
  height: number | null;
  license: string | null;
  license_status: string | null;
  author: string | null;
}

export interface RecipeSummary {
  id: string;
  version: string;
  name: string;
  categories: string[];
  cuisines: string[];
  tags: string[];
  ingredient_names: string[];
  step_count: number;
  servings: string | null;
  servings_count: number | null;
  durations: { prep: string | null; cook: string | null; total: string | null };
  cover_image: RecipeImage | null;
  source: RecipeSource;
}

export interface RecipeDetail extends RecipeSummary {
  description: string | null;
  ingredients: { name: string; amount: string | null; unit: string | null; role: string }[];
  steps: string[];
  tips: string[];
  images: RecipeImage[];
}

export interface RecipePage {
  items: RecipeSummary[];
  total: number;
  offset: number;
  limit: number;
  categories: { name: string; count: number }[];
  dataset_version: string;
}

export interface RecipeFilters {
  q: string;
  category: string;
  offset: number;
  limit: number;
}

export function scaleQuantity(amount: string | null, servings: number | null, baseServings: number | null): string | null {
  if (amount === null || servings === null || baseServings === null || !Number.isFinite(servings)
    || !Number.isFinite(baseServings) || servings <= 0 || baseServings <= 0 || !/^\d+(?:\.\d+)?$/.test(amount.trim())) {
    return amount;
  }
  const scaledAmount = Number(amount) * servings / baseServings;
  return Number.isFinite(scaledAmount)
    ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(scaledAmount)
    : amount;
}

export function ingredientQuantity(ingredient: RecipeDetail["ingredients"][number], servings: number | null, baseServings: number | null): string {
  const amount = scaleQuantity(ingredient.amount, servings, baseServings);
  return [amount, ingredient.unit].filter((value) => value !== null && value.length > 0).join("") || "用量未注明";
}

export function recipeDuration(recipe: RecipeSummary): string | null {
  return recipe.durations.total ?? recipe.durations.cook
    ?? (recipe.durations.prep !== null ? `准备 ${recipe.durations.prep}` : null);
}

export function sourceUrl(source: RecipeSource): string | null {
  const url = source.url ?? source.original_url;
  return url !== null && /^https?:\/\//i.test(url) ? url : null;
}
