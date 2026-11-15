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

export const recipeContext = [
  `${recipe.title}，${recipe.minutes}分钟，${recipe.servings}人份。`,
  `食材：${recipe.ingredients.map((ingredient) => ingredient.name + ingredient.quantity + ingredient.unit).join("、")}，另备少许食用油、盐，葱花可选。`,
  ...recipe.steps.map((step, index) => `${index + 1}. ${step.summary}`)
].join("\n");
