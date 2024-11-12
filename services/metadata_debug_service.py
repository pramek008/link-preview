from typing import Dict, Any
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import logging
import random
import asyncio

logger = logging.getLogger(__name__)

class MetadataDebugService:
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/119.0.0.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
    ]

    @staticmethod
    def get_proxy_config(proxy_url: str) -> Dict:
        """Convert proxy URL to Playwright proxy config with validation"""
        try:
            parsed = urlparse(proxy_url)
            if not all([parsed.scheme, parsed.hostname, parsed.port]):
                raise ValueError("Proxy URL must contain scheme, hostname, and port")
            
            config = {
                "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
            }
            
            if parsed.username and parsed.password:
                config.update({
                    "username": parsed.username,
                    "password": parsed.password
                })
            
            return config
        except Exception as e:
            logger.error(f"Failed to parse proxy URL: {str(e)}")
            raise ValueError(f"Invalid proxy URL format: {str(e)}")

    @staticmethod
    async def extract_metadata_from_page(page, metadata: Dict) -> Dict:
        """Extract metadata from page even if there are navigation issues"""
        try:
            metadata['title'] = await page.title()
            
            # Get meta tags that are available
            meta_tags = await page.evaluate('''
                () => {
                    const metas = document.getElementsByTagName('meta');
                    return Array.from(metas).map(meta => {
                        const attributes = {};
                        for (let attr of meta.attributes) {
                            attributes[attr.name] = attr.value;
                        }
                        return attributes;
                    });
                }
            ''')
            metadata['meta_tags'] = meta_tags

            # Get head HTML
            metadata['head_html'] = await page.evaluate('() => document.head.outerHTML')
            
            # Get final URL after redirects
            metadata['final_url'] = page.url

        except Exception as e:
            logger.warning(f"Error extracting some metadata: {str(e)}")
            if not metadata.get('error'):
                metadata['error'] = f"Partial metadata extraction error: {str(e)}"
        
        return metadata

    @staticmethod
    async def get_page_metadata(url: str, proxy_url: str = None, timeout: int = 30000, max_redirects: int = 2) -> Dict[str, Any]:
        """
        Fetch page metadata with improved redirect and error handling
        
        Args:
            url: Target URL to fetch metadata from
            proxy_url: Optional proxy URL
            timeout: Timeout in milliseconds (default 30s)
            max_redirects: Maximum number of redirects to follow (default 2)
        """
        metadata = {
            'url': url,
            'final_url': None,
            'status': None,
            'headers': {},
            'meta_tags': [],
            'title': None,
            'head_html': None,
            'error': None,
            'proxy_used': bool(proxy_url),
            'redirects': []
        }

        try:
            async with async_playwright() as p:
                browser_args = {
                    "headless": True,
                }

                if proxy_url:
                    try:
                        proxy_config = MetadataDebugService.get_proxy_config(proxy_url)
                        browser_args["proxy"] = proxy_config
                        logger.info(f"Using proxy: {proxy_config['server']}")
                    except Exception as e:
                        logger.error(f"Proxy configuration failed: {str(e)}")
                        metadata['error'] = f"Proxy configuration error: {str(e)}"
                        return metadata

                browser = await p.chromium.launch(**browser_args)
                context = await browser.new_context(
                    user_agent=random.choice(MetadataDebugService.USER_AGENTS),
                    viewport={'width': 1920, 'height': 1080}
                )

                # Configure context to handle redirects
                await context.set_extra_http_headers({
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1'
                })

                page = await context.new_page()
                
                # Listen for response events to track redirects
                async def handle_response(response):
                    if response.request.headers.get('referer') and response.request.method != 'GET':
                        metadata['redirects'].append({
                            'from': response.request.headers['referer'],
                            'status': response.status
                        })

                page.on('response', handle_response)

                try:
                    # Try to navigate with more permissive settings
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=timeout,
                        referer="https://www.google.com/"  # Add referer to help with some sites
                    )
                    
                    if response:
                        metadata['status'] = response.status
                        metadata['headers'] = dict(response.headers)
                        
                        # Extract metadata even if we hit redirect limits
                        await MetadataDebugService.extract_metadata_from_page(page, metadata)
                    
                except PlaywrightTimeout:
                    logger.warning("Navigation timed out, attempting to extract available metadata")
                    await MetadataDebugService.extract_metadata_from_page(page, metadata)
                    if not metadata.get('error'):
                        metadata['error'] = "Navigation timed out, but some metadata was extracted"

                except Exception as e:
                    logger.error(f"Page navigation failed: {str(e)}")
                    # Still try to extract whatever metadata we can
                    await MetadataDebugService.extract_metadata_from_page(page, metadata)
                    if not metadata.get('error'):
                        metadata['error'] = f"Navigation failed: {str(e)}, but some metadata was extracted"

                finally:
                    await browser.close()

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            metadata['error'] = f"Unexpected error: {str(e)}"

        return metadata