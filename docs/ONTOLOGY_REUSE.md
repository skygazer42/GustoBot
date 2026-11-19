# 菜谱本体复用核查

状态：本页保留现成词汇的核查和映射依据。默认菜谱已改为正式模型编译与标准引擎执行，当前行为以[领域服务](DOMAIN_KNOWLEDGE.md)为准；术语 URI 对照本身仍不等同加载公理或具备推理。设计纠偏见[案例复核](ONTOLOGY_CASE_REVIEW.md)。

核查日期：2026-11-16。范围是现成词汇与概念模型的覆盖及本地映射，结果不代表已导入外部实例数据。当前运行契约见[领域知识服务](DOMAIN_KNOWLEDGE.md)，机器可读的复用对照见[术语映射](ontology/recipe-reference-alignment.yaml)。

## 选择结论

采用 Schema.org Recipe/HowTo 的必要子集作为基础词汇，按需对齐 FoodOn 食材与加工术语；WhatToMake 提供食材、口味、条件查询等关系参考。项目继续维护做法版本、原始用量、证据和可执行约束。定义可由现有规范裁剪，不需要先让 LLM 从零生成本体。

早期 14 项术语注释方案已由正式实现取代：[运行清单](../gustobot/config/domains/recipes.yaml)选择 `recipes.ttl` 与 `recipes.shacl.ttl`。本地 Schema.org 30.1 子集参与实际类继承；业务类、身份、数量、正向查询和答案形状由模型与执行器共同落实。WhatToMake 仍为参照，不声称其全部语义已导入；原始耗时、口味主体和 FoodOn 个别中文词义仍不猜测等价。

| 资源 | 已核实内容 | 在项目中的位置 |
| --- | --- | --- |
| [Schema.org Recipe](https://schema.org/Recipe)、[HowToStep](https://schema.org/HowToStep) | 菜谱、步骤、食材、菜系、方法、烹饪和总时间；已核对 30.1 发布 JSON-LD | 优先复用菜谱、步骤词汇，转换后保留本地类型与字段 |
| [WhatToMake](https://foodkg.github.io/whattomake.html) | 实际 RDF 声明 Recipe、Ingredient、Flavor、hasIngredient、hasCookTime，并描述条件查询场景 | 参考业务关系；用户画像、推荐和过敏推理按实际需求引入 |
| [FoodOn](https://foodon.org/) | 食物、来源、加工及食品分类术语；官方仓库提供 OWL 和稳定发布入口 | 按需确认外部术语 ID，补充食材分类与概念对齐 |
| [RecipeKG](https://github.com/IDIASLab/RecipeKG) | 已读取实际 Turtle 格式的 recipekg.owl，复用 Schema.org/WhatToMake 并扩展营养、健康相关模型 | 保留为参考；本轮基础问答不需要整体采用其健康评价模型 |

## 与当前 YAML 的对应

| 本地概念或字段 | 可复用定义 | 转换要求 |
| --- | --- | --- |
| RecipeVariant | schema:Recipe | 增加本地来源、内容版本及稳定身份 |
| CookingStep、order、instruction | schema:HowToStep、position、text | 保留做法内步骤归属、正整数顺序与唯一性 |
| 主料/辅料使用关系 | schema:supply → HowToSupply，或 wtm:hasIngredient | 主/辅角色和多次投料属于本地扩展；外部表达可能需要关系实体化 |
| 关系上的 amount_text、unit | schema:requiredQuantity、QuantitativeValue | 每项供应物属于具体做法；原文“适量”保留为 Text，不能填造数值 |
| RecipeVariant.cook_time | schema:cookTime 或 totalTime 候选 | 先确认来源“耗时”口径；明确烹饪时间或总时间后，再转换为 ISO 8601 Duration |
| 菜系、烹饪方法 | schema:recipeCuisine、cookingMethod | 本地目标节点名投影为外部文字值，不能把关系名直接当作等价属性 |
| Ingredient、Flavor | wtm:Ingredient、Flavor；FoodOn 对应食物类 | 中文名称、食材状态和粒度需要核对；近义词不自动合并 |
| Dish、VARIANT_OF、证据与版本 | 本地扩展 | 当前复用子集没有直接替代本项目的身份及证据约束 |

[HowToSupply.requiredQuantity](https://schema.org/HowToSupply) 允许文本、数值或 QuantitativeValue；[QuantitativeValue](https://schema.org/QuantitativeValue) 提供值及单位表达。关系属性可以继续用于 Neo4j 存储，未来导出 RDF 时再为每条使用关系生成供应物节点，不必为复用词汇先迁移存储。

## 源码核查中发现的边界

- Schema.org [30.1 发布定义](https://schema.org/version/latest)及其[JSON-LD 文件](https://raw.githubusercontent.com/schemaorg/schemaorg/main/data/releases/30.1/schemaorg-current-https.jsonld)已核对。外部词汇与本地的类型、基数、来源和完整性规则分别记录。
- WhatToMake [RDF 快照](https://raw.githubusercontent.com/foodkg/foodkg.github.io/e130bd2a557a0bb3df99c3a34d15412e1937cdc0/ontologies/WhatToMake.rdf)中 hasIngredient/hasCookTime 有业务定义；hasFlavor 注明 ingredient property，而本地 HAS_FLAVOR 描述做法口味，主体粒度仍需裁决，不能按名称自动等价。
- RecipeKG [实际本体](https://raw.githubusercontent.com/IDIASLab/RecipeKG/053a7934539368bcfdd0f0a362465ae5e703a0e7/Ontology/recipekg.owl)虽以 .owl 命名，内容为 Turtle；hasAmount 的 domain 为 NutrientData、range 为 xsd:float，不能据名称映射为食材投料量。hasUnit 的声明也不足以证明单位已完整约束。
- [FoodOn 官方说明与源码](https://github.com/FoodOntology/foodon)适合食物术语复用；本轮未逐个批准中文食材的外部 ID。中文“糖”仍需区分白砂糖、红糖等含义。确认后记录外部 IRI 与版本，保留本地原始名称和来源。

## 对链路与模型次数的影响

离线核对标准 → 裁剪概念与关系 → 补本地规则 → 固化 YAML。结构化记录按字段映射形成实例；文档可按此定义抽取候选。在线查询读取已加载定义和本地实例，不实时下载本体或调用模型重建定义。此复用方案不增加在线模型调用。

编译器读取本地固定定义，实际 OWL-RL 和 SHACL 在图副本上运行，支持范围外的构件和 imports 报错。SHA-256 记录离线核对的外部源快照，运行时不联网下载。语义目录由正式定义生成；版本已升级到 `2026-11-16.3`，旧模型事实与向量需要显式再导入，不能以术语注释的兼容承诺解释此次模型变更。

选用标准不提供“佛跳墙实际加几克糖”的事实，该值仍须来自具体做法及其证据；原文典故等内容继续由文档向量库检索。现有做法版本、未知值和来源校验保持其业务含义。
