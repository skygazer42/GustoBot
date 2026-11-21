"""Public read-only recipe browsing and verified local media routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from gustobot.application.services.recipe_library import (
    RecipeDetail,
    RecipeLibrary,
    RecipeLibraryUnavailable,
    RecipeNotFound,
    RecipePage,
    get_recipe_library,
)

router = APIRouter(prefix="/recipes", tags=["Public Recipes"])
Library = Annotated[RecipeLibrary, Depends(get_recipe_library)]


class RecipeQuery(BaseModel):
    """Validated search and pagination parameters supported by the public catalog."""

    q: str = Field(default="", max_length=200)
    category: str | None = Field(default=None, max_length=200)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=12, ge=1, le=48)


@router.get("", response_model=RecipePage)
def list_recipes(query: Annotated[RecipeQuery, Depends()], library: Library) -> RecipePage:
    """Read one catalog page in FastAPI's thread pool without a model or graph call."""
    try:
        return library.list(**query.model_dump())
    except RecipeLibraryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/media/{filename}")
def recipe_media(filename: str, library: Library) -> FileResponse:
    """Serve only current-catalog image references inside the dedicated media root."""
    try:
        path = library.media_path(filename)
    except RecipeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeLibraryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})


@router.get("/{recipe_id}", response_model=RecipeDetail)
def recipe_detail(recipe_id: str, library: Library) -> RecipeDetail:
    """Return the full current recipe and its real provenance."""
    try:
        return library.get(recipe_id)
    except RecipeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeLibraryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
