"""Route chat requests using a configured domain and explicit business extensions."""

import asyncio
import base64
import io
import json
from contextlib import AsyncExitStack, ExitStack
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import aiohttp
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from PIL import Image
from pydantic import BaseModel, Field, SecretStr
from typing_extensions import TypedDict

from gustobot.application.services.lightrag_service import get_lightrag_service
from gustobot.config import settings
from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.core.logger import get_logger
from gustobot.infrastructure.core.resources import acquire_in_thread
from gustobot.infrastructure.knowledge import KnowledgeService

from .kb_tools import KnowledgeQueryInputState, create_knowledge_query_node
from .kb_tools.workflow import create_kb_multi_tool_workflow
from .text2sql import create_text2sql_workflow
from .lg_prompts import (
    CHECK_HALLUCINATIONS,
    GENERAL_QUERY_SYSTEM_PROMPT,
    GET_ADDITIONAL_SYSTEM_PROMPT,
    GET_IMAGE_SYSTEM_PROMPT,
    GUARDRAILS_SYSTEM_PROMPT,
    IMAGE_GENERATION_ENHANCE_PROMPT,
    IMAGE_GENERATION_SUCCESS_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    domain_prompt,
)
from .lg_states import AgentState, GradeHallucinations, InputState, Router
from .utils import message_text


class KnowledgeAgentUpdate(TypedDict, total=False):
    messages: List[BaseMessage]
    sources: List[Dict[str, str]]


class AdditionalGuardrailsOutput(BaseModel):
    """
    格式化输出，用于判断用户的问题是否与图谱内容相关
    """

    decision: Literal["end", "proceed"] = Field(
        description="Decision on whether the question is related to the graph contents."
    )


# 构建日志记录器
logger = get_logger(service="lg_builder")


def _coerce_to_bool(value: Any, *, default: bool = False) -> bool:
    """Best-effort conversion of dynamic configuration values to boolean."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


async def analyze_and_route_query(
    state: AgentState, *, config: RunnableConfig
) -> dict[str, Router]:
    """
    Analyze the user's query and determine the appropriate routing.

    This function uses a language model to classify the user's query and decide how to route it
    within the conversation flow.

    Args:
        state (AgentState): The current state of the agent, including conversation history.
        config (RunnableConfig): Configuration with the model used for query analysis.

    Returns:
        dict[str, Router]: A dictionary containing the 'router' key with the classification
        result (classification type and logic).
    """

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured for router analysis.")

    model = ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY),
        model=settings.OPENAI_MODEL,
        base_url=settings.OPENAI_API_BASE,
        temperature=0.7,
        tags=["router"],
    )

    # 拼接提示模版 + 用户的实时问题（包含历史上下文对话）
    messages = [{"role": "system", "content": domain_prompt(ROUTER_SYSTEM_PROMPT)}] + state.messages
    logger.info("-----Analyze user query type-----")
    logger.info(f"History messages: {state.messages}")

    question_text = message_text(state.messages[-1]) if state.messages else ""
    heuristic_router = _heuristic_router(question_text)
    fallback_router: Router = heuristic_router or Router(
        type="kb-query",
        logic="fallback: default to knowledge base routing",
        question=question_text,
    )

    try:
        raw_response = await model.with_structured_output(
            Router, method="function_calling"
        ).ainvoke(messages)
        response = Router.model_validate(raw_response)
    except Exception as exc:
        logger.opt(exception=True).warning("Router LLM failed: {}. Falling back to KB query.", exc)
        return {"router": fallback_router}

    if response.type == "text2sql-query" and (
        not get_domain_definition().sql_enabled or not settings.SQL_DATABASE_URL
    ):
        return {"router": fallback_router}

    sanitized_router = Router(
        type=response.type,
        logic=response.logic,
        question=response.question or question_text,
        decision=response.decision,
        confidence=response.confidence,
        reasoning=response.reasoning,
    )

    # Use the heuristic fallback for invalid output or disabled SQL routing.
    logger.info(f"Analyze user query type completed, result: {sanitized_router}")
    return {"router": sanitized_router}


def route_query(
    state: AgentState,
    *,
    config: RunnableConfig,
) -> Literal[
    "respond_to_general_query",
    "get_additional_info",
    "create_research_plan",
    "create_image_query",
    "create_file_query",
    "create_kb_query",
]:
    """
    根据查询分类确定下一步操作。

    Args:
        state (AgentState): 当前代理状态，包括路由器的分类。

    Returns:
        Literal["respond_to_general_query", "get_additional_info", "create_research_plan",
        "create_image_query", "create_file_query"，"create_kb_query"]: 下一步操作。
    """
    route_type = state.router.type
    attachments = config.get("configurable", {})
    if attachments.get("image_path"):
        logger.info("检测到图片路径，转为图片查询处理")
        return "create_image_query"
    if attachments.get("file_path"):
        logger.info("检测到文件路径，转为文件上传处理")
        return "create_file_query"

    if route_type == "general-query":
        return "respond_to_general_query"
    elif route_type == "additional-query":
        return "get_additional_info"
    elif route_type in ("graphrag-query", "text2sql-query"):  # 图查询或结构化问数
        return "create_research_plan"
    elif route_type == "image-query":
        return "create_image_query"
    elif route_type == "file-query":
        return "create_file_query"
    elif route_type == "kb-query":
        return "create_kb_query"
    else:
        raise ValueError(f"Unknown router type {route_type}")


async def respond_to_general_query(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """生成对一般查询的响应，完全基于大模型，不会触发任何外部服务的调用，包括自定义工具、知识库查询等。
    当路由器将查询分类为一般问题时，将调用此节点。
    Args:
        state (AgentState): 当前代理状态，包括对话历史和路由逻辑。
        config (RunnableConfig): 用于配置响应生成的模型。
    Returns:
        Dict[str, List[BaseMessage]]: 包含'messages'键的字典，其中包含生成的响应。
    """
    logger.info("-----generate general-query response-----")

    # 使用大模型生成回复
    model = ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY is not None else None,
        model=settings.OPENAI_MODEL,
        base_url=settings.OPENAI_API_BASE,
        temperature=0.7,
        tags=["general_query"],
    )

    system_prompt = domain_prompt(GENERAL_QUERY_SYSTEM_PROMPT, logic=state.router.logic)

    messages = [{"role": "system", "content": system_prompt}] + state.messages
    response = await model.ainvoke(messages)
    return {"messages": [response]}


# 大模型生成输出多了一些额外消息
async def get_additional_info(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """生成一个响应，要求用户提供更多信息。

    当路由确定需要从用户那里获取更多信息时，将调用此函数。

    Args:
        state (AgentState): 当前代理状态，包括对话历史和路由逻辑。
        config (RunnableConfig): 用于配置响应生成的模型。

    Returns:
        Dict[str, List[BaseMessage]]: 包含'messages'键的字典，其中包含生成的响应。
    """
    logger.info("------continue to get additional info------")

    # 使用大模型生成回复
    model = ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY is not None else None,
        model=settings.OPENAI_MODEL,
        base_url=settings.OPENAI_API_BASE,
        temperature=0.7,
        tags=["additional_info"],
    )
    decision = AdditionalGuardrailsOutput.model_validate(
        await model.with_structured_output(
            AdditionalGuardrailsOutput, method="function_calling"
        ).ainvoke(
            [
                SystemMessage(content=domain_prompt(GUARDRAILS_SYSTEM_PROMPT)),
                HumanMessage(content=message_text(state.messages[-1]) if state.messages else ""),
            ]
        )
    )
    if decision.decision == "end":
        domain = get_domain_definition()
        return {
            "messages": [
                AIMessage(content=f"当前服务范围是{domain.description}，请提供此范围内的问题。")
            ]
        }
    messages = [
        SystemMessage(
            content=domain_prompt(GET_ADDITIONAL_SYSTEM_PROMPT, logic=state.router.logic)
        ),
        *state.messages,
    ]
    return {"messages": [await model.ainvoke(messages)]}


async def _generate_image(user_query: str) -> Dict[str, List[BaseMessage]]:
    """调用配置的图片生成 API。

    Args:
        user_query: 用户的图片生成请求

    Returns:
        包含生成图片信息的消息字典
    """
    try:
        # 步骤1: 使用LLM优化用户提示词
        model = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=SecretStr(settings.LLM_API_KEY) if settings.LLM_API_KEY is not None else None,
            base_url=settings.LLM_BASE_URL,
            temperature=0.7,
        )

        enhance_prompt = domain_prompt(IMAGE_GENERATION_ENHANCE_PROMPT, user_query=user_query)
        enhance_messages = [{"role": "user", "content": enhance_prompt}]

        logger.info(f"Enhancing user prompt: {user_query}")
        enhanced_response = await model.ainvoke(enhance_messages)
        enhanced_prompt = message_text(enhanced_response).strip()
        logger.info(f"Enhanced prompt: {enhanced_prompt}")

        # 步骤2: 调用图片生成 API
        api_key = settings.IMAGE_GENERATION_API_KEY
        base_url = settings.IMAGE_GENERATION_BASE_URL
        model_name = settings.IMAGE_GENERATION_MODEL
        size = settings.IMAGE_GENERATION_SIZE

        if not api_key:
            logger.error("IMAGE_GENERATION_API_KEY not configured")
            return {"messages": [AIMessage(content="抱歉，图片生成服务配置不完整，无法生成图片。")]}

        # 构建API请求
        api_url = f"{base_url}/images/generations"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model_name, "prompt": enhanced_prompt, "size": size}

        logger.info("Calling image generation API: {}", api_url)
        logger.info(f"Payload: model={model_name}, size={size}")

        # 异步HTTP请求
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers, timeout=60) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error("Image generation API error: {} - {}", resp.status, error_text)
                    return {"messages": [AIMessage(content="抱歉，图片生成失败，请稍后再试。")]}

                result = await resp.json()
                logger.info(
                    "Image generation API response: {}", json.dumps(result, ensure_ascii=False)
                )

        # 步骤3: 解析响应获取图片URL
        if "data" not in result or len(result["data"]) == 0:
            logger.error("Image generation API returned no image data: {}", result)
            return {"messages": [AIMessage(content="抱歉，图片生成失败，请稍后再试。")]}

        image_url = result["data"][0].get("url", "")
        if not image_url:
            logger.error("Image generation API returned no image URL: {}", result)
            return {"messages": [AIMessage(content="抱歉，图片生成失败，请稍后再试。")]}

        logger.info(f"Image generated successfully: {image_url}")

        success_message = IMAGE_GENERATION_SUCCESS_PROMPT
        response_content = f"{success_message}\n\n图片链接: {image_url}"

        return {"messages": [AIMessage(content=response_content)]}

    except asyncio.TimeoutError:
        logger.exception("Image generation API timeout")
        return {"messages": [AIMessage(content="抱歉，图片生成超时，请稍后再试。")]}
    except Exception as e:
        logger.exception("Error generating image: {}", e)
        return {"messages": [AIMessage(content=f"抱歉，图片生成过程中出现错误：{str(e)}")]}


def _encode_image_for_vision(image_path: str) -> str:
    """Encode a bounded JPEG while closing every Pillow image we create."""
    with ExitStack() as resources:
        image: Image.Image = resources.enter_context(Image.open(image_path))
        width, height = image.size
        max_size = 1024
        if width > max_size or height > max_size:
            ratio = min(max_size / width, max_size / height)
            image = resources.enter_context(
                image.resize((int(width * ratio), int(height * ratio)), Image.Resampling.LANCZOS)
            )
        if image.mode != "RGB":
            image = resources.enter_context(image.convert("RGB"))
        with io.BytesIO() as buffer:
            image.save(buffer, format="JPEG", quality=85)
            image_data = base64.b64encode(buffer.getvalue()).decode("ascii")
        logger.info(
            "Image Compressed, Original Size: {}x{}, New Size: {}x{}",
            width,
            height,
            image.width,
            image.height,
        )
        return image_data


async def create_image_query(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """处理图片查询并生成描述回复

    Args:
        state (AgentState): 当前代理状态，包括对话历史
        config (RunnableConfig): 配置参数，包含线程ID等配置信息

    Returns:
        Dict[str, List[BaseMessage]]: 包含'messages'键的字典，其中包含生成的响应
    """
    logger.info("-----Handle Image Query-----")
    image_path = config.get("configurable", {}).get("image_path", None)
    user_query = message_text(state.messages[-1]) if state.messages else ""

    # 判断是图像识别还是图像生成
    generation_keywords = ["生成", "画", "创建", "制作图片", "做一张", "给我一张", "来一张"]
    is_generation = any(keyword in user_query for keyword in generation_keywords)

    # 情况1: 用户要求生成图片（没有上传图片，或明确要求生成）
    if is_generation and not image_path:
        logger.info(f"Image Generation Request: {user_query}")
        return await _generate_image(user_query)

    # 情况2: 用户上传了图片，进行识别
    if not image_path:
        logger.warning("User Upload Image Path is None for recognition")
        return {"messages": [AIMessage(content="抱歉，我无法查看这张图片，请重新上传。")]}

    if not Path(image_path).exists():
        logger.warning(f"User Upload Image Not Found: {image_path}")
        return {"messages": [AIMessage(content="抱歉，我无法查看这张图片，请重新上传。")]}

    # 获取视觉模型配置
    api_key = settings.VISION_API_KEY
    base_url = settings.VISION_BASE_URL
    vision_model = settings.VISION_MODEL

    if not api_key or not base_url or not vision_model:
        logger.error("Vision Model Configuration Not Complete")
        return {"messages": [AIMessage(content="抱歉，我无法查看这张图片，请重新上传。")]}

    logger.info(f"Using Vision Model: {vision_model} to process image: {image_path}")

    try:
        image_data = await asyncio.to_thread(_encode_image_for_vision, image_path)

        # 构建API请求
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

        payload = {
            "model": vision_model,
            "messages": [
                {
                    "role": "system",
                    "content": domain_prompt(
                        GET_IMAGE_SYSTEM_PROMPT, image_description="请先识别上传图片"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                        }
                    ],
                },
            ],
            "max_tokens": 4000,
            "temperature": 0.7,
        }

        # 发送API请求
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,  # 增加超时时间
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    image_description = result["choices"][0]["message"]["content"]
                    logger.info("Successfully processed image and generated description")
                    # 使用图片描述和用户问题生成最终回复

                    # 构建回复请求
                    model = ChatOpenAI(
                        api_key=(
                            SecretStr(settings.OPENAI_API_KEY)
                            if settings.OPENAI_API_KEY is not None
                            else None
                        ),
                        model=settings.OPENAI_MODEL,
                        base_url=settings.OPENAI_API_BASE,
                        temperature=0.7,
                        tags=["image_query"],
                    )
                    # 使用专门的图片查询提示模板
                    system_prompt = domain_prompt(
                        GET_IMAGE_SYSTEM_PROMPT, image_description=image_description
                    )
                    messages = [{"role": "system", "content": system_prompt}] + state.messages
                    answer_message = await model.ainvoke(messages)
                    return {"messages": [answer_message]}

                else:
                    error_text = await response.text()
                    logger.error(f"Vision API Request Failed: {response.status} - {error_text}")
                    return {
                        "messages": [AIMessage(content="抱歉，我无法查看这张图片，请重新上传。")]
                    }

    except Exception as e:
        logger.exception("Error processing image: {}", e)
        return {"messages": [AIMessage(content="抱歉，我无法查看这张图片，请重新上传。")]}


async def create_file_query(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """Handle user-provided files for ingestion."""

    logger.info("-----Found User Upload File-----")
    config_opts = config.get("configurable", {})
    file_path = config_opts.get("file_path")
    ingest_service_url = settings.INGEST_SERVICE_URL

    if not file_path:
        logger.warning("User Upload File Path is None")
        return {"messages": [AIMessage(content="请提供要处理的文件路径。")]}

    p = Path(file_path)
    if not p.exists() or not p.is_file():
        logger.warning("User Upload File Not Found: {}", file_path)
        return {"messages": [AIMessage(content="抱歉，未找到该文件，请确认路径是否正确。")]}

    try:
        async with AsyncExitStack() as resources:
            suffix = p.suffix.lower()
            size_bytes = p.stat().st_size
            if size_bytes > settings.FILE_UPLOAD_MAX_MB * 1024 * 1024:
                return {
                    "messages": [
                        AIMessage(
                            content=f"文件过大（>{settings.FILE_UPLOAD_MAX_MB}MB），请分割后重新上传。"
                        )
                    ]
                }

            if suffix in {".xlsx", ".xls"}:
                if get_domain_definition().document_backend == "lightrag":
                    return {
                        "messages": [
                            AIMessage(content="当前文档入口请先将 Excel 转为 CSV 或文本后上传。")
                        ]
                    }
                # Excel must be handled by external ingestion service
                if not ingest_service_url:
                    return {
                        "messages": [
                            AIMessage(
                                content="未配置外部接入服务 INGEST_SERVICE_URL，无法处理 Excel 导入。"
                            )
                        ]
                    }
                incremental_flag = _coerce_to_bool(
                    config_opts.get("incremental"),
                    default=settings.INGEST_INCREMENTAL_DEFAULT,
                )
                regenerate_flag = _coerce_to_bool(config_opts.get("regenerate"), default=False)
                payload = {
                    "excel_path": str(p),
                    "incremental": incremental_flag,
                    "regenerate": regenerate_flag,
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{ingest_service_url.rstrip('/')}/api/ingest/excel",
                        json=payload,
                        timeout=60,
                    ) as resp:
                        if resp.status not in (200, 202):
                            txt = await resp.text()
                            return {
                                "messages": [
                                    AIMessage(
                                        content=f"外部 Excel 导入请求失败（{resp.status}）：{txt}"
                                    )
                                ]
                            }
                return {
                    "messages": [
                        AIMessage(content="已启动 Excel 导入（外部服务），完成后可直接检索或提问。")
                    ]
                }

            if suffix in {".txt", ".md", ".csv", ".log"}:
                raw_text = await asyncio.to_thread(p.read_text, encoding="utf-8")
            elif suffix == ".json":
                data = json.loads(await asyncio.to_thread(p.read_text, encoding="utf-8"))
                raw_text = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                return {
                    "messages": [
                        AIMessage(
                            content=f"暂不支持该文件类型：{suffix}。当前仅支持 .txt/.md/.json/.csv/.log/.xlsx/.xls。"
                        )
                    ]
                }

            if get_domain_definition().document_backend == "lightrag":
                result = await get_lightrag_service().insert_documents(
                    [raw_text], file_paths=[p.name]
                )
                if result.failed:
                    raise RuntimeError("; ".join(result.errors))
                return {"messages": [AIMessage(content=f"文件《{p.stem}》已加入当前领域知识库。")]}

            import uuid

            doc_id = f"upload_{p.stem}_{uuid.uuid4().hex[:6]}"
            title = p.stem
            service = await resources.enter_async_context(
                acquire_in_thread(KnowledgeService, KnowledgeService.close)
            )
            success = await service.add_document(
                doc_id=doc_id,
                title=title,
                content=raw_text,
                metadata={"category": "uploaded"},
            )
            if not success:
                return {
                    "messages": [AIMessage(content="文件已读取，但保存到知识库失败，请稍后重试。")]
                }

            knowledge_node = create_knowledge_query_node(knowledge_service=service)
            user_question = message_text(state.messages[-1]) if state.messages else title
            input_state: KnowledgeQueryInputState = {
                "task": user_question,
                "context": {"top_k": 5},
                "steps": ["file_upload"],
            }
            kb_result = await knowledge_node(input_state)
            answer_text = (
                kb_result.get("answer")
                or f"文件《{title}》已上传并加入知识库，可直接对我提问相关内容。"
            )
            return {"messages": [AIMessage(content=answer_text)]}
    except Exception as exc:
        logger.exception("Failed to ingest uploaded file: {}", exc)
        return {"messages": [AIMessage(content="文件导入出现异常，请稍后再试或联系管理员。")]}


async def create_kb_query(state: AgentState, *, config: RunnableConfig) -> KnowledgeAgentUpdate:
    """Query the vector knowledge base (and optional external API) via a multi-agent workflow."""
    logger.info("------execute KB multi-tool query------")

    last_message = message_text(state.messages[-1]) if state.messages else ""
    if not last_message.strip():
        return {"messages": [AIMessage(content="请告诉我具体的问题，我才能帮您查询知识库。")]}

    if get_domain_definition().document_backend == "lightrag":
        answer = await get_lightrag_service().query(last_message, mode="naive", stream=False)
        return {"messages": [AIMessage(content=answer)]}

    config_opts = config.get("configurable", {})
    kb_top_k = config_opts.get("kb_top_k")
    if kb_top_k is None:
        kb_top_k = settings.KB_TOP_K
    kb_similarity_threshold = (
        config_opts.get("kb_similarity_threshold")
        if config_opts.get("kb_similarity_threshold") is not None
        else settings.KB_SIMILARITY_THRESHOLD
    )
    kb_filter_expr = config_opts.get("kb_filter_expr")

    knowledge_service: Optional[KnowledgeService] = None
    async with AsyncExitStack() as resources:
        try:
            if not settings.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY is not configured for KB multi-tool workflow.")

            llm = ChatOpenAI(
                api_key=SecretStr(settings.OPENAI_API_KEY),
                model=settings.OPENAI_MODEL,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.3,
                tags=["kb_multi_tool"],
            )

            service_context = acquire_in_thread(KnowledgeService, KnowledgeService.close)
            knowledge_service = await resources.enter_async_context(service_context)

            external_url = settings.KB_EXTERNAL_SEARCH_URL
            if not external_url and settings.INGEST_SERVICE_URL:
                external_url = f"{settings.INGEST_SERVICE_URL.rstrip('/')}/api/search"

            workflow = create_kb_multi_tool_workflow(
                llm=llm,
                knowledge_service=knowledge_service,
                top_k=kb_top_k,
                similarity_threshold=kb_similarity_threshold,
                filter_expr=kb_filter_expr,
                allow_external=settings.KB_ENABLE_EXTERNAL_SEARCH,
                external_search_url=external_url,
                scope_description=get_domain_definition().document_scope,
            )

            history_payload = [
                {
                    "role": msg.type,
                    "content": message_text(msg),
                }
                for msg in state.messages[:-1]
                if message_text(msg).strip()
            ]

            response = await workflow.ainvoke(
                {
                    "question": last_message,
                    "history": history_payload,
                }
            )
            answer_text = response.get("answer") or "检索完成，但暂时没有可以分享的结果。"
            sources = response.get("sources", [])

            # 创建包含sources的AIMessage
            ai_message = AIMessage(content=answer_text)
            # 将sources附加到消息的additional_kwargs中
            ai_message.additional_kwargs["sources"] = sources

            return {"messages": [ai_message], "sources": sources}
        except Exception as exc:
            logger.opt(exception=True).warning(
                "KB multi-tool workflow unavailable ({}); falling back to direct search.", exc
            )

        # Fallback: direct KB query
        if knowledge_service is None:
            service_context = acquire_in_thread(KnowledgeService, KnowledgeService.close)
            knowledge_service = await resources.enter_async_context(service_context)
        knowledge_node = create_knowledge_query_node(knowledge_service=knowledge_service)
        input_state: KnowledgeQueryInputState = {
            "task": last_message,
            "context": {
                "top_k": kb_top_k,
                "similarity_threshold": kb_similarity_threshold,
                "filter_expr": kb_filter_expr,
            },
            "steps": ["kb_query"],
        }
        result = await knowledge_node(input_state)
        answer_text = result.get("answer", "") or "抱歉，我暂时无法从知识库中找到答案。"
        sources = result.get("sources", [])
        return {
            "messages": [AIMessage(content=answer_text, additional_kwargs={"sources": sources})],
            "sources": sources,
        }


# 图工具 查询节点
async def create_research_plan(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """Retrieve entity relationships or run explicitly enabled statistical SQL."""
    domain = get_domain_definition()
    question = message_text(state.messages[-1]) if state.messages else ""
    if state.router.type != "text2sql-query":
        result = await get_lightrag_service().query(question, stream=False)
        return {"messages": [AIMessage(content=result)]}

    if not domain.sql_enabled or not settings.SQL_DATABASE_URL:
        raise RuntimeError("SQL requires an enabled domain and SQL_DATABASE_URL.")
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured for SQL.")
    model = ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY),
        base_url=settings.OPENAI_API_BASE,
        model=settings.OPENAI_MODEL,
        temperature=0.3,
        tags=["text2sql"],
    )
    workflow = create_text2sql_workflow(
        model, settings.SQL_DATABASE_URL, db_type=domain.sql_db_type
    )
    sql_result = await workflow.ainvoke({"question": question})
    return {"messages": [AIMessage(content=sql_result["answer"])]}


async def check_hallucinations(state: AgentState, *, config: RunnableConfig) -> dict[str, Any]:
    """
    Analyze the user's query and checks if the response is supported by the set of facts based
    on the document retrieved,
    providing a binary score result.

    This function uses a language model to analyze the user's query and gives a binary score result.

    Args:
        state (AgentState): The current state of the agent, including conversation history.
        config (RunnableConfig): Configuration with the model used for query analysis.

    Returns:
        dict[str, Router]: A dictionary containing the 'router' key with the classification
        result (classification type and logic).
    """
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured for hallucination checks.")

    model = ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY),
        base_url=settings.OPENAI_API_BASE,
        model=settings.OPENAI_MODEL,
        temperature=0.7,
        tags=["hallucinations"],
    )

    system_prompt = CHECK_HALLUCINATIONS.format(
        documents=state.documents, generation=state.messages[-1]
    )

    messages = [{"role": "system", "content": system_prompt}] + state.messages

    logger.info("---CHECK HALLUCINATIONS---")

    response = GradeHallucinations.model_validate(
        await model.with_structured_output(GradeHallucinations, method="function_calling").ainvoke(
            messages
        )
    )

    return {"hallucination": response}


checkpointer = InMemorySaver()

# 定义状态图
builder = StateGraph(AgentState, input_schema=InputState)
# 添加节点
builder.add_node(analyze_and_route_query)  # 意图识别
builder.add_node(respond_to_general_query)  # 默认回复
builder.add_node(get_additional_info)  # 图结构信息
builder.add_node("create_research_plan", create_research_plan)
builder.add_node(create_image_query)
builder.add_node(create_file_query)
builder.add_node(create_kb_query)


# 添加边
builder.add_edge(START, "analyze_and_route_query")
builder.add_conditional_edges("analyze_and_route_query", route_query)

graph = builder.compile(checkpointer=checkpointer)


def _heuristic_router(question: str) -> Optional[Router]:
    """Fallback routing based on simple keyword heuristics."""
    if not question:
        return None

    lowered = question.lower()

    domain = get_domain_definition()
    graphrag_keywords = domain.graph_keywords
    text2sql_keywords = (
        domain.sql_keywords if domain.sql_enabled and settings.SQL_DATABASE_URL else []
    )

    if any(keyword.lower() in lowered for keyword in text2sql_keywords):
        return Router(
            type="text2sql-query",
            logic="keyword fallback: text2sql",
            question=question,
        )

    if any(keyword.lower() in lowered for keyword in graphrag_keywords):
        return Router(
            type="graphrag-query",
            logic="keyword fallback: graphrag",
            question=question,
        )

    if any(keyword.lower() in lowered for keyword in domain.document_keywords):
        return Router(type="kb-query", logic="keyword fallback: documents", question=question)
    return None
