from playwright.async_api import async_playwright
import logging
from typing import Dict, Any
import json

logger = logging.getLogger(__name__)

class MetadataDebugService:
    @staticmethod
    async def get_page_metadata(url: str) -> Dict[str, Any]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )

            # Add extra headers to appear more like a real browser
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
            metadata = {
                'url': url,
                'status': None,
                'headers': {},
                'meta_tags': [],
                'title': None,
                'head_html': None,
                'error': None
            }

            try:
                logger.info(f"Fetching metadata for URL: {url}")
                
                # Navigate to page
                response = await page.goto(url, wait_until="networkidle", timeout=30000)
                metadata['status'] = response.status if response else None
                metadata['headers'] = dict(response.headers) if response else {}

                # Get page title
                metadata['title'] = await page.title()

                # Get all meta tags
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

                # Get complete head HTML
                metadata['head_html'] = await page.evaluate('() => document.head.outerHTML')

                logger.info(f"Successfully fetched metadata for URL: {url}")

            except Exception as e:
                error_msg = f"Error fetching metadata: {str(e)}"
                logger.error(error_msg)
                metadata['error'] = error_msg

            finally:
                await browser.close()

            return metadata

            