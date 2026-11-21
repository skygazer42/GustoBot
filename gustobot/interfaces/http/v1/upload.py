"""Managed uploads retain the frontend response without implicitly indexing content."""

import asyncio
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from gustobot.infrastructure.core.database import session_scope
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository

router = APIRouter()
UPLOAD_DIR = Path(__file__).resolve().parents[4] / "uploads"
ALLOWED_FILE_TYPES = {".txt", ".md", ".markdown", ".json", ".csv", ".log", ".pdf", ".docx"}
ALLOWED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MAX_FILE_SIZE = 50 * 1024 * 1024


class UploadResponse(BaseModel):
    """Common asset metadata returned after a successful upload."""

    success: bool
    asset_id: str
    filename: str
    original_name: str
    size: int
    file_path: str
    file_type: str


class FileUploadResponse(UploadResponse):
    """Upload receipt with the file download route and compatibility ID."""

    file_id: str
    file_url: str


class ImageUploadResponse(UploadResponse):
    """Upload receipt with the image display route and compatibility ID."""

    image_id: str
    image_url: str


class DeleteUploadResponse(BaseModel):
    """Result of removing a previously uploaded asset file."""

    success: bool
    message: str


def _validate_filename(filename: str | None) -> str:
    """Reject empty names and path syntax before using a client filename."""
    if (
        not filename
        or filename in {".", ".."}
        or any(char in filename for char in ("/", "\\", ":", "\x00"))
    ):
        raise HTTPException(status_code=400, detail="文件名无效")
    return filename


def _uploaded_path(directory: Path, filename: str) -> Path:
    """Resolve a filename and reject paths that escape the upload directory."""
    path = (directory / _validate_filename(filename)).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise HTTPException(status_code=400, detail="文件路径无效")
    return path


def _save_new_asset(directory, asset_id, original_name, content, file_type):
    """Write an asset and register it, removing the file if registration fails."""
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{asset_id}_{original_name}"
    path = _uploaded_path(directory, filename)
    created = False
    # 文件和数据库无法共用事务；登记失败时删除本次新文件，避免留下失联附件。
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(content)
        with session_scope() as session:
            KnowledgeRepository(session).register_asset(
                id=asset_id,
                original_name=original_name,
                path=str(path),
                file_type=file_type,
                size=len(content),
            )
        return path
    except BaseException:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove the newly failed upload {}", asset_id)
        raise


async def _receive_upload(file: UploadFile, directory: Path, allowed_types: set[str]):
    """Validate, size-limit, store, and register an uploaded file."""
    original_name = _validate_filename(file.filename)
    file_type = Path(original_name).suffix.lower()
    if file_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="不支持的文件类型。支持的类型: " + ", ".join(sorted(allowed_types)),
        )
    # 多读一个字节即可识别超限，不必将整个超大文件加载到内存。
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, detail=f"文件太大，最大支持 {MAX_FILE_SIZE // (1024 * 1024)}MB"
        )
    asset_id = str(uuid.uuid4())
    try:
        path = await asyncio.to_thread(
            _save_new_asset, directory, asset_id, original_name, content, file_type
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Upload registration failed for {}", asset_id)
        raise HTTPException(status_code=503, detail="上传未完成，请检查文件存储与数据库") from error
    return {
        "success": True,
        "asset_id": asset_id,
        "filename": path.name,
        "original_name": original_name,
        "size": len(content),
        "file_path": str(path),
        "file_type": file_type,
    }


@router.post("/file", response_model=FileUploadResponse)
async def upload_file(file: Annotated[UploadFile, File()]) -> FileUploadResponse:
    """Store a supported document and return its asset and download identifiers."""
    payload = await _receive_upload(file, UPLOAD_DIR, ALLOWED_FILE_TYPES)
    return FileUploadResponse(
        **payload,
        file_id=payload["asset_id"],
        file_url=f"/api/v1/upload/files/{payload['filename']}",
    )


@router.post("/image", response_model=ImageUploadResponse)
async def upload_image(image: Annotated[UploadFile, File()]) -> ImageUploadResponse:
    """Store a supported image and return its asset and display identifiers."""
    payload = await _receive_upload(image, UPLOAD_DIR / "images", ALLOWED_IMAGE_TYPES)
    return ImageUploadResponse(
        **payload,
        image_id=payload["asset_id"],
        image_url=f"/api/v1/upload/images/{payload['filename']}",
    )


@router.get("/files/{filename}")
def get_uploaded_file(filename: str):
    """Return an uploaded file after constraining its resolved path to uploads."""
    path = _uploaded_path(UPLOAD_DIR, filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)


@router.get("/images/{filename}")
def get_uploaded_image(filename: str):
    """Return an uploaded image after constraining its path to the image folder."""
    path = _uploaded_path(UPLOAD_DIR / "images", filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)


@router.delete("/{file_id}", response_model=DeleteUploadResponse)
def delete_uploaded_file(file_id: str):
    """Remove the first stored file matching a valid uploaded asset identifier."""
    try:
        uuid.UUID(file_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="文件ID无效") from error
    for path in UPLOAD_DIR.rglob(f"{file_id}_*"):
        if not path.is_file() or not path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
            continue
        try:
            path.unlink()
            return DeleteUploadResponse(success=True, message="文件删除成功")
        except OSError as error:
            logger.exception("Upload deletion failed")
            raise HTTPException(status_code=500, detail="文件删除失败") from error
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
