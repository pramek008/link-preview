from playwright.async_api import async_playwright
import asyncio
import logging
import re
from contextlib import asynccontextmanager
import httpx

logger = logging.getLogger(__name__)

class PlaywrightManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.lock = asyncio.Lock()
        self.last_used = 0
        self.close_task = None
    
    @staticmethod
    def get_user_agent(domain: str) -> str:
        """Get appropriate user agent for specific domains"""
        # E-commerce sites often work better with WhatsApp user agent
        if 'tokopedia.com' in domain:
            return 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
        elif any(site in domain for site in ['shopee.co.id', 'bukalapak.com', 'blibli.com']):
            return 'WhatsApp/2.23.2.72 A'
        elif 'tiktok.com' in domain:
            return 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1'
        elif 'amazon.com' in domain or 'amazon.co.id' in domain:
            return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        elif 'twitter.com' in domain or 'x.com' in domain:
            return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        else:
            return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


    async def initialize(self):
        async with self.lock:
            if self.playwright is None:
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(headless=True)
            if self.context is None:
                self.context = await self.browser.new_context()
            self.last_used = asyncio.get_event_loop().time()
            self.schedule_close()

    def schedule_close(self):
        if self.close_task:
            self.close_task.cancel()
        self.close_task = asyncio.create_task(self.auto_close())

    async def auto_close(self, delay=900):
        await asyncio.sleep(delay)
        async with self.lock:
            if asyncio.get_event_loop().time() - self.last_used >= delay:
                await self.close()

    async def close(self):
        logger.info("Closing Playwright resources")
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.playwright = self.browser = self.context = None
        logger.info("Playwright resources closed")

    @asynccontextmanager
    async def get_page(self, domain: str = None):
        await self.initialize()
        self.last_used = asyncio.get_event_loop().time()
        
        # Update context with domain-specific user agent
        if domain:
            user_agent = self.get_user_agent(domain)
            await self.context.close()
            self.context = await self.browser.new_context(
                user_agent=user_agent,
                extra_http_headers={'Accept-Language': 'en-US,en;q=0.9'}
            )
        
        page = await self.context.new_page()
        try:
            yield page
        finally:
            await page.close()


playwright_manager = PlaywrightManager()

async def get_page():
    return playwright_manager.get_page()

def resolve_redirect(url: str) -> str:
    try:
        r = httpx.get(url, follow_redirects=True, timeout=10)
        return str(r.url)  # final URL setelah semua redirect
    except Exception as e:
        print(f"Redirect error for {url}: {e}")
        return url

# Helper function for common page operations
async def navigate_and_wait(page, url, timeout=30000):
    try:
        await page.route("**/*", lambda route: route.abort() 
                    if any(ext in route.request.url for ext in [
                        '.png', '.jpg', '.jpeg', '.gif', '.css', 
                        '.woff', '.woff2', '.ttf', '.mp4', '.webp', 
                        'analytics', 'tracking', 'advertisement'
                    ]) else route.continue_()
                )
        await page.goto(url, timeout=timeout, wait_until="networkidle")
    except Exception as e:
        logger.error(f"Navigation error: {str(e)}")
        raise
    finally:
        await page.close()


async def navigate_and_wait_v2(page, url, timeout=30000):
    try:
        # Compile regex once for improved performance
        blocked_resources = re.compile(r'\.(png|jpg|jpeg|gif|css|woff|woff2|ttf|mp4|webp)$|analytics|tracking|advertisement')
        
        # Only block certain requests
        async def handle_route(route):
            if blocked_resources.search(route.request.url):
                await route.abort()
            else:
                await route.continue_()

        # Set user agent
        await page.set_extra_http_headers({
            "User-Agent": "WhatsApp/2.23.2.72 A"
        })
        
        # Set up routing to block unnecessary resources
        await page.route("**/*", handle_route)
        
        # Go to the URL and wait for network to stabilize but not completely idle
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception as e:
        logger.error(f"Error navigating to {url}: {str(e)}")
        raise
    # finally:
    #     await page.close()

async def navigate_and_wait_v3(page, url, timeout=30000):
    try:
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        await page.route("**/*", lambda route, request: 
            route.continue_() if request.resource_type in ['document', 'script'] else route.abort())
            
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception as e:
        logger.error(f"Error navigating to {url}: {str(e)}")
        raise
    # finally:
    #     await page.close()

async def navigate_to_resolve_redirect(url: str, timeout=10) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(
            follow_redirects=True, 
            timeout=timeout,
            headers=headers
        ) as client:
            response = await client.get(url)
            return str(response.url)
    except Exception as e:
        logger.error(f"Redirect resolution error for {url}: {str(e)}")
        return url

# async def navigate_and_wait_v2(page, url, timeout=30000):
#     try:
#         # Define resource types to block completely
#         blocked_resources = {
#             'image', 'stylesheet', 'font', 'media', 
#             'websocket', 'other', 'manifest'
#         }
        
#         # Define URL patterns to block
#         blocked_patterns = [
#             # Analytics and tracking
#             'google-analytics', 'analytics', 'tracking', 'stats',
#             'pixel', 'beacon', 'telemetry', 'logging',
#             # Ads
#             'advertisement', 'banner', 'adsystem', 'adserv',
#             # Social media
#             'facebook', 'twitter', 'linkedin',
#             # Common resource extensions
#             '.png', '.jpg', '.jpeg', '.gif', '.css', 
#             '.woff', '.woff2', '.ttf', '.mp4', '.webp',
#             # Other optimization targets
#             'hotjar', 'clarity', 'sentry', 'intercom',
#         ]

#         # Custom request handler with more precise control
#         async def handle_request(route):
#             request = route.request
#             resource_type = request.resource_type
#             request_url = request.url.lower()

#             # Always allow the main document
#             if resource_type == 'document' and request_url == url.lower():
#                 await route.continue_()
#                 return

#             # Block by resource type
#             if resource_type in blocked_resources:
#                 await route.abort()
#                 return

#             # Block by URL pattern
#             if any(pattern in request_url for pattern in blocked_patterns):
#                 await route.abort()
#                 return

#             # Handle scripts more granularly
#             if resource_type == 'script':
#                 # Allow essential TikTok scripts
#                 if 'tiktok.com' in request_url and (
#                     'webapp' in request_url or 
#                     'main' in request_url or 
#                     'item' in request_url
#                 ):
#                     await route.continue_()
#                     return
#                 # Block non-essential scripts
#                 await route.abort()
#                 return

#             # Default: continue with the request
#             await route.continue_()

#         # Set up request interception
#         await page.route("**/*", handle_request)

#         # Configure optimal page settings
#         await page.set_viewport_size({"width": 1280, "height": 720})
        
#         # Optimize browser context
#         await page.context.clear_cookies()
        
#         # Set performance optimization options
#         await page.set_extra_http_headers({
#             "Accept-Language": "en-US,en;q=0.9",
#             "Accept-Encoding": "gzip, deflate, br",
#             "Accept": "text/html,application/json,*/*;q=0.9",
#             "Connection": "keep-alive",
#             "Cache-Control": "no-cache",
#             "Pragma": "no-cache"
#         })

#         # More efficient page load options
#         page_load_options = {
#             "timeout": timeout,
#             "wait_until": "domcontentloaded",  # Changed from networkidle
#             "referer": "https://www.tiktok.com/"
#         }

#         # Create a response received event
#         response_received = asyncio.Event()
#         main_response = None

#         async def handle_response(response):
#             nonlocal main_response
#             if response.url.lower() == url.lower():
#                 main_response = response
#                 response_received.set()

#         page.on("response", handle_response)

#         # Start navigation
#         navigation_task = asyncio.create_task(
#             page.goto(url, **page_load_options)
#         )

#         try:
#             # Wait for either the main response or timeout
#             await asyncio.wait_for(
#                 response_received.wait(), 
#                 timeout=timeout/1000  # Convert ms to seconds
#             )
            
#             if main_response and main_response.status == 200:
#                 # Optional: Cancel navigation if we got what we needed
#                 navigation_task.cancel()
#                 return main_response
                
#         except asyncio.TimeoutError:
#             # Fall back to waiting for navigation completion
#             response = await navigation_task
#             if response.status != 200:
#                 raise Exception(f"Navigation failed with status {response.status}")
#             return response

#     except Exception as e:
#         logger.error(f"Navigation error: {str(e)}")
#         raise