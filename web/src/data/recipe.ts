import photo from "../assets/tomato-eggs.jpg";

export const recipe = {
  id: "tomato-eggs",
  title: "番茄炒蛋",
  description: "酸甜恰好，趁热拌进一碗米饭里。",
  minutes: 15,
  servings: 2,
  photo,
  ingredients: [
    { id: "tomato", name: "番茄", quantity: "2", unit: "个", question: "怎样挑适合炒蛋的番茄？" },
    { id: "egg", name: "鸡蛋", quantity: "3", unit: "个", question: "只有一个鸡蛋，番茄要放多少？" }
  ],
  steps: [
    {
      id: "eggs",
      title: "先炒鸡蛋，留一点嫩",
      lead: "鸡蛋打散，热油下锅。",
      before: "炒到",
      highlight: "刚凝固",
      after: "就盛出，别等到发干。",
      summary: "鸡蛋打散，热油下锅，炒至刚凝固盛出。",
      question: "怎么判断鸡蛋刚凝固？"
    },
    {
      id: "tomatoes",
      title: "番茄出汁，再合在一起",
      lead: "",
      before: "番茄切块，入锅炒软。等",
      highlight: "汁水",
      after: "出来，倒回鸡蛋，加盐，轻轻翻匀就好。",
      summary: "番茄炒软出汁，倒回鸡蛋，加盐翻匀。",
      question: "番茄要炒到什么程度再放鸡蛋？"
    }
  ]
} as const;

export function scaleQuantity(quantity: string, servings: number, baseServings: number = recipe.servings): string {
  const amount = Number(quantity);
  return quantity.trim() && Number.isFinite(amount)
    ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(amount * servings / baseServings)
    : quantity;
}

export function buildRecipeContext(servings: number): string {
  return [
    `${recipe.title}，来源标注${recipe.minutes}分钟，原份量${recipe.servings}人份，当前调整为${servings}人份。`,
    `食材按份量等比例换算：${recipe.ingredients.map((ingredient) => ingredient.name + scaleQuantity(ingredient.quantity, servings) + ingredient.unit).join("、")}。少许食用油、盐和可选葱花保持原记录，不估算用量。`,
    ...recipe.steps.map((step, index) => `${index + 1}. ${step.summary}`)
  ].join("\n");
}
