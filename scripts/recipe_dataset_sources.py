"""将 HowToCook 原始 Markdown 转为带来源和图片声明的菜谱记录。"""

import hashlib
import posixpath
import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit, urlunsplit

_REPOSITORY = "Anduin2017/HowToCook"
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]\s+|\d+[.)、](?:\s+|(?=\D)))(.*)$")
_HEADING = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_ATTRIBUTE = re.compile(r"(src|alt)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)
_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\([^()]*(?:\([^()]*\)[^()]*)*\)")
_CATEGORIES = {
    "aquatic": "水产",
    "breakfast": "早餐",
    "condiment": "调味料",
    "dessert": "甜品",
    "drink": "饮品",
    "meat_dish": "荤菜",
    "semi-finished": "半成品",
    "soup": "汤羹",
    "staple": "主食",
    "vegetable_dish": "素菜",
}
_TOOLS = {
    "锅",
    "平底锅",
    "铁锅",
    "炒锅",
    "砂锅",
    "高压锅",
    "电压力锅",
    "蒸锅",
    "电饭煲",
    "空气炸锅",
    "烤箱",
    "微波炉",
    "冰箱",
    "电磁炉",
    "燃气灶",
    "热水壶",
    "刀",
    "菜刀",
    "水果刀",
    "厨房剪刀",
    "剪刀",
    "砧板",
    "案板",
    "筷子",
    "碗",
    "盘",
    "盘子",
    "盆",
    "笊篱",
    "锅铲",
    "铲子",
    "漏勺",
    "汤匙",
    "勺子",
    "搅拌机",
    "榨汁机",
    "破壁机",
    "打蛋器",
    "锡箔纸",
    "锡纸",
    "厨房纸",
    "保鲜膜",
    "滤网",
    "漏网",
    "电子秤",
    "计量秤",
    "手套",
    "竹签",
    "烘焙纸",
    "吸油纸",
    "托盘",
    "蒸笼",
    "温度计",
    "量杯",
    "量勺",
    "手动压汁器",
    "雪克瓶",
    "雪克杯",
    "过滤网",
    "擀面杖",
    "蒸笼垫",
    "粉碎机",
    "分蛋器",
    "硅胶垫",
    "披萨石",
    "烘焙刮刀",
    "搅拌器",
    "筛网",
    "防烫盘夹",
}
_AMOUNT_PREFIX = re.compile(
    r"^((?:约\s*)?(?:\d+(?:[./~～-]\d+)*|[一二三四五六七八九十两半几]+)\s*"
    r"(?:kg|ml|mL|cm|g|L|升|毫升|公斤|千克|克|斤|袋|盒|个|根|颗|片|只|条|勺|匙|段|块))\s*(.+)$"
)
# 只在原料表中恰有一个对应名称时归并，计量仍逐字保留上游内容。
_INGREDIENT_ALIASES = (
    {"姜", "生姜"},
    {"蒜", "大蒜"},
    {"葱", "小葱", "大葱"},
    {"五花肉", "猪五花肉"},
    {"鸡翅", "鸡翅中"},
)


def _plain_text(text: str) -> str:
    """移除展示标记，保留图片替代文本、列表内容和计量公式。"""
    text = _IMAGE.sub(lambda match: match.group(1), text)
    text = _HTML_IMAGE.sub("", text)
    text = _LINK.sub(lambda match: match.group(1), text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("`", "").replace("**", "").replace("__", "")
    return text.strip()


def _section_kind(title: str) -> str:
    """识别上游实际章节；不将备料或附注混入操作步骤。"""
    title = _plain_text(title)
    if re.search(r"必备|所需|原料|食材|材料", title):
        return "ingredients"
    if re.search(r"计算|用量|份量|分量", title):
        return "calculation"
    if re.search(r"操作|做法|步骤|制作|烹饪", title):
        return "steps"
    return "tips"


def _is_tool(text: str) -> bool:
    """排除明确标注的工具及器具名称，不以单字前缀误伤食材。"""
    if re.match(r"^(?:工具|厨具|器具|注|注意)(?:[：:]|$)", text):
        return True
    base = re.split(r"[（(，,：:]", text, maxsplit=1)[0].strip()
    base = re.sub(r"(?:若干|[一二三四五六七八九十\d]+\s*[个把只台张对])$", "", base).strip()
    if re.search(
        r"(?:锅|碗|盘|盘子|盆|刀|铲|纸|保鲜膜|模具|锅盖|烤架|手套|烤箱|微波炉|电蒸炉|料理机|克称|克数称|压汁器|搅拌工具|盘夹)$",
        base,
    ):
        return True
    return any(
        base == tool
        or re.match(re.escape(tool) + r"\s+", base)
        or re.fullmatch(re.escape(tool) + r"\s*[一二三四五六七八九十\d]*[个把只台张对]?", base)
        for tool in _TOOLS
    )


def _split_ingredients(text: str, separators: str = "、，,+") -> list[str]:
    """拆分主料/辅料组合行，括号内说明与复合原料名保持完整。"""
    text = re.sub(r"^[（(]可选[）)]\s*[：:]\s*", "", text)
    text = re.sub(r"^(?:必备|可选)[：:]\s*", "", text)
    text = re.sub(r"^(?:主料|辅料|配料|原料|调料|食材|炒料|调味料|其他调味料)[：:]\s*", "", text)
    parts = []
    start = depth = 0
    for index, char in enumerate(text):
        if char in "（(":
            depth += 1
        elif char in "）)":
            depth = max(0, depth - 1)
        elif char in separators and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def _ingredient_name(text: str) -> str:
    """取得原料匹配名，展示说明仍保存在 ingredients_raw 中。"""
    text = re.sub(r"^\[?可选\]?\s*[：:]?\s*", "", text)
    previous = None
    while text != previous:
        previous = text
        text = re.sub(r"[（(][^（）()]*[）)]", "", text)
    text = re.sub(r"(?:[—-]\s*)?可选.*$", "", text)
    return re.sub(r"各$", "", text.strip(" *：:").rstrip("。；;"))


def _ingredient_note(text: str) -> bool:
    """识别份量、火候和器具说明，避免把整句说明注册为食材。"""
    return (
        not text
        or len(text) > 24
        or "?" in text
        or "？" in text
        or bool(re.match(r"^\d", text))
        or bool(
            re.match(
                r"^(?:注|注意|建议|参见|一般|每份|每次|一份|基于|按照|如果|若|可选|原料|工具|辅料|配料)[：:]?",
                text,
            )
        )
        or bool(
            re.search(
                r"过程|分钟|时间|用量为|可准备|需要|容量|体积|质量|家庭用量|建议选择|的用量", text
            )
        )
    )


def _ingredient_pair(text: str, names: list[str]) -> tuple[str, str | None]:
    """优先匹配完整原料名，再识别明确分隔符或数量起点。"""
    text = text.strip().rstrip("。；;")
    # 1:1 是糖浆配比，不是名为“1”的原料；配比原文另留在用量说明。
    ratio = re.match(r"^\d+\s*:\s*\d+\s+(.+)$", text)
    if ratio:
        return _ingredient_pair(ratio.group(1), names)
    prefix_amount = _AMOUNT_PREFIX.match(text)
    if prefix_amount:
        rest = prefix_amount.group(2)
        formula = re.search(r"\s*\*\s*份数.*$", rest)
        if formula:
            rest = rest[: formula.start()]
        name, remainder = _ingredient_pair(rest, names)
        amount = prefix_amount.group(1)
        if remainder is not None:
            amount += " " + remainder
        if formula:
            amount += " " + formula.group().strip()
        return name, amount
    parenthesized_name = re.match(r"^[（(]([^（）()]+)[）)]\s*(\d.+)$", text)
    if parenthesized_name:
        return parenthesized_name.group(1).strip(), parenthesized_name.group(2).strip()
    for name in sorted(names, key=len, reverse=True):
        if text.startswith(name):
            remainder = text[len(name) :]
            if not remainder or re.match(
                r"^[\s=:：\d约半一二三四五六七八九十两少适（(]", remainder
            ):
                amount = remainder.lstrip(" =:：").strip()
                return name, amount if amount else None
    # 只在括号外寻找数量或分隔符；肥瘦 3:7 及可选说明不是名称的一部分。
    depth = 0
    for index, char in enumerate(text):
        if char in "（(":
            depth += 1
        elif char in "）)":
            depth = max(0, depth - 1)
        elif depth == 0 and char in "=:：0123456789¼½¾⅛⅜⅝⅞⅓⅔":
            name = _ingredient_name(text[:index])
            if name:
                amount = text[index:].lstrip(" =:：").strip()
                return name, amount if amount else None
            break
    match = re.match(
        r"^(.+?)\s*([一二三四五六七八九十两半几]+(?:小)?(?:个|根|颗|片|只|条|勺|匙|段|块).*)$", text
    )
    if match:
        return _ingredient_name(match.group(1)), match.group(2).strip()
    match = re.match(r"^(.+?)\s+(约|少许|适量|大约)(.+)$", text)
    if match:
        return _ingredient_name(match.group(1)), (match.group(2) + match.group(3)).strip()
    parenthetical_amount = re.match(r"^([^（）()]+)[（(]((?:\d|约\s*\d).*)[）)]$", text)
    if parenthetical_amount:
        return parenthetical_amount.group(1).strip(), parenthetical_amount.group(2).strip()
    return _ingredient_name(text), None


def _parse_ingredients(
    sections: dict[str, list[tuple[int, str]]],
) -> tuple[list[dict], list[str], list[str]]:
    """合并原料和计算章节；无法确定的公式不换算成臆测的固定份量。"""
    ingredients: dict[str, dict] = {}
    raw_lines = []
    notes = []
    tool_section = False
    for _line_number, line in sections["ingredients"]:
        heading = _HEADING.match(line)
        label = _plain_text(heading.group(2) if heading else line).strip(" ：:")
        match = _LIST_ITEM.match(line)
        if match:
            label = _plain_text(match.group(2)).strip(" ：:")
        if heading:
            tool_section = bool(re.search(r"工具|厨具|器具", label))
            continue
        if label in {"工具", "厨具", "器具", "原料", "主料", "辅料", "材料", "食材", "香料"}:
            tool_section = label in {"工具", "厨具", "器具"}
            continue
        if not match:
            continue
        raw = match.group(2).strip()
        raw_lines.append(raw)
        text = _plain_text(raw)
        if tool_section or _is_tool(text):
            notes.append(f"原料与工具说明：{text}")
            continue
        for part in _split_ingredients(text):
            if _is_tool(part):
                notes.append(f"工具：{part}")
                continue
            name, amount = _ingredient_pair(part, [])
            if _is_tool(name):
                notes.append(f"工具：{part}")
            elif _ingredient_note(name):
                notes.append(f"原料说明：{part}")
            elif name:
                ingredients[name] = {"name": name, "amount": amount, "unit": None}

    calculated_amounts: dict[str, list[tuple[str, str]]] = {}
    calculation_section = ""
    calculation_lines = sections["calculation"]
    for position, (_line_number, line) in enumerate(calculation_lines):
        match = _LIST_ITEM.match(line)
        if not match:
            text = _plain_text(line)
            heading = _HEADING.match(line)
            if heading:
                calculation_section = _plain_text(heading.group(2)).rstrip("：:")
            elif line.strip().startswith("**") and line.strip().endswith("**"):
                calculation_section = text.rstrip("：:")
            if text and not _HEADING.match(line):
                notes.append(f"用量说明：{text}")
            continue
        text = _plain_text(match.group(2))
        if not text:
            continue
        next_item = next(
            (
                _LIST_ITEM.match(next_line)
                for _, next_line in calculation_lines[position + 1 :]
                if next_line.strip()
            ),
            None,
        )
        if next_item is not None and len(next_item.group(1)) > len(match.group(1)):
            calculation_section = text.rstrip("：:")
            notes.append(f"用量说明：{text}")
            continue
        if re.match(r"^\d+\s*:\s*\d+\s+", text):
            notes.append(f"用量说明：{text}")
        for part in _split_ingredients(text, separators="、"):
            name, amount = _ingredient_pair(part, list(ingredients))
            if _is_tool(name) or _ingredient_note(name):
                notes.append(f"用量说明：{part}")
                continue
            if amount is None:
                if name not in ingredients and re.search(r"可选", part):
                    ingredients[name] = {"name": name, "amount": None, "unit": None}
                notes.append(f"用量说明：{part}")
                continue
            for aliases in _INGREDIENT_ALIASES:
                candidates = aliases.intersection(ingredients)
                if name in aliases and len(candidates) == 1:
                    name = next(iter(candidates))
                    break
            amounts = calculated_amounts.setdefault(name, [])
            if (calculation_section, amount) not in amounts:
                amounts.append((calculation_section, amount))
            if name not in ingredients:
                ingredients[name] = {"name": name, "amount": None, "unit": None}
    for name, amounts in calculated_amounts.items():
        # 不将腌料、酱汁或酵头的用量互相覆盖，也不擅自汇总不同基准的配比。
        ingredients[name]["amount"] = "；".join(
            f"{context}：{amount}" if context else amount for context, amount in amounts
        )
    return list(ingredients.values()), raw_lines, notes


def _content_blocks(lines: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    """按顶层列表/段落分块，嵌套说明与其所属步骤一起保留。"""
    blocks: list[tuple[int, int, str]] = []
    list_indents = [len(match.group(1)) for _, line in lines if (match := _LIST_ITEM.match(line))]
    top_indent = min(list_indents) if list_indents else 0
    current: list[str] = []
    start = 0
    end = 0
    subsection = ""
    has_start = False

    def flush() -> None:
        """结束当前内容块，纯空行或装饰不生成烹饪步骤。"""
        nonlocal current, has_start
        text = "\n".join(current).strip()
        if text:
            blocks.append((start, end, text))
        current = []
        has_start = False

    for line_number, line in lines:
        heading = _HEADING.match(line)
        if heading:
            flush()
            subsection = _plain_text(heading.group(2))
            continue
        match = _LIST_ITEM.match(line)
        top_item = match is not None and len(match.group(1)) == top_indent
        if top_item:
            flush()
            start = line_number
            has_start = True
        elif not line.strip():
            continue
        elif not has_start:
            start = line_number
            has_start = True
        # 图片的 alt 是描述，不是操作；图片仍通过原始行号关联对应步骤。
        text = _plain_text(_IMAGE.sub("", match.group(2) if match else line))
        if not text:
            end = line_number
            continue
        if subsection:
            text = f"{subsection}：{text}"
            subsection = ""
        if match and not top_item:
            text = f"  - {text}"
        current.append(text)
        end = line_number
    flush()
    return blocks


def _image_url(target: str, path: str, revision: str) -> tuple[str, bool] | None:
    """解析仓库内相对图片；拒绝跨目录遍历和非 HTTP(S) 图片协议。"""
    target = target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = re.sub(r"\s+[\"'].*[\"']$", "", target).strip()
    target = unquote(target)
    if not target or "\\" in target or any(char in target for char in "\r\n\x00"):
        return None
    parts = urlsplit(target)
    if ".." in PurePosixPath(parts.path).parts:
        return None
    if parts.scheme or parts.netloc:
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
            return None
        same_repository = parts.hostname == "raw.githubusercontent.com" and parts.path.startswith(
            f"/{_REPOSITORY}/{revision}/"
        )
        encoded = urlunsplit(
            (parts.scheme, parts.netloc, quote(parts.path, safe="/"), parts.query, "")
        )
        return encoded, same_repository
    relative = PurePosixPath(parts.path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    resolved = posixpath.join(posixpath.dirname(path), parts.path)
    url = f"https://raw.githubusercontent.com/{_REPOSITORY}/{revision}/{quote(resolved, safe='/')}"
    return url, True


def parse_howtocook_recipe(markdown: str, path: str, revision: str) -> dict | None:
    """解析固定提交中的单份菜谱；模板和无完整原料/步骤的资料返回 None。

    图片 step_index 从 1 开始。未声明具体份数/耗时/菜系时保留空值；
    外部图片只记录原链接，许可须另行审核，不继承仓库的 Unlicense 声明。
    """
    recipe_path = PurePosixPath(path)
    if (
        recipe_path.is_absolute()
        or ".." in recipe_path.parts
        or "\\" in path
        or not path.startswith("dishes/")
        or not path.endswith(".md")
    ):
        raise ValueError("HowToCook recipe path must be a relative dishes/*.md path")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise ValueError("HowToCook revision must be a full immutable Git commit SHA")
    if "template" in recipe_path.parts:
        return None
    markdown = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
    sections: dict[str, list[tuple[int, str]]] = {
        "description": [],
        "ingredients": [],
        "calculation": [],
        "steps": [],
        "tips": [],
    }
    name = ""
    section = "description"
    image_lines: list[tuple[int, str, str, str]] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        heading = _HEADING.match(line)
        if heading and len(heading.group(1)) == 1 and not name:
            name = re.sub(r"的做法$", "", _plain_text(heading.group(2))).strip()
            continue
        if heading and len(heading.group(1)) == 2:
            section = _section_kind(heading.group(2))
            continue
        sections[section].append((line_number, line))
        image_lines.extend(
            (line_number, section, match.group(1), match.group(2))
            for match in _IMAGE.finditer(line)
        )
        for image in _HTML_IMAGE.finditer(line):
            attributes = {
                m.group(1).lower(): m.group(3) for m in _HTML_ATTRIBUTE.finditer(image.group())
            }
            if "src" in attributes:
                image_lines.append(
                    (line_number, section, attributes.get("alt", ""), attributes["src"])
                )
    if not name or name in {"示例菜", "菜模板", "菜谱模板", "模板"}:
        return None
    ingredients, ingredients_raw, ingredient_notes = _parse_ingredients(sections)
    step_blocks = _content_blocks(sections["steps"])
    if not ingredients or not step_blocks:
        return None
    source_url = f"https://github.com/{_REPOSITORY}/blob/{revision}/{quote(path, safe='/')}"
    images = []
    seen_images = set()
    for line_number, image_section, alt, target in image_lines:
        resolved = _image_url(target, path, revision)
        if resolved is None or resolved[0] in seen_images:
            continue
        url, same_repository = resolved
        seen_images.add(url)
        role = "step" if image_section == "steps" else "unspecified"
        if "成品" in alt or "成品" in unquote(urlsplit(url).path):
            role = "hero"
        step_index = next(
            (i for i, (start, end, _) in enumerate(step_blocks, 1) if start <= line_number <= end),
            None,
        )
        images.append(
            {
                "url": url,
                "role": role,
                "step_index": step_index,
                "alt": alt,
                "license": "Unlicense" if same_repository else "unknown",
                "license_status": "repository_declared" if same_repository else "review_required",
                "source_url": source_url,
            }
        )
    description = "\n".join(
        text for _, line in sections["description"] if (text := _plain_text(_IMAGE.sub("", line)))
    )
    tip_lines = [
        (line_number, line)
        for line_number, line in sections["tips"]
        if "请提出 Issue 或 Pull request" not in line
    ]
    tips = [text for _, _, text in _content_blocks(tip_lines)]
    tips.extend(ingredient_notes)
    category = _CATEGORIES.get(recipe_path.parts[1])
    return {
        "id": "howtocook:" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:20],
        "name": name,
        "language": "zh-CN",
        "description": description,
        "ingredients": ingredients,
        "ingredients_raw": ingredients_raw,
        "steps": [text for _, _, text in step_blocks],
        "tips": tips,
        "categories": [category] if category is not None else [],
        "cuisines": [],
        "images": images,
        "source": {
            "provider": "howtocook",
            "record_id": path,
            "url": source_url,
            "original_url": source_url,
            "license": "Unlicense",
            "license_url": f"https://github.com/{_REPOSITORY}/blob/{revision}/LICENSE",
            "license_status": "repository_declared",
            "attribution": "HowToCook contributors",
            "revision": revision,
        },
        "durations": {"prep": None, "cook": None, "total": None},
        "servings": None,
        "tags": [],
    }
