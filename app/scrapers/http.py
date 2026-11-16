"""HTTP client shared by all job board scrapers."""

import httpx

USER_AGENT = "job-discovery-agent/0.1"


def create_http_client(timeout_seconds: float = 30.0) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )
