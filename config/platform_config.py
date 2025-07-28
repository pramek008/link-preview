from dataclasses import dataclass
from typing import List, Dict

@dataclass
class PlatformSelectors:
    title: List[str]
    description: List[str]
    image: List[str]

class PlatformConfig:
    def __init__(self, selectors: PlatformSelectors):
        self.selectors = selectors

PLATFORM_CONFIGS: Dict[str, PlatformConfig] = {
    "default": PlatformConfig(PlatformSelectors(
        title=['meta[property="og:title"]', 'meta[name="twitter:title"]', 'title'],
        description=['meta[property="og:description"]', 'meta[name="twitter:description"]', 'meta[name="description"]'],
        image=['meta[property="og:image"]', 'meta[name="twitter:image"]']
    )),
    "twitter.com": PlatformConfig(PlatformSelectors(
        title=['[data-testid="tweetText"]', 'meta[property="og:title"]'],
        description=['[data-testid="tweetText"]', 'meta[property="og:description"]'],
        image=['[data-testid="tweetPhoto"] img', 'meta[property="og:image"]']
    )),
    "tiktok.com": PlatformConfig(PlatformSelectors(
        title=[
            '[data-e2e="browse-video-desc"]',
            '[data-e2e="video-desc"]', 
            'meta[property="og:title"]',
            'title'
        ],
        description=[
            '[data-e2e="browse-video-desc"]',
            '[data-e2e="video-desc"]',
            'meta[property="og:description"]',
            'meta[name="description"]'
        ],
        image=[
            '[data-e2e="browse-video-cover"] img',
            'meta[property="og:image"]',
            'meta[name="twitter:image"]'
        ]
    )),
    "tokopedia.com": PlatformConfig(PlatformSelectors(
        title=[
            '[data-testid="lblPDPProductName"]',
            'h1[data-testid="lblPDPProductName"]',
            '.css-1os9jjn',
            'meta[property="og:title"]',
            'title'
        ],
        description=[
            '[data-testid="lblPDPDescriptionProduk"]',
            '.css-g5kl8m',
            'meta[property="og:description"]',
            'meta[name="description"]'
        ],
        image=[
            '[data-testid="PDPImageMain"] img',
            '.css-1c345mg img',
            'meta[property="og:image"]'
        ]
    )),
    "shopee.co.id": PlatformConfig(PlatformSelectors(
        title=[
            '[data-testid="pdp-product-title"]',
            '.pdp-product-title',
            '._3aWaN4 span',
            'meta[property="og:title"]',
            'title'
        ],
        description=[
            '[class*="product-detail"]',
            '.pdp-product-description',
            'meta[property="og:description"]',
            'meta[name="description"]'
        ],
        image=[
            '[class*="product-image"] img',
            '.pdp-product-image img',
            '._2zr5iX img',
            'meta[property="og:image"]'
        ]
    )),
    "amazon.com": PlatformConfig(PlatformSelectors(
        title=[
            '#productTitle',
            'span#productTitle',
            'meta[property="og:title"]',
            'title'
        ],
        description=[
            '#feature-bullets ul',
            '[data-feature-name="featurebullets"]',
            'meta[property="og:description"]',
            'meta[name="description"]'
        ],
        image=[
            '#landingImage',
            '[data-old-hires]',
            '.a-dynamic-image',
            'meta[property="og:image"]'
        ]
    )),
    "facebook.com": PlatformConfig(PlatformSelectors(
        title=['meta[property="og:title"]', 'meta[name="twitter:title"]'],
        description=['meta[property="og:description"]', 'meta[name="twitter:description"]'],
        image=['meta[property="og:image"]', 'meta[name="twitter:image"]']
    )),
    "youtube.com": PlatformConfig(PlatformSelectors(
        title=['meta[property="og:title"]', 'meta[name="twitter:title"]'],
        description=['meta[property="og:description"]', 'meta[name="twitter:description"]'],
        image=['meta[property="og:image"]', 'meta[name="twitter:image"]']
    )),
    "youtu.be": PlatformConfig(PlatformSelectors(
        title=['meta[property="og:title"]', 'meta[name="twitter:title"]'],
        description=['meta[property="og:description"]', 'meta[name="twitter:description"]'],
        image=['meta[property="og:image"]', 'meta[name="twitter:image"]']
    )),
    "linkedin.com": PlatformConfig(PlatformSelectors(
        title=['meta[property="og:title"]', 'meta[name="twitter:title"]'],
        description=['meta[property="og:description"]', 'meta[name="twitter:description"]'],
        image=['meta[property="og:image"]', 'meta[name="twitter:image"]']
    ))
}
