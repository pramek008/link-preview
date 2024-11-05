from pydantic import BaseModel
from typing import Optional

class LinkPreview(BaseModel):
    url: str
    title: Optional[str]
    description: Optional[str]
    image: Optional[str]
