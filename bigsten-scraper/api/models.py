from typing import Literal, Optional
from pydantic import BaseModel, HttpUrl


class ScrapeRequest(BaseModel):
    url: str
    render_js: bool = False
    wait_selector: Optional[str] = None
    wait_ms: int = 1000
    extract: Literal["html", "text"] = "html"
    priority: Literal["high", "normal"] = "normal"


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
