from fastapi import APIRouter, HTTPException
from services.metadata_debug_service import MetadataDebugService
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

@router.get("/debug-metadata")
async def debug_metadata(
    url: str,
    proxy_url: str = None,
    timeout: int = 30000,
    ):
    try:
        metadata = await MetadataDebugService.get_page_metadata(
            url=url,
            proxy_url=proxy_url,
            timeout=timeout,        
        )
        
        success = bool(metadata.get('title') or metadata.get('meta_tags'))
        
        return {
            "success": success,
            "metadata": metadata
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))