from fastapi import APIRouter, HTTPException
from models.schemas import LinkPreview
from services.link_preview_service import LinkPreviewService

router = APIRouter()

@router.get("/preview", response_model=LinkPreview)
async def preview(url: str):
    preview = await LinkPreviewService.get_link_preview(url)
    if preview:
        return preview
    raise HTTPException(status_code=400, detail="Could not generate preview")

@router.get("/original-url")
async def original_url(url: str):
    original_url = await LinkPreviewService.get_original_url(url)
    return {"original_url": original_url}

@router.get("/all-images")
async def all_images(url: str):
    all_images = await LinkPreviewService.get_images(url)
    return {"all_images": all_images}