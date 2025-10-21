from fastapi import APIRouter, HTTPException
from enum import Enum
from typing import Optional
from pydantic import BaseModel
from services.html_to_markdown_service import HTMLToMarkdownService

router = APIRouter()
html_service = HTMLToMarkdownService()

class OutputFormat(str, Enum):
    STRING = "string"  # Default: string dengan \n
    LINES = "lines"    # Array of lines (mudah di-handle)
    PRETTY = "pretty"  # Structured dengan metadata

class ScrapeRequest(BaseModel):
    url: str
    skip_short_code_blocks: bool = True
    timeout: int = 30000
    selector: Optional[str] = None
    output_format: OutputFormat = OutputFormat.STRING  # ← Tambahan

class ConvertRequest(BaseModel):
    html: str
    skip_short_code_blocks: bool = True
    output_format: OutputFormat = OutputFormat.STRING  # ← Tambahan

@router.post("/scrape-to-markdown")
async def scrape_to_markdown(request: ScrapeRequest):
    result = await html_service.scrape_and_convert(
        url=request.url,
        skip_short_code_blocks=request.skip_short_code_blocks,
        timeout=request.timeout,
        selector=request.selector,
        output_format=request.output_format  # ← Pass parameter
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result

@router.post("/convert-to-markdown")
async def convert_to_markdown(request: ConvertRequest):
    markdown = html_service.convert_html_to_markdown(
        html=request.html,
        skip_short_code_blocks=request.skip_short_code_blocks,
        output_format=request.output_format  # ← Pass parameter
    )
    
    return {
        'success': True,
        'markdown': markdown,
        'format': request.output_format.value
    }

@router.post("/convert-html")
async def convert_html(request: ConvertRequest):
    result = await html_service.convert_from_html_string(
        html=request.html,
        skip_short_code_blocks=request.skip_short_code_blocks
    )
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result