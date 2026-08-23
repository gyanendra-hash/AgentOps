from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RateLimitCheckRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=256)
    tier: str = "default"
    cost: int = Field(default=1, ge=1)


class RateLimitCheckResponse(BaseModel):
    allowed: bool
    algorithm: Literal["token_bucket", "sliding_window"]
    remaining: float
    limit: float
    retry_after: Optional[float] = None


class RateLimitStatusResponse(BaseModel):
    """Current bucket state for a client/tier, without consuming a request
    (used by the Monitor Agent, Milestone 5)."""

    algorithm: Literal["token_bucket", "sliding_window"]
    remaining: float
    limit: float


class JobStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRY = "RETRY"
    FAILED = "FAILED"
    DLQ = "DLQ"
    CANCELLED = "CANCELLED"


class NewJob(BaseModel):
    """One job in a batch submission. `ref` is a client-chosen id, unique within
    the batch, used to express dependencies between jobs that don't have a
    database id yet."""

    ref: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    priority: int = Field(default=0, description="Higher value = dispatched sooner")
    payload: dict = Field(default_factory=dict)
    max_retries: int = Field(default=3, ge=0, le=20)
    depends_on: list[str] = Field(
        default_factory=list, description="`ref`s of other jobs in this batch"
    )


class JobBatchRequest(BaseModel):
    jobs: list[NewJob] = Field(min_length=1, max_length=500)


class JobResponse(BaseModel):
    id: str
    name: str
    status: JobStatus
    priority: int
    attempt: int
    max_retries: int
    payload: dict
    depends_on: list[str]
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JobBatchResponse(BaseModel):
    jobs: list[JobResponse]


class JobStatusUpdateRequest(BaseModel):
    status: JobStatus
    error: Optional[str] = None
    increment_attempt: bool = False


class JobStatsResponse(BaseModel):
    """Job counts per status -- "queue depth" for the Monitor Agent
    (Milestone 5). Only non-zero statuses are included."""

    counts: dict[JobStatus, int]
