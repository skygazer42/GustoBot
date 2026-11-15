"""
文件上传处理API
"""

import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

router = APIRouter()

# 创建上传目录
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# 支持的文件类型
ALLOWED_FILE_TYPES = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".log",
    ".xlsx",
    ".xls",
    ".pdf",
    ".doc",
    ".docx",
}

ALLOWED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

# 最大文件大小 (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024


class UploadResponse(BaseModel):
    success: bool
    filename: str
    original_name: str
    size: int
    file_path: str
    file_type: str


class FileUploadResponse(UploadResponse):
    file_id: str
    file_url: str


class ImageUploadResponse(UploadResponse):
    image_id: str
    image_url: str


class DeleteUploadResponse(BaseModel):
    success: bool
    message: str


def _validate_filename(filename: Optional[str]) -> str:
    if (
        not filename
        or filename in {".", ".."}
        or any(char in filename for char in ("/", "\\", ":", "\x00"))
    ):
        raise HTTPException(status_code=400, detail="文件名无效")
    return filename


def _uploaded_path(directory: Path, filename: str) -> Path:
    path = (directory / _validate_filename(filename)).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise HTTPException(status_code=400, detail="文件路径无效")
    return path


@router.post("/file", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)) -> FileUploadResponse:
    """上传文件（txt, excel, pdf等）"""

    # 检查文件类型
    original_name = _validate_filename(file.filename)
    file_ext = Path(original_name).suffix.lower()
    if file_ext not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型。支持的类型: {', '.join(ALLOWED_FILE_TYPES)}",
        )

    try:
        # 生成唯一文件名
        file_id = str(uuid.uuid4())
        filename = f"{file_id}_{original_name}"
        file_path = _uploaded_path(UPLOAD_DIR, filename)

        # 保存文件
        content = await file.read(MAX_FILE_SIZE + 1)
        file_size = len(content)

        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"文件太大，最大支持 {MAX_FILE_SIZE // (1024*1024)}MB",
            )

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)

        logger.info(f"文件上传成功: {filename} ({file_size} bytes)")

        return FileUploadResponse(
            success=True,
            file_id=file_id,
            filename=filename,
            original_name=original_name,
            size=file_size,
            file_path=str(file_path),
            file_url=f"/api/v1/upload/files/{filename}",
            file_type=file_ext,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("文件上传失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"文件上传失败: {str(e)}"
        ) from e


@router.post("/image", response_model=ImageUploadResponse)
async def upload_image(image: UploadFile = File(...)) -> ImageUploadResponse:
    """上传图片文件"""

    # 检查文件类型
    original_name = _validate_filename(image.filename)
    file_ext = Path(original_name).suffix.lower()
    if file_ext not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的图片类型。支持的类型: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    try:
        # 生成唯一文件名
        image_id = str(uuid.uuid4())
        filename = f"{image_id}_{original_name}"

        # 创建图片目录
        image_dir = UPLOAD_DIR / "images"
        image_dir.mkdir(exist_ok=True)

        file_path = _uploaded_path(image_dir, filename)

        # 保存图片
        content = await image.read(MAX_FILE_SIZE + 1)
        file_size = len(content)

        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"图片太大，最大支持 {MAX_FILE_SIZE // (1024*1024)}MB",
            )

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)

        logger.info(f"图片上传成功: {filename} ({file_size} bytes)")

        return ImageUploadResponse(
            success=True,
            image_id=image_id,
            filename=filename,
            original_name=original_name,
            size=file_size,
            file_path=str(file_path),
            image_url=f"/api/v1/upload/images/{filename}",
            file_type=file_ext,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("图片上传失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"图片上传失败: {str(e)}"
        ) from e


@router.get("/files/{filename}")
def get_uploaded_file(filename: str):
    """获取上传的文件"""
    file_path = _uploaded_path(UPLOAD_DIR, filename)
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    return FileResponse(file_path)


@router.get("/images/{filename}")
def get_uploaded_image(filename: str):
    """获取上传的图片"""
    file_path = _uploaded_path(UPLOAD_DIR / "images", filename)
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")

    return FileResponse(file_path)


@router.delete("/{file_id}", response_model=DeleteUploadResponse)
def delete_uploaded_file(file_id: str):
    """删除上传的文件"""
    try:
        uuid.UUID(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="文件ID无效") from exc
    # 查找文件
    for file_path in UPLOAD_DIR.rglob(f"{file_id}_*"):
        if not file_path.is_file() or not file_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
            continue
        try:
            file_path.unlink()
            logger.info(f"文件删除成功: {file_path}")
            return DeleteUploadResponse(success=True, message="文件删除成功")
        except OSError as exc:
            logger.exception("文件删除失败")
            raise HTTPException(status_code=500, detail="文件删除失败") from exc

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
