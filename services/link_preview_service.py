import logging
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Page
from config.platform_config import PLATFORM_CONFIGS
from models.schemas import LinkPreview
from typing import Optional, List
from fastapi import HTTPException


logger = logging.getLogger(__name__)

class LinkPreviewService:
    @staticmethod
    async def get_element_content(page: Page, selectors: list) -> Optional[str]:
        for selector in selectors:
            try:
                if '[data-testid' in selector:  # Special handling for Twitter
                    element = await page.query_selector(selector)
                    if element:
                        return await element.inner_text()
                else:
                    element = await page.query_selector(selector)
                    if element:
                        return await element.get_attribute('content') or await element.inner_text()
            except Exception as e:
                logger.error(f"Error getting element content: {str(e)}")
                continue
        return None

    @staticmethod
    def get_actual_image_url(base_url: str, image_url: Optional[str]) -> Optional[str]:
        if not image_url or image_url.strip() == '' or image_url.startswith('data:'):
            return None

        if '.svg' in image_url or '.gif' in image_url:
            return None

        if image_url.startswith('//'):
            image_url = f'https:{image_url}'

        if not image_url.startswith('http'):
            base_url = base_url.rstrip('/')
            image_url = image_url.lstrip('/')
            return f'{base_url}/{image_url}'

        return image_url

    @staticmethod
    async def get_main_image_url(page: Page, base_url: str, is_twitter: bool = False) -> Optional[str]:
        if is_twitter:
            # Try to get tweet image first
            tweet_image = await page.query_selector('[data-testid="tweetPhoto"] img')
            if tweet_image:
                src = await tweet_image.get_attribute('src')
                return LinkPreviewService.get_actual_image_url(base_url, src)

        # Try meta tags
        meta_elements = await page.query_selector_all('meta[property="og:image"], meta[name="twitter:image"]')
        for element in meta_elements:
            image_url = await element.get_attribute('content')
            actual_url = LinkPreviewService.get_actual_image_url(base_url, image_url)
            if actual_url:
                return actual_url

        # Fallback to largest image
        try:
            images = await page.query_selector_all('img')
            largest_image = None
            largest_area = 0

            for img in images:
                src = await img.get_attribute('src')
                actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
                if not actual_url:
                    continue

                box = await img.bounding_box()
                if box and box["width"] and box["height"]:
                    area = box["width"] * box["height"]
                    if area > largest_area:
                        largest_area = area
                        largest_image = actual_url

            return largest_image
        except Exception as e:
            logger.error(f"Error finding largest image: {str(e)}")
            return None

    @staticmethod
    async def get_link_preview(url: str) -> Optional[LinkPreview]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'
            )
            
            # Set up route handling
            await context.route("**/*", lambda route, request: 
                route.continue_() if request.resource_type in ['document', 'script', 'image'] else route.abort())

            page = await context.new_page()
            
            try:
                logger.info(f"Fetching preview for URL: {url}")
                response = await page.goto(url, wait_until="networkidle")
                final_url = response.url
                domain = urlparse(final_url).netloc
                
                # Special handling for Twitter
                is_twitter = 'twitter.com' in domain
                if is_twitter:
                    # Wait for tweet content to load
                    await page.wait_for_selector('[data-testid="tweetText"]', timeout=5000)
                
                config = PLATFORM_CONFIGS.get(domain, PLATFORM_CONFIGS["default"])
                
                main_image = await LinkPreviewService.get_main_image_url(
                    page, 
                    final_url,
                    is_twitter=is_twitter
                )
                
                preview = LinkPreview(
                    url=final_url,
                    title=await LinkPreviewService.get_element_content(page, config.selectors.title),
                    description=await LinkPreviewService.get_element_content(page, config.selectors.description),
                    image=main_image
                )
                
                logger.info(f"Successfully generated preview for URL: {final_url}")
                return preview
                
            except Exception as e:
                logger.error(f"Error generating preview for URL {url}: {str(e)}")
                return None
                
            finally:
                await browser.close()
    
    @staticmethod
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
                
    @staticmethod
    async def get_all_images(page: Page, base_url: str) -> List[str]:
        images = await page.query_selector_all("img")
        image_urls = []
        
        for img in images:
            src = await img.get_attribute("src")
            actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
            if actual_url:
                image_urls.append(actual_url)
                
        return image_urls

    @staticmethod
    async def get_images(url: str) :
        if not url:
            raise HTTPException(status_code=400, detail="URL parameter is required")
            
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            
            page = await context.new_page()
            
            # Configure request interception
            async def handle_route(route):
                if route.request.resource_type in ["document", "script", "image"]:
                    await route.continue_()
                else:
                    await route.abort()
                    
            await page.route("**/*", handle_route)
                
            try:
                # Navigate to the URL
                await page.goto(url, wait_until="networkidle", timeout=30000)
                final_url = page.url
                
                # Get all images
                image_urls = await LinkPreviewService.get_all_images(page, final_url)
                
                if not image_urls:
                    raise HTTPException(status_code=400, detail="No images found")
                    
                return image_urls
                
            except Exception as e:
                print(f"Error processing request: {str(e)}")
                raise HTTPException(status_code=500, detail="Internal server error")
            finally:
                await browser.close()