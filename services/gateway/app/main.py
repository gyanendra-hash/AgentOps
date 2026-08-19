from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from app.config import get_settings
from app.rate_limit_client import RateLimiterUnavailableError, check_rate_limit
from app.routing import Router, ServiceUnavailableError

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.router = Router(settings.routing_table)
    app.state.http_client = httpx.AsyncClient(timeout=settings.upstream_timeout_seconds)
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="AgentOps API Gateway", lifespan=lifespan)


def _client_id(request: Request) -> str:
    header_id = request.headers.get("X-Client-Id")
    if header_id:
        return header_id
    if request.client:
        return request.client.host
    return "anonymous"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy(path: str, request: Request) -> Response:
    settings = get_settings()
    client_id = _client_id(request)
    http_client: httpx.AsyncClient = request.app.state.http_client

    try:
        result = await check_rate_limit(http_client, client_id, settings.default_tier)
        if not result.allowed:
            headers = {}
            if result.retry_after is not None:
                headers["Retry-After"] = str(int(result.retry_after) + 1)
            return Response(
                content='{"detail":"rate limit exceeded"}',
                status_code=429,
                headers=headers,
                media_type="application/json",
            )
    except RateLimiterUnavailableError:
        if not settings.fail_open:
            return Response(
                content='{"detail":"rate limiter unavailable"}',
                status_code=503,
                media_type="application/json",
            )

    router: Router = request.app.state.router
    try:
        instance_url = router.next_instance(settings.default_service)
    except ServiceUnavailableError:
        return Response(
            content='{"detail":"no healthy backend instances"}',
            status_code=503,
            media_type="application/json",
        )

    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
    body = await request.body()

    upstream_response = await http_client.request(
        request.method,
        f"{instance_url}/{path}",
        params=request.query_params,
        headers=forward_headers,
        content=body,
    )

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
    )
