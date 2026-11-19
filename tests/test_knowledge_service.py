"""
知识库服务测试
"""

import pytest

from gustobot.infrastructure.knowledge import KnowledgeService


@pytest.fixture
def sample_recipe():
    """示例菜谱"""
    return {
        "id": "test_001",
        "name": "测试菜谱",
        "category": "家常菜",
        "difficulty": "简单",
        "ingredients": ["食材1", "食材2"],
        "steps": ["步骤1", "步骤2"],
        "tips": "小贴士",
    }


def test_format_recipe_document(sample_recipe):
    """测试菜谱格式化"""
    document = KnowledgeService._format_recipe_document(sample_recipe)

    assert "测试菜谱" in document
    assert "家常菜" in document
    assert "食材1" in document
    assert "步骤1" in document
