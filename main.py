import asyncio
import logging
from urllib.parse import urlparse
from fastapi import FastAPI
from playwright.async_api import async_playwright
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LinkPreview(BaseModel):
    url: str
    title: Optional[str]
    description: Optional[str]
    image: Optional[str]

class TikTokPreview(LinkPreview):
    pass

class PlatformConfig:
    def __init__(self, selectors):
        self.selectors = selectors

PLATFORM_CONFIGS = {
    "default": PlatformConfig({
        "title": ['meta[property="og:title"]', 'meta[name="twitter:title"]', 'title'],
        "description": ['meta[property="og:description"]', 'meta[name="twitter:description"]', 'meta[name="description"]'],
        "image": ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
    }),
    "tiktok.com": PlatformConfig({
        "title": ['meta[property="og:title"]'],
        "description": ['meta[property="og:description"]'],
        "image": ['meta[property="og:image"]'],
    }),
}

async def get_element_content(page, selectors):
    for selector in selectors:
        try:
            element = await page.query_selector(selector)
            if element:
                return await element.get_attribute('content') or await element.inner_text()
        except:
            continue
    return None

async def get_original_url(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        response = await page.goto(url)
        return response.url

async def get_link_preview(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.route("**/*", lambda route, request: 
            route.continue_() if request.resource_type in ['document', 'script'] else route.abort())
            
        await context.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'
        })
        page = await context.new_page()
        
        try:
            logger.info(f"Fetching preview for URL: {url}")
            response = await page.goto(url, wait_until="networkidle")
            final_url = response.url
            domain = urlparse(final_url).netloc
            config = PLATFORM_CONFIGS.get(domain, PLATFORM_CONFIGS["default"])
            logger.debug(f"Using config for domain: {domain}")
            
            if "tiktok.com" in domain:
                preview = TikTokPreview(
                    url=final_url,
                    title=await get_element_content(page, config.selectors["title"]),
                    description=await get_element_content(page, config.selectors["description"]),
                    image=await get_element_content(page, config.selectors["image"]),
                )
            else:
                preview = LinkPreview(
                    url=final_url,
                    title=await get_element_content(page, config.selectors["title"]),
                    description=await get_element_content(page, config.selectors["description"]),
                    image=await get_element_content(page, config.selectors["image"]),
                )
            
            logger.info(f"Successfully generated preview for URL: {final_url}")
            return preview
        
        except Exception as e:
            logger.error(f"Error generating preview for URL {url}: {str(e)}")
            return None
        
        finally:
            await browser.close()

@app.get("/original-url")
async def original_url(url: str):
    original_url = await get_original_url(url)
    return {"original_url": original_url}


@app.get("/preview")
async def preview(url: str):
    preview = await get_link_preview(url)
    if preview:
        return preview
    return {"error": "Could not generate preview"}


