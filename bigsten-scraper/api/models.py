import re
from typing import Literal, Optional
from urllib.parse import urlsplit
from pydantic import BaseModel, HttpUrl, field_validator


class ScrapeRequest(BaseModel):
    url: str
    render_js: bool = False
    wait_selector: Optional[str] = None
    wait_ms: int = 1000
    extract: Literal["html", "text"] = "html"
    priority: Literal["high", "normal"] = "normal"

    @field_validator("url")
    @classmethod
    def no_ebay(cls, url):
        # eBay data must come only via official APIs and the deletion ledger; never into Redis/logs here.
        if re.search(r"(^|\.)ebay(img)?\.[a-z.]+$", (urlsplit(url).hostname or "").lower()):
            raise ValueError("eBay pages are not scraped; use the official API integration")
        return url


class ScrapeResponse(BaseModel):
    success: bool
    html: Optional[str] = None
    text: Optional[str] = None
    status_code: Optional[int] = None
    worker_id: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    redis: bool
    queue_length: int


class QueueStatusResponse(BaseModel):
    high_queue: int
    normal_queue: int
    failed: int
