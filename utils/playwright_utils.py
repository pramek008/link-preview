import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class BrowserInstance:
    browser: Browser
    context: BrowserContext
    semaphore: asyncio.Semaphore
    created_at: float
    last_used: float
    active_tabs: int = 0
    total_requests: int = 0  # Track total requests per browser

class AdvancedPlaywrightManager:
    def __init__(
        self, 
        max_tabs_per_browser: int = 25,
        max_browsers: int = 3,
        auto_scale: bool = True,
        browser_idle_timeout: int = 900,
        min_browsers: int = 1
    ):
        self.playwright = None
        self.browsers: List[BrowserInstance] = []
        self.max_tabs_per_browser = max_tabs_per_browser
        self.max_browsers = max_browsers
        self.min_browsers = min_browsers
        self.auto_scale = auto_scale
        self.browser_idle_timeout = browser_idle_timeout
        
        self.lock = asyncio.Lock()
        self.cleanup_task = None
        
        # Enhanced stats
        self.stats = {
            'total_requests': 0,
            'active_tabs': 0,
            'browsers_created': 0,
            'browsers_closed': 0,
            'failed_requests': 0,
            'successful_requests': 0,
            'peak_active_tabs': 0,
            'peak_browsers': 0
        }
    
    @staticmethod
    def get_user_agent(domain: str) -> str:
        """Get appropriate user agent for specific domains"""
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
        """Initialize playwright and create minimum number of browsers"""
        async with self.lock:
            if self.playwright is None:
                logger.info("Starting Playwright...")
                self.playwright = await async_playwright().start()
                
                for _ in range(self.min_browsers):
                    await self._create_browser_instance()
                
                if not self.cleanup_task:
                    self.cleanup_task = asyncio.create_task(self._cleanup_idle_browsers())
                
                logger.info(f"✓ Initialized with {len(self.browsers)} browser instance(s)")

    async def _create_browser_instance(self) -> BrowserInstance:
        """Create a new browser instance with persistent context"""
        browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',  # For better compatibility
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
        
        # Create ONE context per browser - akan dipakai untuk semua requests
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent=self.get_user_agent(''),
            extra_http_headers={'Accept-Language': 'en-US,en;q=0.9'},
            ignore_https_errors=True
        )
        
        current_time = asyncio.get_event_loop().time()
        instance = BrowserInstance(
            browser=browser,
            context=context,
            semaphore=asyncio.Semaphore(self.max_tabs_per_browser),
            created_at=current_time,
            last_used=current_time
        )
        
        self.browsers.append(instance)
        self.stats['browsers_created'] += 1
        
        # Update peak
        if len(self.browsers) > self.stats['peak_browsers']:
            self.stats['peak_browsers'] = len(self.browsers)
        
        logger.info(f"✓ Created browser #{len(self.browsers)} (Total active: {len(self.browsers)}/{self.max_browsers})")
        
        return instance

    async def _get_available_browser(self) -> Optional[BrowserInstance]:
        """Get a browser instance with available capacity"""
        # Try to find browser with available slots
        for browser_instance in self.browsers:
            if browser_instance.active_tabs < self.max_tabs_per_browser:
                return browser_instance
        
        # Auto-scale if needed
        if self.auto_scale and len(self.browsers) < self.max_browsers:
            logger.info(f"⚡ All browsers full! Creating new instance ({len(self.browsers) + 1}/{self.max_browsers})")
            async with self.lock:
                return await self._create_browser_instance()
        
        # Load balance: return browser with least tabs
        return min(self.browsers, key=lambda b: b.active_tabs)

    @asynccontextmanager
    async def get_page(self, domain: str = None):
        """
        Get a page from available browser instance
        FIXED: Tidak recreate context setiap kali!
        """
        await self.initialize()
        
        browser_instance = await self._get_available_browser()
        
        # Wait for slot
        await browser_instance.semaphore.acquire()
        
        page = None
        try:
            # Create page dengan user agent override TANPA recreate context
            page = await browser_instance.context.new_page()
            
            # Override user agent untuk page ini saja jika perlu
            if domain:
                user_agent = self.get_user_agent(domain)
                await page.set_extra_http_headers({
                    'User-Agent': user_agent,
                    'Accept-Language': 'en-US,en;q=0.9'
                })
            
            # Update stats BEFORE yielding
            browser_instance.active_tabs += 1
            browser_instance.total_requests += 1
            browser_instance.last_used = asyncio.get_event_loop().time()
            self.stats['total_requests'] += 1
            self.stats['active_tabs'] = sum(b.active_tabs for b in self.browsers)
            
            # Update peak
            if self.stats['active_tabs'] > self.stats['peak_active_tabs']:
                self.stats['peak_active_tabs'] = self.stats['active_tabs']
            
            browser_idx = self.browsers.index(browser_instance) + 1
            logger.debug(f"📖 Tab opened [Browser {browser_idx}] - Active: {browser_instance.active_tabs}/{self.max_tabs_per_browser}")
            
            yield page
            
            # Mark as successful if we reach here
            self.stats['successful_requests'] += 1
            
        except Exception as e:
            logger.error(f"❌ Error in page context: {e}")
            self.stats['failed_requests'] += 1
            raise
            
        finally:
            # Cleanup
            if page:
                try:
                    await page.close()
                except Exception as e:
                    logger.error(f"Error closing page: {e}")
            
            browser_instance.active_tabs -= 1
            browser_instance.semaphore.release()
            self.stats['active_tabs'] = sum(b.active_tabs for b in self.browsers)
            
            browser_idx = self.browsers.index(browser_instance) + 1
            logger.debug(f"📕 Tab closed [Browser {browser_idx}] - Active: {browser_instance.active_tabs}/{self.max_tabs_per_browser}")

    async def _cleanup_idle_browsers(self):
        """Background task to cleanup idle browser instances"""
        while True:
            try:
                await asyncio.sleep(60)
                
                async with self.lock:
                    current_time = asyncio.get_event_loop().time()
                    browsers_to_remove = []
                    
                    for browser_instance in self.browsers:
                        if len(self.browsers) <= self.min_browsers:
                            break
                        
                        idle_time = current_time - browser_instance.last_used
                        if (idle_time > self.browser_idle_timeout and 
                            browser_instance.active_tabs == 0):
                            browsers_to_remove.append(browser_instance)
                    
                    for browser_instance in browsers_to_remove:
                        idle_time = current_time - browser_instance.last_used
                        logger.info(f"🧹 Closing idle browser (idle: {int(idle_time)}s, requests served: {browser_instance.total_requests})")
                        
                        try:
                            await browser_instance.context.close()
                            await browser_instance.browser.close()
                        except Exception as e:
                            logger.error(f"Error closing browser: {e}")
                        
                        self.browsers.remove(browser_instance)
                        self.stats['browsers_closed'] += 1
                        
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

    async def close(self):
        """Close all browser instances and playwright"""
        logger.info("🛑 Closing all Playwright resources...")
        
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        for browser_instance in self.browsers:
            try:
                await browser_instance.context.close()
                await browser_instance.browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
        
        self.browsers.clear()
        
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        
        logger.info("✓ All Playwright resources closed")

    def get_stats(self) -> Dict:
        """Get current statistics - REAL TIME"""
        current_active_tabs = sum(b.active_tabs for b in self.browsers)
        
        return {
            **self.stats,
            'active_browsers': len(self.browsers),
            'active_tabs': current_active_tabs,  # Real-time value
            'total_capacity': len(self.browsers) * self.max_tabs_per_browser,
            'capacity_used_percent': round((current_active_tabs / (len(self.browsers) * self.max_tabs_per_browser) * 100) if self.browsers else 0, 2),
            'success_rate': round((self.stats['successful_requests'] / self.stats['total_requests'] * 100) if self.stats['total_requests'] > 0 else 0, 2),
            'browsers_info': [
                {
                    'index': i + 1,
                    'active_tabs': b.active_tabs,
                    'max_tabs': self.max_tabs_per_browser,
                    'total_requests': b.total_requests,
                    'uptime_seconds': int(asyncio.get_event_loop().time() - b.created_at),
                    'idle_seconds': int(asyncio.get_event_loop().time() - b.last_used),
                    'utilization_percent': round((b.active_tabs / self.max_tabs_per_browser * 100), 2)
                }
                for i, b in enumerate(self.browsers)
            ]
        }
    
    def get_health_status(self) -> Dict:
        """Quick health check"""
        stats = self.get_stats()
        
        is_healthy = (
            self.playwright is not None and
            len(self.browsers) >= self.min_browsers and
            stats['capacity_used_percent'] < 90
        )
        
        return {
            'status': 'healthy' if is_healthy else 'degraded',
            'playwright_running': self.playwright is not None,
            'browsers': len(self.browsers),
            'active_tabs': stats['active_tabs'],
            'capacity_used': f"{stats['capacity_used_percent']}%",
            'total_requests': stats['total_requests'],
            'success_rate': f"{stats['success_rate']}%"
        }

# Initialize global manager with configuration
playwright_manager = AdvancedPlaywrightManager(
    max_tabs_per_browser=25,
    max_browsers=3,
    auto_scale=True,
    browser_idle_timeout=900,
    min_browsers=1
)

async def get_page(domain: str = None):
    """Helper function to get a page"""
    return playwright_manager.get_page(domain)


# Helper functions for navigation (unchanged)
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


async def navigate_and_wait_v2(page, url, timeout=30000):
    try:
        blocked_resources = re.compile(r'\.(png|jpg|jpeg|gif|css|woff|woff2|ttf|mp4|webp)$|analytics|tracking|advertisement')
        
        async def handle_route(route):
            if blocked_resources.search(route.request.url):
                await route.abort()
            else:
                await route.continue_()

        await page.set_extra_http_headers({
            "User-Agent": "WhatsApp/2.23.2.72 A"
        })
        
        await page.route("**/*", handle_route)
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception as e:
        logger.error(f"Error navigating to {url}: {str(e)}")
        raise


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