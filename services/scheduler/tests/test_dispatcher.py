import asyncio
import json

import pytest

from agentops_common.models import JobStatus, NewJob
from agentops_common.queue import QUEUE_KEY
from app.dag import CycleDetectedError
from app.dispatcher import DuplicateRefError, UnknownDependencyError


async def _drain_queue(redis_client) -> list[str]:
    items = []
    while True:
        raw = await redis_client.lpop(QUEUE_KEY)
        if raw is None:
            break
        items.append(json.loads(raw)["job_id"])
    return items


async def test_submit_batch_rejects_cycles(scheduler):
    jobs = [
        NewJob(ref="a", name="a", depends_on=["b"]),
        NewJob(ref="b", name="b", depends_on=["a"]),
    ]
    with pytest.raises(CycleDetectedError):
        await scheduler.submit_batch(jobs)


async def test_submit_batch_rejects_duplicate_refs(scheduler):
    jobs = [NewJob(ref="a", name="a"), NewJob(ref="a", name="a-again")]
    with pytest.raises(DuplicateRefError):
        await scheduler.submit_batch(jobs)


async def test_submit_batch_rejects_unknown_dependency(scheduler):
    jobs = [NewJob(ref="a", name="a", depends_on=["ghost"])]
    with pytest.raises(UnknownDependencyError):
        await scheduler.submit_batch(jobs)


async def test_job_with_no_dependencies_is_immediately_ready(scheduler):
    jobs = [NewJob(ref="a", name="a")]
    await scheduler.submit_batch(jobs)

    ready_count = await scheduler.refresh_ready_jobs()
    assert ready_count == 1


async def test_job_with_unmet_dependency_is_not_ready(scheduler):
    jobs = [NewJob(ref="a", name="a"), NewJob(ref="b", name="b", depends_on=["a"])]
    await scheduler.submit_batch(jobs)

    ready_count = await scheduler.refresh_ready_jobs()
    assert ready_count == 1  # only "a"


async def test_five_job_dag_mixed_priorities_dispatch_order(scheduler, redis_client):
    """ROADMAP 2.8: 5-job DAG, mixed priorities, correct dispatch order.

    Graph:  j1 -> j3 -\
                        -> j5
            j2 -> j4 -/
    """
    jobs = [
        NewJob(ref="j1", name="j1", priority=1),
        NewJob(ref="j2", name="j2", priority=5),
        NewJob(ref="j3", name="j3", priority=10, depends_on=["j1"]),
        NewJob(ref="j4", name="j4", priority=1, depends_on=["j2"]),
        NewJob(ref="j5", name="j5", priority=100, depends_on=["j3", "j4"]),
    ]
    records = await scheduler.submit_batch(jobs)
    id_by_ref = {ref: record.id for ref, record in records.items()}

    await scheduler.run_once()
    assert await _drain_queue(redis_client) == [id_by_ref["j2"], id_by_ref["j1"]]

    await scheduler.update_status(id_by_ref["j1"], JobStatus.SUCCEEDED)
    await scheduler.update_status(id_by_ref["j2"], JobStatus.SUCCEEDED)

    await scheduler.run_once()
    assert await _drain_queue(redis_client) == [id_by_ref["j3"], id_by_ref["j4"]]

    await scheduler.update_status(id_by_ref["j3"], JobStatus.SUCCEEDED)
    await scheduler.update_status(id_by_ref["j4"], JobStatus.SUCCEEDED)

    await scheduler.run_once()
    assert await _drain_queue(redis_client) == [id_by_ref["j5"]]


async def test_concurrent_dispatch_next_never_double_dispatches(scheduler):
    jobs = [NewJob(ref=f"j{i}", name=f"j{i}", priority=i) for i in range(5)]
    await scheduler.submit_batch(jobs)
    await scheduler.refresh_ready_jobs()

    results = await asyncio.gather(*(scheduler.dispatch_next() for _ in range(10)))
    dispatched = [r for r in results if r is not None]

    assert len(dispatched) == 5
    assert len(set(dispatched)) == 5  # no job claimed twice


async def test_dispatch_next_on_empty_queue_returns_none(scheduler):
    assert await scheduler.dispatch_next() is None
