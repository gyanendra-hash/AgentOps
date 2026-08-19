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
