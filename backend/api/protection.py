"""
protection.py  -  access token and per-IP rate limits for a public server (v1.1.0).

Access token. When PQF_API_TOKEN is set, every request must carry it in the
X-PQF-Token header (compared in constant time). /health stays open so the host's
health check works; GET /music/preview also accepts it as ?token= because the
audio player cannot send headers. When PQF_API_TOKEN is not set (laptop use),
nothing is checked.

Rate limits. Per client IP, per hour: /batch and /video/plan 20 each (each costs
model calls), /guidance generous (it is called about once a second while the
camera is open). Over the limit: HTTP 429 with a plain message, code
"rate_limited" and Retry-After. Behind a proxy (Railway) the client IP is the
first X-Forwarded-For entry. PQF_RATE_LIMIT=off disables the limits (the test
suite, which calls these endpoints many times, sets it).

Neither is a framework criterion; they only protect the server and its AI quota.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

TOKEN_HEADER = "X-PQF-Token"
OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}
QUERY_TOKEN_PREFIXES = ("/music/preview/",)

WINDOW_S = 3600
LIMITS = {"/batch": 20, "/video/plan": 20, "/guidance": 7200}

_hits: dict = defaultdict(deque)
_lock = threading.Lock()

router = APIRouter()


@router.get("/auth/check")
def auth_check():
    """Protected like every other endpoint: 200 means the app's token is accepted."""
    return {"ok": True}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _token_ok(request: Request, expected: str) -> bool:
    given = request.headers.get(TOKEN_HEADER, "")
    if not given and request.url.path.startswith(QUERY_TOKEN_PREFIXES):
        given = request.query_params.get("token", "")
    return hmac.compare_digest(given.encode(), expected.encode())


def _rate_limited(ip: str, path: str) -> int:
    """Seconds to wait if this request is over its limit, else 0 (and counted)."""
    limit = LIMITS.get(path)
    if limit is None or os.environ.get("PQF_RATE_LIMIT", "").lower() == "off":
        return 0
    now = time.time()
    with _lock:
        q = _hits[(ip, path)]
        while q and q[0] <= now - WINDOW_S:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(q[0] + WINDOW_S - now))
        q.append(now)
    return 0


def reset() -> None:
    """Forget all counts (tests)."""
    with _lock:
        _hits.clear()


async def protect(request: Request, call_next):
    path = request.url.path
    if request.method != "OPTIONS" and path not in OPEN_PATHS:
        expected = os.environ.get("PQF_API_TOKEN", "")
        if expected and not _token_ok(request, expected):
            return JSONResponse(status_code=401, content={
                "detail": "This app is not allowed to use the server: the access "
                          "token is wrong or missing.",
                "code": "bad_token"})
        wait = _rate_limited(_client_ip(request), path)
        if wait:
            mins = max(1, round(wait / 60))
            return JSONResponse(status_code=429, headers={"Retry-After": str(wait)}, content={
                "detail": f"Too many requests from this network. Try again in about "
                          f"{mins} minute{'s' if mins != 1 else ''}.",
                "code": "rate_limited", "retry_after_s": wait})
    return await call_next(request)
