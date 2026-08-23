import pytest

from agentops_common.models import JobStatus, NewJob
from app.repository import JobNotCancellableError


async def test_list_jobs_with_no_filter_returns_all(scheduler):
    await scheduler.submit_batch([NewJob(ref="a", name="a"), NewJob(ref="b", name="b")])

    records = await scheduler.list_jobs()

    assert len(records) == 2


async def test_list_jobs_filters_by_status(scheduler):
    records = await scheduler.submit_batch([NewJob(ref="a", name="a"), NewJob(ref="b", name="b")])
    await scheduler.update_status(records["a"].id, JobStatus.DLQ, error="boom")

    dlq_jobs = await scheduler.list_jobs(JobStatus.DLQ)
    pending_jobs = await scheduler.list_jobs(JobStatus.PENDING)

    assert [r.id for r in dlq_jobs] == [records["a"].id]
    assert [r.id for r in pending_jobs] == [records["b"].id]


async def test_cancel_pending_job_succeeds(scheduler):
    records = await scheduler.submit_batch([NewJob(ref="a", name="a")])

    cancelled = await scheduler.cancel_job(records["a"].id)

    assert cancelled.status == JobStatus.CANCELLED


async def test_cancel_ready_job_succeeds(scheduler):
    records = await scheduler.submit_batch([NewJob(ref="a", name="a")])
    await scheduler.refresh_ready_jobs()

    cancelled = await scheduler.cancel_job(records["a"].id)

    assert cancelled.status == JobStatus.CANCELLED


async def test_cancel_dispatched_job_is_refused(scheduler):
    records = await scheduler.submit_batch([NewJob(ref="a", name="a")])
    await scheduler.refresh_ready_jobs()
    await scheduler.dispatch_next()

    with pytest.raises(JobNotCancellableError):
        await scheduler.cancel_job(records["a"].id)


async def test_cancel_unknown_job_returns_none(scheduler):
    assert await scheduler.cancel_job("does-not-exist") is None
