import logging
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Page
from config.platform_config import PLATFORM_CONFIGS
from models.schemas import LinkPreview
from typing import Optional, List
from fastapi import HTTPException
import asyncio

logger = logging.getLogger(__name__)

class LinkPreviewService:
    
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

    @staticmethod
    async def get_element_content(page: Page, selectors: list) -> Optional[str]:
        for selector in selectors:
            try:
                # Special handling for data-testid and data-e2e selectors
                if '[data-testid' in selector or '[data-e2e' in selector:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        if text and text.strip():
                            return text.strip()
                else:
                    element = await page.query_selector(selector)
                    if element:
                        # Try content attribute first, then inner_text
                        content = await element.get_attribute('content')
                        if content and content.strip():
                            return content.strip()
                        
                        text = await element.inner_text()
                        if text and text.strip():
                            return text.strip()
            except Exception as e:
                logger.error(f"Error getting element content with selector {selector}: {str(e)}")
                continue
        return None

    @staticmethod
    def get_actual_image_url(base_url: str, image_url: Optional[str]) -> Optional[str]:
        if not image_url or image_url.strip() == '' or image_url.startswith('data:'):
            return None
        
        # Skip very small images or common placeholders, but allow YouTube thumbnails
        if any(x in image_url.lower() for x in ['.svg', 'placeholder', 'default']) and 'ytimg.com' not in image_url.lower():
            return None
        
        # Allow .gif for YouTube (some thumbnails might be gif)
        if '.gif' in image_url.lower() and 'ytimg.com' not in image_url.lower():
            return None
            
        if image_url.startswith('//'):
            image_url = f'https:{image_url}'
        elif not image_url.startswith('http'):
            base_url = base_url.rstrip('/')
            image_url = image_url.lstrip('/')
            return f'{base_url}/{image_url}'
        
        return image_url

    @staticmethod
    async def get_main_image_url(page: Page, base_url: str, domain: str) -> Optional[str]:
        try:
            # E-commerce specific image handling
            if 'tokopedia.com' in domain:
                tokped_selectors = [
                    '[data-testid="PDPImageMain"] img',
                    '.css-1c345mg img',
                    '.fade-appear-done img',
                    'img[alt*="product"]'
                ]
                
                for selector in tokped_selectors:
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            src = await element.get_attribute('src')
                            if not src:
                                src = await element.get_attribute('data-src')
                            actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
                            if actual_url and 'product' in actual_url:
                                return actual_url
                    except Exception:
                        continue

            elif 'shopee.co.id' in domain:
                shopee_selectors = [
                    '[class*="product-image"] img',
                    '.pdp-product-image img',
                    '._2zr5iX img',
                    'img[alt*="product"]',
                    'div[style*="background-image"]'
                ]
                
                for selector in shopee_selectors:
                    try:
                        if 'background-image' in selector:
                            element = await page.query_selector(selector)
                            if element:
                                style = await element.get_attribute('style')
                                if style and 'background-image' in style:
                                    import re
                                    match = re.search(r'background-image:\s*url\(["\']?([^"\']+)["\']?\)', style)
                                    if match:
                                        img_url = match.group(1)
                                        actual_url = LinkPreviewService.get_actual_image_url(base_url, img_url)
                                        if actual_url:
                                            return actual_url
                        else:
                            element = await page.query_selector(selector)
                            if element:
                                src = await element.get_attribute('src')
                                if not src:
                                    src = await element.get_attribute('data-src')
                                actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
                                if actual_url:
                                    return actual_url
                    except Exception:
                        continue

            elif 'amazon.com' in domain or 'amazon.co.id' in domain:
                amazon_selectors = [
                    '#landingImage',
                    '[data-old-hires]',
                    '.a-dynamic-image',
                    '#imgTagWrapperId img'
                ]
                
                for selector in amazon_selectors:
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            # Amazon sometimes has high-res image in data attributes
                            src = await element.get_attribute('data-old-hires')
                            if not src:
                                src = await element.get_attribute('src')
                            if not src:
                                src = await element.get_attribute('data-src')
                            actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
                            if actual_url:
                                return actual_url
                    except Exception:
                        continue

            # TikTok specific image handling
            elif 'tiktok.com' in domain:
                # Try TikTok specific selectors first
                tiktok_selectors = [
                    '[data-e2e="browse-video-cover"] img',
                    'img[alt*="video"]',
                    'video[poster]'
                ]
                
                for selector in tiktok_selectors:
                    try:
                        if selector == 'video[poster]':
                            element = await page.query_selector(selector)
                            if element:
                                poster = await element.get_attribute('poster')
                                if poster:
                                    return LinkPreviewService.get_actual_image_url(base_url, poster)
                        else:
                            element = await page.query_selector(selector)
                            if element:
                                src = await element.get_attribute('src')
                                actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
                                if actual_url:
                                    return actual_url
                    except Exception:
                        continue

            # Twitter specific image handling
            elif 'twitter.com' in domain or 'x.com' in domain:
                tweet_image = await page.query_selector('[data-testid="tweetPhoto"] img')
                if tweet_image:
                    src = await tweet_image.get_attribute('src')
                    actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
                    if actual_url:
                        return actual_url

            # Try meta tags for all platforms
            logger.info(f"Trying meta tags for domain: {domain}")
            meta_selectors = [
                'meta[property="og:image"]',
                'meta[name="twitter:image"]',
                'meta[property="og:image:url"]'
            ]
            
            for selector in meta_selectors:
                try:
                    logger.info(f"Trying meta selector: {selector}")
                    element = await page.query_selector(selector)
                    if element:
                        image_url = await element.get_attribute('content')
                        logger.info(f"Found meta image URL: {image_url}")
                        if image_url:
                            actual_url = LinkPreviewService.get_actual_image_url(base_url, image_url)
                            logger.info(f"Processed meta image URL: {actual_url}")
                            if actual_url:
                                return actual_url
                except Exception as e:
                    logger.error(f"Error with meta selector {selector}: {str(e)}")
                    continue

            # Fallback to largest image (only for non-ecommerce sites to avoid clutter)
            if not any(site in domain for site in ['tokopedia.com', 'shopee.co.id', 'amazon.com']):
                images = await page.query_selector_all('img')
                largest_image = None
                largest_area = 0
                
                for img in images[:10]:  # Limit to first 10 images for performance
                    try:
                        src = await img.get_attribute('src')
                        actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
                        if not actual_url:
                            continue
                        
                        box = await img.bounding_box()
                        if box and box["width"] and box["height"]:
                            area = box["width"] * box["height"]
                            if area > largest_area and area > 10000:  # Minimum size threshold
                                largest_area = area
                                largest_image = actual_url
                    except Exception:
                        continue
                        
                return largest_image
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding image for {domain}: {str(e)}")
            return None

    @staticmethod
    async def setup_page_optimizations(page: Page, domain: str):
        """Setup page optimizations based on domain"""
        # Sites that need images for proper preview
        needs_images = [
            'tokopedia.com', 'shopee.co.id', 'amazon.com', 'bukalapak.com', 'blibli.com',
            'youtube.com', 'youtu.be'  # YouTube needs images for thumbnails
        ]
        
        if any(site in domain for site in needs_images):
            # Allow images for sites that need them
            await page.route("**/*", lambda route, request: (
                route.continue_() if request.resource_type in ['document', 'script', 'xhr', 'fetch', 'image'] 
                else route.abort()
            ))
        else:
            # Block unnecessary resources for faster loading
            await page.route("**/*", lambda route, request: (
                route.continue_() if request.resource_type in ['document', 'script', 'xhr', 'fetch'] 
                else route.abort()
            ))
        
        # Set viewport for mobile sites like TikTok
        if 'tiktok.com' in domain:
            await page.set_viewport_size({"width": 375, "height": 667})
        else:
            await page.set_viewport_size({"width": 1280, "height": 720})

    @staticmethod
    async def get_link_preview(url: str) -> Optional[LinkPreview]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--no-first-run',
                    '--disable-extensions'
                ]
            )
            
            domain = urlparse(url).netloc
            user_agent = LinkPreviewService.get_user_agent(domain)
            
            context = await browser.new_context(
                user_agent=user_agent,
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9'
                }
            )
            
            page = await context.new_page()
            
            try:
                # Setup optimizations
                await LinkPreviewService.setup_page_optimizations(page, domain)
                
                logger.info(f"Fetching preview for URL: {url}")
                
                # Navigate with shorter timeout and different wait strategy
                response = await page.goto(
                    url, 
                    wait_until="domcontentloaded",  # Changed from networkidle
                    timeout=15000  # Increased for e-commerce sites
                )
                
                if not response or response.status >= 400:
                    logger.error(f"Failed to load page: {response.status if response else 'No response'}")
                    return None
                
                final_url = response.url
                parsed_domain = urlparse(final_url).netloc
                
                # Wait for specific content based on platform
                if 'tokopedia.com' in parsed_domain:
                    try:
                        # Wait for either product name or meta tags to load
                        await page.wait_for_selector('[data-testid="lblPDPProductName"], meta[property="og:title"]', timeout=8000)
                        await asyncio.sleep(2)  # Extra wait for JS to populate meta tags
                    except:
                        pass
                elif 'shopee.co.id' in parsed_domain:
                    try:
                        await page.wait_for_selector('[data-testid="pdp-product-title"], meta[property="og:title"]', timeout=8000)
                        await asyncio.sleep(2)  # Extra wait for JS to populate meta tags
                    except:
                        pass
                elif 'amazon.com' in parsed_domain or 'amazon.co.id' in parsed_domain:
                    try:
                        await page.wait_for_selector('#productTitle, meta[property="og:title"]', timeout=8000)
                        await asyncio.sleep(1)
                    except:
                        pass
                elif 'tiktok.com' in parsed_domain:
                    try:
                        await page.wait_for_selector('[data-e2e="browse-video-desc"], [data-e2e="video-desc"]', timeout=5000)
                    except:
                        pass  # Continue even if specific selector not found
                elif 'twitter.com' in parsed_domain or 'x.com' in parsed_domain:
                    try:
                        await page.wait_for_selector('[data-testid="tweetText"]', timeout=5000)
                    except:
                        pass
                
                config = PLATFORM_CONFIGS.get(parsed_domain, PLATFORM_CONFIGS["default"])
                
                # Get content
                title = await LinkPreviewService.get_element_content(page, config.selectors.title)
                description = await LinkPreviewService.get_element_content(page, config.selectors.description)
                main_image = await LinkPreviewService.get_main_image_url(page, final_url, parsed_domain)
                
                preview = LinkPreview(
                    url=final_url,
                    title=title,
                    description=description,
                    image=main_image
                )
                
                logger.info(f"Successfully generated preview for URL: {final_url}")
                logger.info(f"Title: {title}")
                logger.info(f"Description: {description}")
                logger.info(f"Image: {main_image}")
                
                return preview
                
            except Exception as e:
                logger.error(f"Error generating preview for URL {url}: {str(e)}")
                return None
            finally:
                await browser.close()

    @staticmethod
    async def get_original_url(url: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            
            # Block resources for faster loading
            await context.route("**/*", lambda route, request: (
                route.continue_() if request.resource_type in ['document'] 
                else route.abort()
            ))
            
            page = await context.new_page()
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=5000)
                return response.url
            except Exception as e:
                logger.error(f"An error occurred: {e}")
                return url
            finally:
                await browser.close()

    @staticmethod
    async def get_all_images(page: Page, base_url: str) -> List[str]:
        images = await page.query_selector_all("img")
        image_urls = []
        
        for img in images:
            try:
                src = await img.get_attribute("src")
                actual_url = LinkPreviewService.get_actual_image_url(base_url, src)
                if actual_url:
                    image_urls.append(actual_url)
            except Exception:
                continue
                
        return image_urls

    @staticmethod
    async def get_images(url: str):
        if not url:
            raise HTTPException(status_code=400, detail="URL parameter is required")
            
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                final_url = page.url
                image_urls = await LinkPreviewService.get_all_images(page, final_url)
                
                if not image_urls:
                    raise HTTPException(status_code=400, detail="No images found")
                    
                return image_urls
                
            except Exception as e:
                logger.error(f"Error processing request: {str(e)}")
                raise HTTPException(status_code=500, detail="Internal server error")
            finally:
                await browser.close()
