import asyncio
from datetime import datetime
import logging
import os
import time
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from routes.link_preview import router as link_preview_router
from routes.debug import router as debug_router
from routes.html_to_md_route import router as html_to_md_router
from dotenv import load_dotenv
from utils.playwright_utils import AdvancedPlaywrightManager, playwright_manager

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(link_preview_router, tags=["link-preview"])
app.include_router(debug_router,prefix="/debug", tags=["debug"])
app.include_router(html_to_md_router, prefix="/html-to-markdown", tags=["html-to-markdown"])

playwright_manager =  AdvancedPlaywrightManager(
    max_tabs_per_browser=5,
    max_browsers=3,
    min_browsers=1,
    auto_scale=True,
    browser_idle_timeout=300  # 5 minutes
)
@app.on_event("startup")
async def startup_event():
    """Initialize Playwright manager on startup"""
    logger.info("Starting application...")
    logger.info("Initializing Advanced Playwright Manager...")
    await playwright_manager.initialize()
    logger.info("Playwright Manager initialized successfully")
    logger.info(f"Configuration: {playwright_manager.max_tabs_per_browser} tabs/browser, "
                f"{playwright_manager.max_browsers} max browsers, "
                f"auto-scale: {playwright_manager.auto_scale}")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown of all browser instances"""
    logger.info("Shutting down application...")
    logger.info("Closing Playwright Manager...")
    await playwright_manager.close()
    logger.info("Playwright Manager closed successfully")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Advanced Web Scraper API",
        "version": "2.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    stats = playwright_manager.get_stats()
    return {
        "status": "healthy",
        "playwright_initialized": playwright_manager.playwright is not None,
        "active_browsers": stats['active_browsers'],
        "active_tabs": stats['active_tabs'],
        "total_capacity": stats['total_capacity']
    }


@app.get("/stats")
async def get_stats():
    """Get detailed statistics about browser instances"""
    return JSONResponse(content=playwright_manager.get_stats())


@app.post("/admin/scale-browsers")
async def scale_browsers(target_browsers: int):
    """Manually scale the number of browser instances"""
    if target_browsers < playwright_manager.min_browsers:
        return {
            "error": f"Cannot scale below minimum ({playwright_manager.min_browsers})"
        }
    if target_browsers > playwright_manager.max_browsers:
        return {
            "error": f"Cannot scale above maximum ({playwright_manager.max_browsers})"
        }
    
    current = len(playwright_manager.browsers)
    
    if target_browsers > current:
        # Scale up
        async with playwright_manager.lock:
            for _ in range(target_browsers - current):
                await playwright_manager._create_browser_instance()
        return {
            "action": "scaled_up",
            "previous": current,
            "current": len(playwright_manager.browsers)
        }
    elif target_browsers < current:
        # Scale down (only close idle browsers with no active tabs)
        async with playwright_manager.lock:
            browsers_to_remove = []
            for browser_instance in playwright_manager.browsers[target_browsers:]:
                if browser_instance.active_tabs == 0:
                    browsers_to_remove.append(browser_instance)
            
            for browser_instance in browsers_to_remove:
                await browser_instance.context.close()
                await browser_instance.browser.close()
                playwright_manager.browsers.remove(browser_instance)
        
        return {
            "action": "scaled_down",
            "previous": current,
            "current": len(playwright_manager.browsers),
            "note": "Only closed idle browsers with no active tabs"
        }
    else:
        return {
            "action": "no_change",
            "current": current
        }


@app.get("/admin/config")
async def get_config():
    """Get current configuration"""
    return {
        "max_tabs_per_browser": playwright_manager.max_tabs_per_browser,
        "max_browsers": playwright_manager.max_browsers,
        "min_browsers": playwright_manager.min_browsers,
        "auto_scale": playwright_manager.auto_scale,
        "browser_idle_timeout": playwright_manager.browser_idle_timeout
    }

@app.get("/debug/test-tab-opening")
async def debug_test_tab_opening():
    """
    Test apakah tab benar-benar dibuka dan stats terupdate
    """
    stats_before = playwright_manager.get_stats()
    
    # Open a page and HOLD it (tidak langsung close)
    async with playwright_manager.get_page("google.com") as page:
        stats_during = playwright_manager.get_stats()
        
        # Wait a bit so we can check
        await asyncio.sleep(2)
        
        stats_still_open = playwright_manager.get_stats()
    
    stats_after = playwright_manager.get_stats()
    
    return {
        "test": "tab_opening",
        "stats_before": stats_before,
        "stats_during_open": stats_during,
        "stats_still_open": stats_still_open,
        "stats_after_close": stats_after,
        "analysis": {
            "tabs_increased": stats_during['active_tabs'] > stats_before['active_tabs'],
            "tabs_decreased_after": stats_after['active_tabs'] < stats_during['active_tabs'],
            "expected_behavior": "tabs should increase during and decrease after"
        }
    }


@app.get("/debug/stress-test-internal")
async def debug_stress_test_internal(num_requests: int = 10):
    """
    Internal stress test - buat multiple requests sekaligus
    """
    import time
    
    start_time = time.time()
    stats_before = playwright_manager.get_stats()
    
    async def single_test(i: int):
        try:
            async with playwright_manager.get_page("test.com") as page:
                await page.goto("https://example.com", timeout=5000)
                return {"request": i, "success": True}
        except Exception as e:
            return {"request": i, "success": False, "error": str(e)}
    
    # Launch concurrent requests
    tasks = [single_test(i) for i in range(num_requests)]
    
    # Get stats while running
    stats_during = playwright_manager.get_stats()
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    duration = time.time() - start_time
    stats_after = playwright_manager.get_stats()
    
    successful = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
    
    return {
        "test": "internal_stress_test",
        "num_requests": num_requests,
        "duration_seconds": round(duration, 2),
        "successful": successful,
        "failed": num_requests - successful,
        "stats_before": stats_before,
        "stats_during": stats_during,
        "stats_after": stats_after,
        "peak_tabs_detected": max(
            stats_before['active_tabs'],
            stats_during['active_tabs'],
            stats_after.get('peak_active_tabs', 0)
        ),
        "results_sample": results[:3]
    }


@app.get("/debug/browser-info")
async def debug_browser_info():
    """
    Detailed info tentang setiap browser instance
    """
    browsers_info = []
    
    for i, browser in enumerate(playwright_manager.browsers):
        info = {
            "index": i + 1,
            "active_tabs": browser.active_tabs,
            "total_requests": browser.total_requests,
            "created_at": datetime.fromtimestamp(browser.created_at).isoformat(),
            "last_used": datetime.fromtimestamp(browser.last_used).isoformat(),
            "uptime_seconds": int(asyncio.get_event_loop().time() - browser.created_at),
            "idle_seconds": int(asyncio.get_event_loop().time() - browser.last_used),
            "semaphore_available": browser.semaphore._value,
            "browser_is_connected": browser.browser.is_connected(),
            "context_pages_count": len(browser.context.pages)
        }
        browsers_info.append(info)
    
    return {
        "total_browsers": len(playwright_manager.browsers),
        "config": {
            "max_tabs_per_browser": playwright_manager.max_tabs_per_browser,
            "max_browsers": playwright_manager.max_browsers,
            "min_browsers": playwright_manager.min_browsers,
            "auto_scale": playwright_manager.auto_scale
        },
        "browsers": browsers_info,
        "current_stats": playwright_manager.get_stats()
    }


@app.get("/debug/simulate-load")
async def debug_simulate_load(
    concurrent: int = 5,
    duration_seconds: int = 10,
    background_tasks: BackgroundTasks = None
):
    """
    Simulate load in background untuk testing
    """
    async def background_load():
        logger.info(f"🔥 Starting background load: {concurrent} concurrent for {duration_seconds}s")
        
        start_time = time.time()
        request_count = 0
        
        async def single_request():
            nonlocal request_count
            try:
                async with playwright_manager.get_page("example.com") as page:
                    await page.goto("https://example.com", timeout=5000)
                    request_count += 1
                    return True
            except Exception as e:
                logger.error(f"Background request error: {e}")
                return False
        
        while time.time() - start_time < duration_seconds:
            tasks = [single_request() for _ in range(concurrent)]
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(1)
        
        logger.info(f"✓ Background load completed: {request_count} requests processed")
    
    # Start in background
    asyncio.create_task(background_load())
    
    return {
        "message": "Background load started",
        "concurrent_requests": concurrent,
        "duration_seconds": duration_seconds,
        "check_stats_at": "/stats or /debug/browser-info"
    }


@app.post("/debug/force-scale")
async def debug_force_scale(num_browsers: int):
    """
    Force create atau remove browsers
    """
    current = len(playwright_manager.browsers)
    
    if num_browsers > playwright_manager.max_browsers:
        return {"error": f"Cannot exceed max_browsers ({playwright_manager.max_browsers})"}
    
    if num_browsers > current:
        # Scale up
        async with playwright_manager.lock:
            for _ in range(num_browsers - current):
                await playwright_manager._create_browser_instance()
        
        return {
            "action": "scaled_up",
            "from": current,
            "to": len(playwright_manager.browsers),
            "stats": playwright_manager.get_stats()
        }
    
    elif num_browsers < current:
        # Scale down
        async with playwright_manager.lock:
            while len(playwright_manager.browsers) > num_browsers:
                if len(playwright_manager.browsers) <= playwright_manager.min_browsers:
                    break
                
                # Remove last browser if idle
                browser = playwright_manager.browsers[-1]
                if browser.active_tabs == 0:
                    await browser.context.close()
                    await browser.browser.close()
                    playwright_manager.browsers.remove(browser)
                else:
                    break
        
        return {
            "action": "scaled_down",
            "from": current,
            "to": len(playwright_manager.browsers),
            "stats": playwright_manager.get_stats()
        }
    
    return {
        "action": "no_change",
        "current": current,
        "stats": playwright_manager.get_stats()
    }


@app.get("/debug/reset-stats")
async def debug_reset_stats():
    """Reset statistics"""
    old_stats = playwright_manager.stats.copy()
    
    playwright_manager.stats = {
        'total_requests': 0,
        'active_tabs': 0,
        'browsers_created': len(playwright_manager.browsers),
        'browsers_closed': 0,
        'failed_requests': 0,
        'successful_requests': 0,
        'peak_active_tabs': 0,
        'peak_browsers': len(playwright_manager.browsers)
    }
    
    # Reset per-browser stats
    for browser in playwright_manager.browsers:
        browser.total_requests = 0
    
    return {
        "message": "Stats reset",
        "old_stats": old_stats,
        "new_stats": playwright_manager.get_stats()
    }

# import asyncio
# import logging
# from urllib.parse import urlparse, urljoin
# from fastapi import FastAPI
# from playwright.async_api import async_playwright
# from pydantic import BaseModel
# from typing import Optional, List

# app = FastAPI()

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# class LinkPreview(BaseModel):
#     url: str
#     title: Optional[str]
#     description: Optional[str]
#     image: Optional[str]

# class PlatformConfig:
#     def __init__(self, selectors):
#         self.selectors = selectors

# PLATFORM_CONFIGS = {
#     "default": PlatformConfig({
#         "title": ['meta[property="og:title"]', 'meta[name="twitter:title"]', 'title'],
#         "description": ['meta[property="og:description"]', 'meta[name="twitter:description"]', 'meta[name="description"]'],
#         "image": ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
#     }),
#     "tiktok.com": PlatformConfig({
#         "title": ['meta[property="og:title"]'],
#         "description": ['meta[property="og:description"]'],
#         "image": ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
#     }),
#     "facebook.com": PlatformConfig({
#         "title": ['meta[property="og:title"]', 'meta[name="twitter:title"]'],
#         "description": ['meta[property="og:description"]', 'meta[name="twitter:description"]'],
#         "image": ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
#     }),
#     "youtube.com": PlatformConfig({
#         "title": ['meta[property="og:title"]', 'meta[name="twitter:title"]'],
#         "description": ['meta[property="og:description"]', 'meta[name="twitter:description"]'],
#         "image": ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
#     }),
#     "linkedin.com": PlatformConfig({
#         "title": ['meta[property="og:title"]', 'meta[name="twitter:title"]'],
#         "description": ['meta[property="og:description"]', 'meta[name="twitter:description"]'],
#         "image": ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
#     }),
#     "twitter.com": PlatformConfig({
#         "title": ['meta[property="og:title"]', 'meta[name="twitter:title"]'],
#         "description": ['meta[property="og:description"]', 'meta[name="twitter:description"]'],
#         "image": ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
#     }),
# }

# async def get_element_content(page, selectors):
#     for selector in selectors:
#         try:
#             element = await page.query_selector(selector)
#             if element:
#                 return await element.get_attribute('content') or await element.inner_text()
#         except:
#             continue
#     return None

# def get_actual_image_url(base_url, image_url):
#     if image_url is None or image_url.strip() == '' or image_url.startswith('data:'):
#         return None

#     if '.svg' in image_url or '.gif' in image_url:
#         return None

#     if image_url.startswith('//'):
#         image_url = f'https:{image_url}'

#     if not image_url.startswith('http'):
#         if base_url.endswith('/') and image_url.startswith('/'):
#             image_url = f'{base_url[:-1]}{image_url}'
#         elif not base_url.endswith('/') and not image_url.startswith('/'):
#             image_url = f'{base_url}/{image_url}'
#         else:
#             image_url = f'{base_url}{image_url}'

#     return image_url

# async def get_main_image_url(page, base_url):
#     # First, try to get image from og:image or twitter:image meta tags
#     meta_elements = await page.query_selector_all('meta[property="og:image"], meta[name="twitter:image"]')
#     for element in meta_elements:
#         image_url = await element.get_attribute('content')
#         actual_url = get_actual_image_url(base_url, image_url)
#         if actual_url:
#             return actual_url

#     # If no image found in meta tags, look for the largest img tag
#     try:
#         images = await page.query_selector_all('img')
#         largest_image = None
#         largest_area = 0

#         for img in images:
#             src = await img.get_attribute('src')
#             actual_url = get_actual_image_url(base_url, src)
#             if not actual_url:
#                 continue

#             bounding_box = await img.bounding_box()
#             if bounding_box:
#                 width, height = bounding_box["width"], bounding_box["height"]
#                 if width and height:
#                     area = width * height
#                     if area > largest_area:
#                         largest_area = area
#                         largest_image = actual_url

#         if largest_image:
#             return largest_image
#     except Exception as e:
#         logger.error(f"Error finding largest image: {str(e)}")

#     return None

# async def get_link_preview(url):
#     async with async_playwright() as p:
#         browser = await p.chromium.launch(headless=True)
#         context = await browser.new_context()
#         await context.route("**/*", lambda route, request: 
#             route.continue_() if request.resource_type in ['document', 'script', 'image'] else route.abort())
            
#         await context.set_extra_http_headers({
#             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'
#         })
#         page = await context.new_page()
        
#         try:
#             logger.info(f"Fetching preview for URL: {url}")
#             response = await page.goto(url, wait_until="networkidle")
#             final_url = response.url
#             domain = urlparse(final_url).netloc
#             config = PLATFORM_CONFIGS.get(domain, PLATFORM_CONFIGS["default"])
#             logger.debug(f"Using config for domain: {domain}")
            
#             main_image = await get_main_image_url(page, final_url)
            
#             preview = LinkPreview(
#                 url=final_url,
#                 title=await get_element_content(page, config.selectors["title"]),
#                 description=await get_element_content(page, config.selectors["description"]),
#                 image=main_image
#             )
            
#             logger.info(f"Successfully generated preview for URL: {final_url}")
#             return preview
        
#         except Exception as e:
#             logger.error(f"Error generating preview for URL {url}: {str(e)}")
#             return None
        
#         finally:
#             await browser.close()

# @app.get("/preview")
# async def preview(url: str):
#     preview = await get_link_preview(url)
#     if preview:
#         return preview
#     return {"error": "Could not generate preview"}
    
# # The get_original_url function remains unchanged
# async def get_original_url(url):
#     async with async_playwright() as p:
#         browser = await p.chromium.launch(headless=True)
#         context = await browser.new_context()

#         await context.route("**/*", lambda route, request: 
#             route.continue_() if request.resource_type in ['document', 'script'] else route.abort())
        
#         page = await context.new_page()
#         try:
#             response = await page.goto(url, wait_until="domcontentloaded", timeout=3000)
#             return response.url
#         except Exception as e:
#             logger.error(f"An error occurred: {e}")
#         finally:
#             await page.unroute_all()
#             await browser.close()

# @app.get("/original-url")
# async def original_url(url: str):
#     original_url = await get_original_url(url)
#     return {"original_url": original_url}