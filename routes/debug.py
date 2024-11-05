from fastapi import APIRouter, HTTPException
from services.metadata_debug_service import MetadataDebugService

router = APIRouter()

@router.get("/debug-metadata")
async def debug_metadata(url: str):
    try:
        metadata = await MetadataDebugService.get_page_metadata(url)
        return {
            "success": True,
            "metadata": metadata
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))