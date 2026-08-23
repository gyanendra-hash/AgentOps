import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from redis.asyncio import Redis

from agentops_common.models import (
    JobBatchRequest,
    JobBatchResponse,
    JobResponse,
    JobStatus,
    JobStatusUpdateRequest,
)
from app.config import get_settings
from app.dag import CycleDetectedError
from app.db import create_pool, run_migrations
from app.dispatcher import DuplicateRefError, Scheduler, UnknownDependencyError
from app.leader_election import LeaderElection
from app.postgres_repository import PostgresJobRepository
from app.repository import JobNotCancellableError, JobRecord

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _to_response(record: JobRecord) -> JobResponse:
    return JobResponse(
        id=record.id,
        name=record.name,
        status=record.status,
        priority=record.priority,
        attempt=record.attempt,
        max_retries=record.max_retries,
        payload=record.payload,
        depends_on=record.depends_on,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = await create_pool(settings.database_url)
    await run_migrations(pool, MIGRATIONS_DIR)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)

    repository = PostgresJobRepository(pool)
    leader = LeaderElection(redis, settings.leader_key, settings.leader_ttl_seconds)
    app.state.scheduler = Scheduler(repository, redis, leader)
    app.state.pool = pool
    app.state.redis = redis

    stop_event = asyncio.Event()
    loop_task = asyncio.create_task(
        app.state.scheduler.run_forever(stop_event, settings.dispatch_poll_interval_seconds)
    )

    yield

    stop_event.set()
    await loop_task
    await redis.aclose()
    await pool.close()


app = FastAPI(title="AgentOps Scheduler", lifespan=lifespan)


@app.post("/v1/jobs", response_model=JobBatchResponse, status_code=201)
async def submit_jobs(payload: JobBatchRequest, request: Request) -> JobBatchResponse:
    scheduler: Scheduler = request.app.state.scheduler
    try:
        records = await scheduler.submit_batch(payload.jobs)
    except CycleDetectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (DuplicateRefError, UnknownDependencyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # preserve request order rather than dict iteration order
    ordered = [records[job.ref] for job in payload.jobs]
    return JobBatchResponse(jobs=[_to_response(r) for r in ordered])


@app.get("/v1/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request) -> JobResponse:
    scheduler: Scheduler = request.app.state.scheduler
    record = await scheduler.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_response(record)


@app.get("/v1/jobs", response_model=JobBatchResponse)
async def list_jobs(request: Request, status: JobStatus | None = None) -> JobBatchResponse:
    scheduler: Scheduler = request.app.state.scheduler
    records = await scheduler.list_jobs(status)
    return JobBatchResponse(jobs=[_to_response(r) for r in records])


@app.post("/v1/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, request: Request) -> JobResponse:
    scheduler: Scheduler = request.app.state.scheduler
    try:
        record = await scheduler.cancel_job(job_id)
    except JobNotCancellableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_response(record)


@app.patch("/v1/jobs/{job_id}/status", response_model=JobResponse)
async def update_job_status(
    job_id: str, payload: JobStatusUpdateRequest, request: Request
) -> JobResponse:
    """Called by the worker pool to report execution progress. The scheduler
    owns job state (SRS: "each service owns its data") so the worker pool
    never touches Postgres directly, only this API."""
    scheduler: Scheduler = request.app.state.scheduler
    record = await scheduler.update_status(
        job_id,
        payload.status,
        error=payload.error,
        increment_attempt=payload.increment_attempt,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_response(record)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
