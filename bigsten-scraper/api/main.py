from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from redis.exceptions import ConnectionError as RedisConnectionError
from rq import Queue
from rq.job import JobStatus
from rq.registry import FailedJobRegistry

from config.settings import API_KEY
from api.models import (
    ScrapeRequest,
    ScrapeResponse,
    HealthResponse,
    QueueStatusResponse,
)
from api.queue_manager import (
    redis_conn,
    high_queue,
    normal_queue,
    enqueue_scrape,
    wait_for_job_result,
)

app = FastAPI(title="Bigsten Scraper Engine", version="1.0.0")


# ── Auth helper ──────────────────────────────────────────────────────────────

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Dict bodies pass through unchanged; strings wrapped in {"detail": ...}
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(body: ScrapeRequest, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)

    job_id = enqueue_scrape(
        url=body.url,
        render_js=body.render_js,
        wait_selector=body.wait_selector,
        wait_ms=body.wait_ms,
        extract=body.extract,
        priority=body.priority,
    )

    outcome = wait_for_job_result(job_id, timeout=30)

    if not outcome["success"]:
        error_msg = outcome.get("error", "Unknown error")
        if "Timeout" in error_msg:
            raise HTTPException(
                status_code=504,
                detail={"success": False, "error": error_msg},
            )
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": error_msg},
        )

    result: dict = outcome["result"]
    return ScrapeResponse(**result)


@app.get("/health", response_model=HealthResponse)
async def health(x_api_key: str = Header(...)):
    verify_api_key(x_api_key)

    try:
        redis_conn.ping()
        redis_ok = True
    except RedisConnectionError:
        redis_ok = False

    queue_length = len(high_queue) + len(normal_queue)

    return HealthResponse(
        status="ok" if redis_ok else "degraded",
        redis=redis_ok,
        queue_length=queue_length,
    )


@app.get("/queue/status", response_model=QueueStatusResponse)
async def queue_status(x_api_key: str = Header(...)):
    verify_api_key(x_api_key)

    failed_registry = FailedJobRegistry("failed", connection=redis_conn)

    return QueueStatusResponse(
        high_queue=len(high_queue),
        normal_queue=len(normal_queue),
        failed=len(failed_registry),
    )
