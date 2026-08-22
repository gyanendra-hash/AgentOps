import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from agentops_common.queue import list_dlq
from app.config import get_settings
from app.redis_client import get_redis
from app.scheduler_client import SchedulerClient
from app.worker import Worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    redis = get_redis()
    http_client = httpx.AsyncClient(timeout=5.0)
    scheduler_client = SchedulerClient(http_client, settings.scheduler_url)

    app.state.redis = redis
    app.state.worker = Worker(
        redis,
        scheduler_client,
        max_retries=settings.max_retries,
        base_backoff_seconds=settings.base_backoff_seconds,
        poll_timeout_seconds=settings.poll_timeout_seconds,
    )

    stop_event = asyncio.Event()
    loop_task = asyncio.create_task(app.state.worker.run_forever(stop_event))

    yield

    stop_event.set()
    await loop_task
    await http_client.aclose()
    await redis.aclose()


app = FastAPI(title="AgentOps Worker Pool", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    redis = get_redis()
    await redis.ping()
    return {"status": "ok"}


@app.get("/v1/dlq")
async def get_dlq(limit: int = 100) -> dict:
    redis = get_redis()
    items = await list_dlq(redis, limit=limit)
    return {"jobs": items}
