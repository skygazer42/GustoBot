"""
Legacy vector knowledge base CRUD API endpoints.
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from gustobot.infrastructure.core.resources import close_on_exit

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# Vector store models ---------------------------------------------------------
class RecipeModel(BaseModel):
    """Recipe payload stored in the vector knowledge base."""

    id: Optional[str] = Field(None, description="Recipe identifier")
    name: str = Field(..., description="Recipe name")
    category: Optional[str] = Field(None, description="Category")
    difficulty: Optional[str] = Field(None, description="Difficulty level")
    time: Optional[str] = Field(None, description="Cooking time")
    ingredients: Optional[List[str]] = Field(None, description="Ingredient list")
    steps: Optional[List[str]] = Field(None, description="Preparation steps")
    tips: Optional[str] = Field(None, description="Cooking tips")
    nutrition: Optional[Dict[str, Any]] = Field(None, description="Nutrition facts")


class SearchRequest(BaseModel):
    """Vector store search request."""

    query: str = Field(..., description="Query text")
    top_k: Optional[int] = Field(5, ge=1, le=20, description="Number of results to return")


class SearchResponse(BaseModel):
    """Vector store search response."""

    results: List[Dict[str, Any]] = Field(..., description="Matched documents")
    count: int = Field(..., description="Result count")


class KnowledgeOperationResponse(BaseModel):
    status: str
    message: str


class RecipeAddedResponse(KnowledgeOperationResponse):
    recipe_id: str


class RecipeBatchStatistics(BaseModel):
    success: int
    error: int
    total: int


class RecipeBatchResponse(KnowledgeOperationResponse):
    statistics: RecipeBatchStatistics


class KnowledgeStatsResponse(BaseModel):
    status: str
    data: Dict[str, Any]


# Dependency helpers ----------------------------------------------------------
async def get_knowledge_service():
    """Return the vector knowledge base service."""
    from gustobot.infrastructure.knowledge import KnowledgeService

    service = await run_in_threadpool(KnowledgeService)
    async with close_on_exit(service.close):
        yield service


# Vector store CRUD -----------------------------------------------------------
@router.post("/recipes", response_model=RecipeAddedResponse, status_code=201)
async def add_recipe(
    recipe: RecipeModel,
    service=Depends(get_knowledge_service),
) -> Dict[str, Any]:
    """Add a single recipe to the vector knowledge base."""
    try:
        if not recipe.id:
            recipe.id = f"recipe_{uuid.uuid4().hex[:8]}"

        success = await service.add_recipe(recipe_id=recipe.id, recipe_data=recipe.model_dump())
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add recipe")

        return {"status": "success", "message": "Recipe added", "recipe_id": recipe.id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Error adding recipe: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/recipes/batch", response_model=RecipeBatchResponse, status_code=201)
async def add_recipes_batch(
    recipes: List[RecipeModel],
    service=Depends(get_knowledge_service),
) -> Dict[str, Any]:
    """Add recipes in batch."""
    try:
        for recipe in recipes:
            if not recipe.id:
                recipe.id = f"recipe_{uuid.uuid4().hex[:8]}"

        result = await service.add_recipes_batch([recipe.model_dump() for recipe in recipes])
        return {
            "status": "success",
            "message": f"Inserted {result['success']} recipes",
            "statistics": result,
        }
    except Exception as exc:
        logger.exception(f"Error in batch add: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(
    request: SearchRequest,
    service=Depends(get_knowledge_service),
) -> SearchResponse:
    """Search the vector knowledge base."""
    try:
        results = await service.search(query=request.query, top_k=request.top_k)
        return SearchResponse(results=results, count=len(results))
    except Exception as exc:
        logger.exception(f"Search error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/recipes/{recipe_id}", response_model=KnowledgeOperationResponse)
async def delete_recipe(
    recipe_id: str,
    service=Depends(get_knowledge_service),
) -> Dict[str, Any]:
    """Delete a recipe."""
    try:
        success = await service.delete_recipe(recipe_id)
        if not success:
            raise HTTPException(status_code=404, detail="Recipe not found or deletion failed")

        return {"status": "success", "message": f"Recipe {recipe_id} deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Delete error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def get_stats(
    service=Depends(get_knowledge_service),
) -> Dict[str, Any]:
    """Return vector store statistics."""
    try:
        stats = await service.get_stats()
        return {"status": "success", "data": stats}
    except Exception as exc:
        logger.exception(f"Stats error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/clear", response_model=KnowledgeOperationResponse)
async def clear_knowledge_base(
    confirm: bool = False,
    service=Depends(get_knowledge_service),
) -> Dict[str, Any]:
    """Clear the vector store (dangerous operation)."""
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm=true is required to clear the store")

    try:
        success = await service.clear()
        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear the store")
        return {"status": "success", "message": "Knowledge base cleared"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Clear error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
