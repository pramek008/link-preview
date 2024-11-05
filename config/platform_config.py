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
    "default": PlatformConfig(
        PlatformSelectors(
            title=['meta[property="og:title"]', 'meta[name="twitter:title"]', 'title'],
            description=['meta[property="og:description"]', 'meta[name="twitter:description"]', 'meta[name="description"]'],
            image=['meta[property="og:image"]', 'meta[name="twitter:image"]']
        )
    ),
    "twitter.com": PlatformConfig(
        PlatformSelectors(
            title=['[data-testid="tweetText"]', 'meta[property="og:title"]'],
            description=['[data-testid="tweetText"]', 'meta[property="og:description"]'],
            image=['[data-testid="tweetPhoto"] img', 'meta[property="og:image"]']
        )
    ),
    "facebook.com": PlatformConfig(
        PlatformSelectors(
            title=['meta[property="og:title"]', 'meta[name="twitter:title"]'],
            description=['meta[property="og:description"]', 'meta[name="twitter:description"]'],
            image=['meta[property="og:image"]', 'meta[name="twitter:image"]'],
        )
    ),
    "youtube.com": PlatformConfig(
        PlatformSelectors(
            title=['meta[property="og:title"]', 'meta[name="twitter:title"]'],
            description=['meta[property="og:description"]', 'meta[name="twitter:description"]'],
            image=['meta[property="og:image"]', 'meta[name="twitter:image"]'],
        )
    ),
    "linkedin.com": PlatformConfig(
        PlatformSelectors(
            title=['meta[property="og:title"]', 'meta[name="twitter:title"]'],
            description=['meta[property="og:description"]', 'meta[name="twitter:description"]'],
            image=['meta[property="og:image"]', 'meta[name="twitter:image"]'],
        )
    ),
    "twitter.com": PlatformConfig(
        PlatformSelectors(
            title=['meta[property="og:title"]', 'meta[name="twitter:title"]'],
            description=['meta[property="og:description"]', 'meta[name="twitter:description"]'],
            image=['meta[property="og:image"]', 'meta[name="twitter:image"]'],
        )
    ),
    # ... other platform configs remain the same
}