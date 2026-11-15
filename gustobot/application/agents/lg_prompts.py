"""Reusable instructions; domain content comes from the selected profile."""

from gustobot.config.domain import get_domain_definition
from gustobot.config import settings

ROUTER_SYSTEM_PROMPT = """根据问题和历史选择处理模块：
general-query：问候与一般交流。
additional-query：需要澄清对象、条件或范围。
kb-query：资料解释、语义检索与文档问答。
graphrag-query：实体关系与多跳图谱问题。
text2sql-query：仅在当前领域启用 SQL 时用于统计与聚合。
image-query：图片分析或生成。file-query：文件上传处理。
不能仅因某个词存在就忽略用户真实意图；不要编造知识库内容。"""

GENERAL_QUERY_SYSTEM_PROMPT = """你是知识助手。清楚、简洁地回答，区分已知事实与推测。
需要资料依据的问题应说明需要检索；不要声称已查过未使用的工具。
本次路由依据：{logic}。"""

GET_ADDITIONAL_SYSTEM_PROMPT = """根据历史和领域范围，提出完成查询所必需的澄清问题。
一次询问关键缺失条件，不预设业务对象。本次路由依据：{logic}。"""

GET_IMAGE_SYSTEM_PROMPT = """分析图片中与当前领域相关的可见对象及其关系。
明确图中无法确认的内容，不把视觉猜测说成数据库事实。
已有图像描述：{image_description}"""

GUARDRAILS_SYSTEM_PROMPT = """判断问题是否属于给定领域范围。
在范围内或需要澄清时选择 proceed，明确无关时选择 end。"""

CHECK_HALLUCINATIONS = """检查回答是否受到给定事实支持，不接受缺乏来源的推断。
事实：{documents}
回答：{generation}"""

IMAGE_GENERATION_ENHANCE_PROMPT = """为图片生成整理清楚的提示词，保留用户要求的主体、风格、构图和限制。
不擅自加入当前领域以外的业务假设。只输出提示词。
用户要求：{user_query}"""

IMAGE_GENERATION_SUCCESS_PROMPT = "图片已生成。"


def domain_prompt(template: str, **values: object) -> str:
    """Format the template first so braces in configured text remain literal."""
    domain = get_domain_definition()
    return (
        template.format(**values)
        + f"\n当前领域：{domain.name}\n{domain.description}\n资料范围：{domain.document_scope}"
        + f"\n领域指引：{domain.assistant_instructions}"
        + f"\n统计 SQL：{'已启用' if domain.sql_enabled and settings.SQL_DATABASE_URL else '未启用'}"
    )
