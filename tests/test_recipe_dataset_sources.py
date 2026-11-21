"""HowToCook 解析器的离线数据完整性与来源边界测试。"""

import pytest

from scripts.recipe_dataset_sources import parse_howtocook_recipe

REVISION = "58c1b9af7900a9489c340bca39ef94a9a62314b1"


def test_preserves_formulas_nested_steps_and_optional_ingredient() -> None:
    """份数公式不应被换算；操作子项留在所属步骤而不是被静默丢弃。"""
    recipe = parse_howtocook_recipe(
        """# 西红柿炒鸡蛋的做法

简单的家常菜。

## 必备原料和工具
* 西红柿
* 鸡蛋
* 糖（可选）
## 计算
一份正好够 1 个人食用。
* 西红柿 = 1 个（约 180g） * 份数
* 鸡蛋 = 1.5 个 * 份数，向上取整
* 糖 = 0-2g * 份数
## 操作
1. 西红柿洗净。
2. 去掉外皮。

  - 开水烫表皮，然后放入冷水。

3. 加鸡蛋翻炒。
  - 注意：不要洗锅。
## 附加内容
* 糖可不放。
如果您遵循本指南的制作流程而发现有问题或可以改进的流程，请提出 Issue 或 Pull request 。
""",
        "dishes/vegetable_dish/西红柿炒鸡蛋.md",
        REVISION,
    )
    assert recipe is not None
    assert recipe["name"] == "西红柿炒鸡蛋"
    assert recipe["ingredients"][1] == {
        "name": "鸡蛋",
        "amount": "1.5 个 * 份数，向上取整",
        "unit": None,
    }
    assert recipe["ingredients"][2]["name"] == "糖"
    assert "糖（可选）" in recipe["ingredients_raw"]
    assert len(recipe["steps"]) == 3
    assert "开水烫表皮，然后放入冷水" in recipe["steps"][1]
    assert "不要洗锅" in recipe["steps"][2]
    assert recipe["tips"][0] == "糖可不放。"
    assert recipe["durations"] == {"prep": None, "cook": None, "total": None}
    assert recipe["servings"] is None
    assert recipe["cuisines"] == []


def test_excludes_tools_and_preserves_compound_ingredients_and_longest_match() -> None:
    """原料表夹杂工具时保留说明，水淀粉不能误匹配成水的用量。"""
    recipe = parse_howtocook_recipe(
        """# 测试菜的做法
## 必备原料和工具
- 工具：`平底锅`
- 主料：`鸡肉`
- 辅料：`水`、`水淀粉`、`盐（推荐海盐）`
- 菜刀一个
- 盆（两个）
## 计算
- 水淀粉 = 20g
- 水 = 50g
- 盐：2g
## 操作
- 混合食材。
""",
        "dishes/meat_dish/测试菜.md",
        REVISION,
    )
    assert recipe is not None
    ingredients = {item["name"]: item for item in recipe["ingredients"]}
    assert set(ingredients) == {"鸡肉", "水", "水淀粉", "盐"}
    assert ingredients["水淀粉"]["amount"] == "20g"
    assert ingredients["水"]["amount"] == "50g"
    assert any("平底锅" in tip for tip in recipe["tips"])
    assert "工具：`平底锅`" in recipe["ingredients_raw"]


def test_pins_local_images_and_does_not_license_external_images() -> None:
    """同仓相对图使用固定版本，第三方图不得继承 Unlicense。"""
    recipe = parse_howtocook_recipe(
        """# 牛排的做法
![牛排成品](./牛排.jpg)
![参考图](https://example.org/photo.jpg)
![危险图](../../private.jpg)
![协议图](javascript:alert)
## 必备原料和工具
- 牛排
## 操作
1. 加热平底锅。
2. ![煎制](./煎制.jpg)
   煎熟后出锅。
3. ![成品](./成品.jpg)
""",
        "dishes/meat_dish/牛排/牛排.md",
        REVISION,
    )
    assert recipe is not None
    images = recipe["images"]
    assert len(images) == 4
    assert images[0]["role"] == "hero"
    assert f"/{REVISION}/" in images[0]["url"]
    assert "%E7%89%9B%E6%8E%92.jpg" in images[0]["url"]
    assert images[0]["license"] == "Unlicense"
    assert images[1]["license"] == "unknown"
    assert images[1]["license_status"] == "review_required"
    assert images[2]["role"] == "step"
    assert images[2]["step_index"] == 2
    assert images[3]["role"] == "hero"
    assert recipe["source"]["url"].startswith(
        f"https://github.com/Anduin2017/HowToCook/blob/{REVISION}/"
    )


def test_preserves_subsection_steps_and_calculation_notes() -> None:
    """备料、烹饪分节重新编号时仍保持源文顺序。"""
    recipe = parse_howtocook_recipe(
        """# 牛排的做法
## 必备原料和工具
- 牛排
- 黑胡椒
## 计算
每份供两人食用。
- 牛排 450-500g（两片牛排）
## 操作
### 备料
1. 解冻。
   - 提前一晚冷藏。
### 烹饪
注：适用于 2-3cm 厚的牛排。
1. 双面煎制。
2. 醒肉。
## 附加内容
### 火候
- 不要干烧。
""",
        "dishes/meat_dish/牛排.md",
        REVISION,
    )
    assert recipe is not None
    assert "备料：解冻" in recipe["steps"][0]
    assert "提前一晚冷藏" in recipe["steps"][0]
    assert "烹饪：注：适用于" in recipe["steps"][1]
    assert "双面煎制" in recipe["steps"][2]
    assert recipe["ingredients"][0]["amount"] == "450-500g（两片牛排）"
    assert any("每份供两人" in tip for tip in recipe["tips"])


@pytest.mark.parametrize("path", ["../private.md", "/dishes/菜.md", "dishes/../菜.md"])
def test_rejects_outside_recipe_paths(path: str) -> None:
    """仓库记录路径不能逃逸或伪装为绝对路径。"""
    with pytest.raises(ValueError, match="relative dishes"):
        parse_howtocook_recipe("# 菜的做法", path, REVISION)


def test_rejects_mutable_revision_and_skips_templates_and_incomplete_documents() -> None:
    """只接受完整提交号；模板与缺少操作的资料不计入有效菜谱。"""
    with pytest.raises(ValueError, match="immutable"):
        parse_howtocook_recipe("# 菜的做法", "dishes/菜.md", "master")
    assert parse_howtocook_recipe("# 示例菜的做法", "dishes/template/示例菜.md", REVISION) is None
    assert parse_howtocook_recipe("# 菜的做法\n## 必备原料和工具\n- 水", "dishes/菜.md", REVISION) is None


def test_separates_quantity_first_ingredients_tool_groups_and_prose() -> None:
    """中文甜品的前置计量及工具小节不应变成名为 125ml 或工具的食材。"""
    recipe = parse_howtocook_recipe(
        """# 咖啡椰奶冻的做法
## 必备原料和工具
- 原料:
  - 125ml 淡奶油
  - 250ml 椰汁
  - 猪肉末（肥瘦 3:7，注释内数字不是份量）
  - 必备：鸡蛋
  - （可选）：糖
- 工具
  - 雪克杯
  - 蒸鱼盘子（能平放下一条鱼即可）
### 所需原料
- 吉利丁
### 所必要的工具
- 布
- 硅油纸或模具
## 计算
- 125ml 淡奶油(whipping cream, 35% M.E)
- 250ml 椰汁
- 猪肉末 300g
- 一个水饺约需要本身体积两倍的水
- 糖（可选）
## 操作
1. 混合材料。
2. 冷藏成型。
""",
        "dishes/dessert/咖啡椰奶冻.md",
        REVISION,
    )
    assert recipe is not None
    ingredients = {item["name"]: item for item in recipe["ingredients"]}
    assert set(ingredients) == {"淡奶油", "椰汁", "猪肉末", "鸡蛋", "糖", "吉利丁"}
    assert ingredients["淡奶油"]["amount"] == "125ml (whipping cream, 35% M.E)"
    assert ingredients["猪肉末"]["amount"] == "300g"
    assert any("水饺约需要" in tip for tip in recipe["tips"])


def test_preserves_each_stage_amount_instead_of_overwriting_marinade() -> None:
    """同一原料在腌料和酱汁中的剂量均须保留，不能只剩最后一项。"""
    recipe = parse_howtocook_recipe(
        """# 黄油鸡的做法
## 必备原料和工具
- 鸡腿肉
- 盐
- 生姜
## 计算
**腌鸡部分：**
- 鸡腿肉 500g
- 盐 3g
- 生姜 10g，磨碎
**酱汁部分：**
- 盐 5g
- 生姜 10g
## 操作
1. 腌制鸡肉。
2. 加入酱汁烧熟。
""",
        "dishes/meat_dish/黄油鸡.md",
        REVISION,
    )
    assert recipe is not None
    ingredients = {item["name"]: item for item in recipe["ingredients"]}
    assert ingredients["盐"]["amount"] == "腌鸡部分：3g；酱汁部分：5g"
    assert ingredients["生姜"]["amount"] == "腌鸡部分：10g，磨碎；酱汁部分：10g"


def test_preserves_nested_dough_amounts_and_numbering_without_spaces() -> None:
    """真实面包格式含无空格编号和分组配方，应保留每阶段原料与步骤。"""
    recipe = parse_howtocook_recipe(
        """# 基础牛奶面包的做法
## 必备原料和工具
- 面粉 *（尽量使用高筋面粉）*
- 黄油
## 计算
- **酵头**
  - 面粉 1 cup
- **面团**
  - 面粉 2½ cup
  - 黄油 ⅛ cup
## 操作
1.将原料混合。
2.静置发酵。
  - 避免放在过冷处。
3.烘烤至熟。
""",
        "dishes/staple/基础牛奶面包.md",
        REVISION,
    )
    assert recipe is not None
    ingredients = {item["name"]: item for item in recipe["ingredients"]}
    assert ingredients["面粉"]["amount"] == "酵头：1 cup；面团：2½ cup"
    assert ingredients["黄油"]["amount"] == "面团：⅛ cup"
    assert len(recipe["steps"]) == 3
    assert "避免放在过冷处" in recipe["steps"][1]


def test_keeps_quantity_first_serving_formulas_and_syrup_ratio() -> None:
    """前置计量不能吞掉份数乘数；糖浆 1:1 配比保留于提示。"""
    recipe = parse_howtocook_recipe(
        """# 调味汁的做法
## 必备原料和工具
- 油麦菜
- 芝麻酱
- 蔗糖糖浆
## 计算
- 1 颗 油麦菜（约 200g） * 份数
- 10ml 芝麻酱 * 份数
- 1 : 1 蔗糖糖浆 30~40 克
## 操作
1. 混合。
""",
        "dishes/condiment/调味汁.md",
        REVISION,
    )
    assert recipe is not None
    ingredients = {item["name"]: item for item in recipe["ingredients"]}
    assert set(ingredients) == {"油麦菜", "芝麻酱", "蔗糖糖浆"}
    assert "* 份数" in ingredients["油麦菜"]["amount"]
    assert ingredients["芝麻酱"]["amount"] == "10ml * 份数"
    assert ingredients["蔗糖糖浆"]["amount"] == "30~40 克"
    assert any("1 : 1 蔗糖糖浆" in tip for tip in recipe["tips"])


def test_image_captions_do_not_create_fake_cooking_steps() -> None:
    """纯图片应只保存在图片列表，不能将成品图 alt 作为烹饪动作。"""
    recipe = parse_howtocook_recipe(
        """# 测试菜的做法
## 必备原料和工具
- 鸡蛋
## 操作
1. 将鸡蛋煎熟。
![测试菜-预览图-1](./煎蛋.jpg)
2. 盛盘。
3. ![测试菜-预览图-2](./成品.jpg)
""",
        "dishes/meat_dish/测试菜/测试菜.md",
        REVISION,
    )
    assert recipe is not None
    assert recipe["steps"] == ["将鸡蛋煎熟。", "盛盘。"]
    assert len(recipe["images"]) == 2
    assert recipe["images"][0]["step_index"] == 1
    assert recipe["images"][1]["role"] == "hero"
