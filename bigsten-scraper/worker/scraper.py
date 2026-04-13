import random
import time
import datetime
from typing import Optional

import requests
import urllib3
from bs4 import BeautifulSoup

from config.settings import WORKER_ID
from worker.user_agents import USER_AGENTS

# Disable SSL warnings (verify=False used for compatibility inside Docker)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BLOCKED_RESOURCES = {"image", "font", "stylesheet", "media", "other"}

COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ro;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _log(level: str, url: str, message: str):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] [{level}] [worker={WORKER_ID}] [url={url}] {message}")


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


def _scrape_requests(url: str, extract: str) -> dict:
    """Scrape using requests library (no JS rendering)."""
    delay = random.uniform(0.5, 2.0)
    time.sleep(delay)

    ua = _random_ua()
    headers = {**COMMON_HEADERS, "User-Agent": ua}

    start = time.time()
    resp = requests.get(url, headers=headers, timeout=15, verify=False)
    duration_ms = int((time.time() - start) * 1000)

    html = resp.text
    text = BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True) if extract == "text" else None

    return {
        "success": True,
        "html": html if extract == "html" else None,
        "text": text,
        "status_code": resp.status_code,
        "worker_id": WORKER_ID,
        "duration_ms": duration_ms,
        "error": None,
    }


def _scrape_playwright(
    url: str,
    wait_selector: Optional[str],
    wait_ms: int,
    extract: str,
) -> dict:
    """Scrape using Playwright with Chromium (JS rendering)."""
    from playwright.sync_api import sync_playwright

    ua = _random_ua()
    start = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=ua,
            ignore_https_errors=True,
        )
        page = context.new_page()

        # Block unnecessary resources to speed up loading
        def block_resources(route, request):
            if request.resource_type in BLOCKED_RESOURCES:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", block_resources)

        page.goto(url, timeout=30000, wait_until="domcontentloaded")

        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=10000)
            except Exception:
                _log("WARN", url, f"wait_selector '{wait_selector}' not found within 10s")
        else:
            page.wait_for_timeout(wait_ms)

        html = page.content()
        browser.close()

    duration_ms = int((time.time() - start) * 1000)
    text = BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True) if extract == "text" else None

    return {
        "success": True,
        "html": html if extract == "html" else None,
        "text": text,
        "status_code": 200,
        "worker_id": WORKER_ID,
        "duration_ms": duration_ms,
        "error": None,
    }


def scrape(
    url: str,
    render_js: bool = False,
    wait_selector: Optional[str] = None,
    wait_ms: int = 1000,
    extract: str = "html",
) -> dict:
    """Core scrape function. Returns a result dict matching ScrapeResponse."""
    _log("INFO", url, f"Starting scrape render_js={render_js} extract={extract}")
    try:
        if render_js:
            result = _scrape_playwright(url, wait_selector, wait_ms, extract)
        else:
            result = _scrape_requests(url, extract)

        _log("INFO", url, f"Done in {result['duration_ms']}ms status={result.get('status_code')}")
        return result

    except Exception as e:
        _log("ERROR", url, f"Scrape failed: {e}")
        return {
            "success": False,
            "html": None,
            "text": None,
            "status_code": None,
            "worker_id": WORKER_ID,
            "duration_ms": None,
            "error": str(e),
        }


def scrape_job(
    url: str,
    render_js: bool,
    wait_selector: Optional[str],
    wait_ms: int,
    extract: str,
) -> dict:
    """RQ job entrypoint — thin wrapper around scrape()."""
    return scrape(
        url=url,
        render_js=render_js,
        wait_selector=wait_selector,
        wait_ms=wait_ms,
        extract=extract,
    )
