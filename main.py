import asyncio
import logging
from urllib.parse import urlparse, urljoin
from fastapi import FastAPI
from playwright.async_api import async_playwright
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LinkPreview(BaseModel):
    url: str
    title: Optional[str]
    description: Optional[str]
    image: Optional[str]

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
        "image": ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
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

def get_actual_image_url(base_url, image_url):
    if image_url is None or image_url.strip() == '' or image_url.startswith('data:'):
        return None

    if '.svg' in image_url or '.gif' in image_url:
        return None

    if image_url.startswith('//'):
        image_url = f'https:{image_url}'

    if not image_url.startswith('http'):
        if base_url.endswith('/') and image_url.startswith('/'):
            image_url = f'{base_url[:-1]}{image_url}'
        elif not base_url.endswith('/') and not image_url.startswith('/'):
            image_url = f'{base_url}/{image_url}'
        else:
            image_url = f'{base_url}{image_url}'

    return image_url

async def get_main_image_url(page, base_url):
    # First, try to get image from og:image or twitter:image meta tags
    meta_elements = await page.query_selector_all('meta[property="og:image"], meta[name="twitter:image"]')
    for element in meta_elements:
        image_url = await element.get_attribute('content')
        actual_url = get_actual_image_url(base_url, image_url)
        if actual_url:
            return actual_url

    # If no image found in meta tags, look for the largest img tag
    try:
        images = await page.query_selector_all('img')
        largest_image = None
        largest_area = 0

        for img in images:
            src = await img.get_attribute('src')
            actual_url = get_actual_image_url(base_url, src)
            if not actual_url:
                continue

            bounding_box = await img.bounding_box()
            if bounding_box:
                width, height = bounding_box["width"], bounding_box["height"]
                if width and height:
                    area = width * height
                    if area > largest_area:
                        largest_area = area
                        largest_image = actual_url

        if largest_image:
            return largest_image
    except Exception as e:
        logger.error(f"Error finding largest image: {str(e)}")

    return None

async def get_link_preview(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.route("**/*", lambda route, request: 
            route.continue_() if request.resource_type in ['document', 'script', 'image'] else route.abort())
            
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
            
            main_image = await get_main_image_url(page, final_url)
            
            preview = LinkPreview(
                url=final_url,
                title=await get_element_content(page, config.selectors["title"]),
                description=await get_element_content(page, config.selectors["description"]),
                image=main_image
            )
            
            logger.info(f"Successfully generated preview for URL: {final_url}")
            return preview
        
        except Exception as e:
            logger.error(f"Error generating preview for URL {url}: {str(e)}")
            return None
        
        finally:
            await browser.close()

@app.get("/preview")
async def preview(url: str):
    preview = await get_link_preview(url)
    if preview:
        return preview
    return {"error": "Could not generate preview"}
    
# The get_original_url function remains unchanged
async def get_original_url(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        await context.route("**/*", lambda route, request: 
            route.continue_() if request.resource_type in ['document', 'script'] else route.abort())
        
        page = await context.new_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=3000)
            return response.url
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            await page.unroute_all()
            await browser.close()

@app.get("/original-url")
async def original_url(url: str):
    original_url = await get_original_url(url)
    return {"original_url": original_url}