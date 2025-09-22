from fastapi import APIRouter, HTTPException, Request
from services.metadata_debug_service import MetadataDebugService
import os
from dotenv import load_dotenv
import logging 

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
    
@router.get("/compare-methods")
async def compare_methods(request: Request):
    url = request.query_params.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="Please provide a valid URL.")

    try:
        result = await MetadataDebugService.compare_navigation_methods(url)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        