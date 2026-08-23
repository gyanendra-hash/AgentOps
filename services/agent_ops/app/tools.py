"""Typed tool schemas + functions wrapping the Scheduler API (ROADMAP 4.1,
4.2), per SRS 6.5.4: each tool is a Pydantic-validated function over an
existing REST endpoint, never a reimplementation of scheduling logic. Tools
flagged `destructive=True` are the ones app/scheduler_agent.py routes
through a confirmation step before executing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, ValidationError

from app.scheduler_client import SchedulerClient


class CreateJobArgs(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    priority: int = 0
    payload: dict = Field(default_factory=dict)


class CancelJobArgs(BaseModel):
    job_id: str = Field(min_length=1)


class GetJobStatusArgs(BaseModel):
    job_id: str = Field(min_length=1)


class ListFailedJobsArgs(BaseModel):
    status: str = "DLQ"  # "DLQ" or "FAILED"


async def _create_job(client: SchedulerClient, args: CreateJobArgs) -> dict:
    return await client.create_job(args.name, priority=args.priority, payload=args.payload)


async def _cancel_job(client: SchedulerClient, args: CancelJobArgs) -> dict:
    return await client.cancel_job(args.job_id)


async def _get_job_status(client: SchedulerClient, args: GetJobStatusArgs) -> dict:
    job = await client.get_job(args.job_id)
    if job is None:
        raise ValueError(f"no job found with id {args.job_id}")
    return job


async def _list_failed_jobs(client: SchedulerClient, args: ListFailedJobsArgs) -> dict:
    jobs = await client.list_jobs(status=args.status)
    return {"jobs": jobs, "count": len(jobs)}


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    destructive: bool
    handler: Callable[[SchedulerClient, BaseModel], Awaitable[Any]]

    def parse_args(self, raw_args: dict) -> BaseModel:
        return self.args_model.model_validate(raw_args)

    async def call(self, client: SchedulerClient, raw_args: dict) -> Any:
        args = self.parse_args(raw_args)
        return await self.handler(client, args)


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="create_job",
            description="Submit a new job to the Scheduler.",
            args_model=CreateJobArgs,
            destructive=False,
            handler=_create_job,
        ),
        ToolSpec(
            name="cancel_job",
            description=(
                "Cancel a job that hasn't started running yet. Destructive: "
                "requires operator confirmation."
            ),
            args_model=CancelJobArgs,
            destructive=True,
            handler=_cancel_job,
        ),
        ToolSpec(
            name="get_job_status",
            description="Look up the current status of a single job by id.",
            args_model=GetJobStatusArgs,
            destructive=False,
            handler=_get_job_status,
        ),
        ToolSpec(
            name="list_failed_jobs",
            description="List jobs currently in the DLQ (or FAILED) status.",
            args_model=ListFailedJobsArgs,
            destructive=False,
            handler=_list_failed_jobs,
        ),
    ]
}


class UnknownToolError(Exception):
    pass


class InvalidToolArgsError(Exception):
    def __init__(self, tool_name: str, validation_error: ValidationError) -> None:
        self.tool_name = tool_name
        self.validation_error = validation_error
        super().__init__(f"invalid arguments for tool '{tool_name}': {validation_error}")


async def execute_tool(client: SchedulerClient, tool_name: str, raw_args: dict) -> Any:
    spec = TOOLS.get(tool_name)
    if spec is None:
        raise UnknownToolError(tool_name)
    try:
        args = spec.parse_args(raw_args)
    except ValidationError as exc:
        raise InvalidToolArgsError(tool_name, exc) from exc
    return await spec.handler(client, args)
