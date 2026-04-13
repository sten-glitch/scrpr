import time
from redis import Redis
from rq import Queue
from rq.job import Job, JobStatus
from config.settings import REDIS_URL

# Shared Redis connection
redis_conn = Redis.from_url(REDIS_URL)

# Queues
high_queue = Queue("high", connection=redis_conn)
normal_queue = Queue("normal", connection=redis_conn)


def enqueue_scrape(
    url: str,
    render_js: bool,
    wait_selector: str | None,
    wait_ms: int,
    extract: str,
    priority: str,
) -> str:
    """
    Enqueue a scrape job. Returns the job ID.
    Uses string reference so the API never imports Playwright.
    """
    queue = high_queue if priority == "high" else normal_queue

    job = queue.enqueue(
        "worker.scraper.scrape_job",
        url,
        render_js,
        wait_selector,
        wait_ms,
        extract,
        job_timeout=45,
    )
    return job.id


def wait_for_job_result(job_id: str, timeout: int = 30) -> dict:
    """
    Poll job status every 0.5s until finished or timeout.
    Compatible with RQ 1.x where job.result(timeout=...) is unreliable.
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        job = Job.fetch(job_id, connection=redis_conn)
        status = job.get_status()

        if status == JobStatus.FINISHED:
            return {"success": True, "result": job.result}

        if status == JobStatus.FAILED:
            exc = job.exc_info or "Worker failed with unknown error"
            return {"success": False, "error": str(exc)}

        time.sleep(0.5)

    return {"success": False, "error": "Timeout waiting for scrape result"}
