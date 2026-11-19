"""Explicit image analysis and generation without an intent classifier or prompt rewrite."""

import asyncio
import base64
import binascii
import io
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI
from PIL import Image
from pydantic import HttpUrl, TypeAdapter

from gustobot.application.services.knowledge_query import KnowledgeAnswer
from gustobot.config import settings
from gustobot.infrastructure.core.resources import close_on_exit

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_IMAGE_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp"}


def _encode_image(path: Path) -> str:
    try:
        with ExitStack() as resources:
            image = resources.enter_context(Image.open(path))
            if image.format not in _IMAGE_EXTENSIONS:
                raise ValueError("Unsupported image format")
            image.load()
            if max(image.size) > 1024:
                ratio = 1024 / max(image.size)
                image = resources.enter_context(
                    image.resize(
                        (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
                        Image.Resampling.LANCZOS,
                    )
                )
            if image.mode != "RGB":
                image = resources.enter_context(image.convert("RGB"))
            with io.BytesIO() as stream:
                image.save(stream, format="JPEG", quality=85)
                return base64.b64encode(stream.getvalue()).decode("ascii")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid or unreadable image content") from exc


def _save_generated_image(encoded: str) -> str:
    try:
        content = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(content)) as image:
            extension = _IMAGE_EXTENSIONS.get(image.format)
            if extension is None:
                raise ValueError("Unsupported generated image format")
            image.load()
    except (binascii.Error, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Image provider returned invalid image data") from exc
    directory = (PROJECT_ROOT / "uploads" / "images").resolve()
    if not directory.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("Generated image directory must stay inside the project")
    directory.mkdir(parents=True, exist_ok=True)
    name = f"generated_{uuid4().hex}{extension}"
    destination = (directory / name).resolve()
    if not destination.is_relative_to(directory):
        raise ValueError("Generated image path must stay inside the managed image directory")
    with destination.open("xb") as stream:
        stream.write(content)
    return f"{settings.API_V1_PREFIX}/upload/images/{name}"


async def answer_image(message: str, *, action: str, path: Path | None) -> KnowledgeAnswer:
    if not message.strip():
        raise ValueError("An image question or generation prompt is required")
    if action == "knowledge" and path is not None:
        action = "analyze_image"
    if action not in {"analyze_image", "generate_image"}:
        raise ValueError("Unsupported image action")
    if action == "analyze_image":
        if path is None:
            raise ValueError("An uploaded image is required for analysis")
        if not settings.VISION_API_KEY or not settings.VISION_MODEL.strip():
            raise ValueError("Vision model configuration is not configured")
        encoded = await asyncio.to_thread(_encode_image, path)
        client = AsyncOpenAI(
            api_key=settings.VISION_API_KEY,
            base_url=settings.VISION_BASE_URL,
            timeout=60,
            max_retries=0,
        )
        async with close_on_exit(client.close):
            response = await client.chat.completions.create(
                model=settings.VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": message},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                            },
                        ],
                    }
                ],
            )
        if not response.choices:
            raise ValueError("Vision provider returned no response text")
        text = response.choices[0].message.content
        if text is None or not text.strip():
            raise ValueError("Vision provider returned no response text")
        return KnowledgeAnswer(
            message=text,
            route="image-query",
            route_logic="按用户请求分析上传图片",
            sources=[{"backend": "attachment", "type": "image", "source": path.name}],
            metadata={
                "model_calls": 1,
                "model": settings.VISION_MODEL,
                "action": action,
                "temporary": True,
            },
        )
    if path is not None:
        raise ValueError(
            "Image generation currently accepts a text prompt without a reference image"
        )
    if not settings.IMAGE_GENERATION_API_KEY or not settings.IMAGE_GENERATION_MODEL.strip():
        raise ValueError("Image generation model configuration is not configured")
    if not settings.IMAGE_GENERATION_SIZE.strip():
        raise ValueError("Image generation size configuration is not configured")
    client = AsyncOpenAI(
        api_key=settings.IMAGE_GENERATION_API_KEY,
        base_url=settings.IMAGE_GENERATION_BASE_URL,
        timeout=60,
        max_retries=0,
    )
    payload: dict[str, Any] = {
        "model": settings.IMAGE_GENERATION_MODEL,
        "prompt": message,
        "size": settings.IMAGE_GENERATION_SIZE,
        "n": 1,
    }
    async with close_on_exit(client.close):
        generated = await client.images.generate(**payload)
    if not generated.data:
        raise ValueError("Image provider returned no image data")
    image = generated.data[0]
    if image.b64_json is not None:
        url = await asyncio.to_thread(_save_generated_image, image.b64_json)
    elif image.url is not None:
        url = str(TypeAdapter(HttpUrl).validate_python(image.url))
    else:
        raise ValueError("Image provider returned neither an image URL nor image data")
    return KnowledgeAnswer(
        message=f"已生成图片：\n\n![生成图片](<{url}>)",
        route="image-generation",
        route_logic="按用户明确请求生成图片",
        sources=[],
        metadata={
            "model_calls": 1,
            "model": settings.IMAGE_GENERATION_MODEL,
            "action": action,
            "image_url": url,
            "generated": True,
        },
    )
