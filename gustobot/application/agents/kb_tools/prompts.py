"""
Prompt helpers for the KG knowledge agent.
"""
from textwrap import dedent


def build_knowledge_system_prompt(context: str) -> str:
    """
    Construct the system prompt used when the agent summarizes knowledge base results.
    """

    return dedent(
        """\
        你是一个专业的菜谱助手，基于提供的知识库内容回答用户问题。

        要求：
        1. 只基于提供的文档内容回答，不要编造信息
        2. 如果文档中没有相关信息，明确告知用户
        3. 回答要准确、详细、实用
        4. 如果是烹饪步骤，要按顺序清晰列出
        5. 回答要友好、自然
        6. 不要自行生成参考资料或数据库名称，系统会单独展示真实检索来源

        参考文档：
        {context}

        请基于以上文档回答用户问题。
        """.format(
            context=context
        )
    )
