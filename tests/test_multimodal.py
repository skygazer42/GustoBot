"""Explicit image actions use one provider call and release their resources."""

import asyncio
import base64
import importlib
import importlib.util
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image


def image_bytes(format="PNG", size=(4, 3)):
    with Image.new("RGB", size, "red") as image, io.BytesIO() as stream:
        image.save(stream, format=format)
        return stream.getvalue()


@pytest.fixture
def environment(monkeypatch, tmp_path):
    name = "gustobot.application.services.multimodal"
    assert (
        importlib.util.find_spec(name) is not None
    ), "Explicit multimodal service is not implemented"
    module = importlib.import_module(name)
    configuration = SimpleNamespace(
        VISION_API_KEY="test-vision-key",
        VISION_BASE_URL="https://vision.example/v1",
        VISION_MODEL="test-vision",
        IMAGE_GENERATION_API_KEY="test-generation-key",
        IMAGE_GENERATION_BASE_URL="https://images.example/v1",
        IMAGE_GENERATION_MODEL="test-image",
        IMAGE_GENERATION_SIZE="1024x1024",
        API_V1_PREFIX="/api/v1",
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="图中是番茄。"))]
                    )
                )
            )
        ),
        images=SimpleNamespace(
            generate=AsyncMock(
                return_value=SimpleNamespace(
                    data=[
                        SimpleNamespace(url="https://images.example/generated.png", b64_json=None),
                    ]
                )
            )
        ),
        close=AsyncMock(),
    )
    factory = Mock(return_value=client)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(module, "settings", configuration)
    monkeypatch.setattr(module, "PROJECT_ROOT", project)
    monkeypatch.setattr(module, "AsyncOpenAI", factory)
    return SimpleNamespace(
        module=module, client=client, factory=factory, settings=configuration, project=project
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["analyze_image", "knowledge"])
async def test_analysis_sends_the_actual_image_and_question_once(environment, tmp_path, action):
    path = tmp_path / "upload.png"
    path.write_bytes(image_bytes(size=(1500, 750)))
    result = await environment.module.answer_image("这个番茄熟了吗？", action=action, path=path)
    request = environment.client.chat.completions.create.call_args.kwargs
    assert request["model"] == "test-vision"
    content = request["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "这个番茄熟了吗？"}
    data_url = content[1]["image_url"]["url"]
    assert data_url.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as encoded:
        assert encoded.format == "JPEG" and encoded.width <= 1024 and encoded.height <= 1024
    assert result.message == "图中是番茄。"
    assert result.route == "image-query"
    assert result.metadata["model_calls"] == 1
    assert result.sources == [{"backend": "attachment", "type": "image", "source": "upload.png"}]
    environment.client.chat.completions.create.assert_awaited_once()
    environment.client.images.generate.assert_not_awaited()
    environment.client.close.assert_awaited_once()
    assert environment.factory.call_args.kwargs["max_retries"] == 0


@pytest.mark.asyncio
async def test_generation_uses_prompt_directly_and_returns_provider_url(environment):
    result = await environment.module.answer_image(
        "一盘番茄炒蛋", action="generate_image", path=None
    )
    request = environment.client.images.generate.call_args.kwargs
    assert request == {"model": "test-image", "prompt": "一盘番茄炒蛋", "size": "1024x1024", "n": 1}
    assert result.route == "image-generation"
    assert result.metadata["model_calls"] == 1
    assert result.metadata["image_url"] == "https://images.example/generated.png"
    assert "https://images.example/generated.png" in result.message
    assert result.sources == []
    environment.client.images.generate.assert_awaited_once()
    environment.client.chat.completions.create.assert_not_awaited()
    environment.client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_base64_generation_writes_only_a_valid_managed_image(
    environment, tmp_path, monkeypatch
):
    encoded = base64.b64encode(image_bytes()).decode("ascii")
    environment.client.images.generate.return_value = SimpleNamespace(
        data=[SimpleNamespace(url=None, b64_json=encoded)]
    )
    outside = tmp_path / "unrelated-working-directory"
    outside.mkdir()
    monkeypatch.chdir(outside)
    result = await environment.module.answer_image(
        "一盘番茄炒蛋", action="generate_image", path=None
    )
    files = list((environment.project / "uploads" / "images").iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == image_bytes()
    assert result.metadata["image_url"] == f"/api/v1/upload/images/{files[0].name}"
    assert list(outside.iterdir()) == []
    with Image.open(files[0]) as image:
        assert image.format == "PNG"
    environment.client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [RuntimeError("provider offline"), asyncio.CancelledError("cancelled")]
)
async def test_provider_failures_and_cancellation_propagate_after_client_close(
    environment, failure
):
    environment.client.images.generate.side_effect = failure
    with pytest.raises(type(failure)) as caught:
        await environment.module.answer_image("画一盘菜", action="generate_image", path=None)
    assert caught.value is failure
    environment.client.close.assert_awaited_once()
    assert not (environment.project / "uploads").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,action",
    [
        ("VISION_API_KEY", "analyze_image"),
        ("VISION_MODEL", "analyze_image"),
        ("IMAGE_GENERATION_API_KEY", "generate_image"),
        ("IMAGE_GENERATION_MODEL", "generate_image"),
    ],
)
async def test_missing_configuration_fails_before_provider_creation(
    environment, tmp_path, field, action
):
    setattr(environment.settings, field, None if field.endswith("API_KEY") else "")
    path = tmp_path / "image.png"
    path.write_bytes(image_bytes())
    with pytest.raises(ValueError, match="配置|configured|configuration"):
        await environment.module.answer_image(
            "看图", action=action, path=None if action == "generate_image" else path
        )
    environment.factory.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_image_and_missing_attachment_fail_before_provider_creation(
    environment, tmp_path
):
    invalid = tmp_path / "looks-like-image.png"
    invalid.write_text("not an image", encoding="utf-8")
    for path in [None, invalid]:
        with pytest.raises(ValueError, match="image|图片"):
            await environment.module.answer_image("看图", action="analyze_image", path=path)
    environment.factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        [],
        [SimpleNamespace(url=None, b64_json=None)],
        [SimpleNamespace(url="javascript:alert(1)", b64_json=None)],
        [SimpleNamespace(url=None, b64_json="not-valid-base64")],
    ],
)
async def test_invalid_generation_responses_never_report_success_or_save_files(environment, data):
    environment.client.images.generate.return_value = SimpleNamespace(data=data)
    with pytest.raises(ValueError):
        await environment.module.answer_image("画一盘菜", action="generate_image", path=None)
    environment.client.close.assert_awaited_once()
    assert not (environment.project / "uploads").exists()


@pytest.mark.asyncio
async def test_analysis_rejects_missing_response_text(environment, tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(image_bytes())
    environment.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
    )
    with pytest.raises(ValueError, match="text|文本"):
        await environment.module.answer_image("看图", action="analyze_image", path=path)
    environment.client.close.assert_awaited_once()
