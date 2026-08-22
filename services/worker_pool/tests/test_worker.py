import time

from agentops_common.models import JobStatus
from agentops_common.queue import pop_job, push_job


async def test_successful_job_transitions_to_succeeded(worker, scheduler_client, redis_client):
    job_id = scheduler_client.seed(payload={})

    await worker.process_one(job_id, {})

    assert scheduler_client.jobs[job_id].status == JobStatus.SUCCEEDED
    assert [s for _, s in scheduler_client.status_history] == [
        JobStatus.RUNNING,
        JobStatus.SUCCEEDED,
    ]


async def test_failed_job_within_retry_budget_goes_to_retry_and_is_requeued(
    worker, scheduler_client, redis_client
):
    job_id = scheduler_client.seed(payload={"simulate_failure": True}, attempt=0, max_retries=3)

    await worker.process_one(job_id, {"simulate_failure": True})

    assert scheduler_client.jobs[job_id].status == JobStatus.RETRY
    assert scheduler_client.jobs[job_id].attempt == 1
    assert scheduler_client.jobs[job_id].error == "simulated failure"

    # scheduled into the delayed set, not immediately requeued
    assert await pop_job(redis_client, timeout=0.01) is None


async def test_job_exhausting_retries_goes_to_dlq(worker, scheduler_client, redis_client):
    job_id = scheduler_client.seed(payload={"simulate_failure": True}, attempt=2, max_retries=3)

    await worker.process_one(job_id, {"simulate_failure": True})

    assert scheduler_client.jobs[job_id].status == JobStatus.DLQ
    assert scheduler_client.jobs[job_id].attempt == 3

    from agentops_common.queue import list_dlq

    dlq_items = await list_dlq(redis_client)
    assert len(dlq_items) == 1
    assert dlq_items[0]["job_id"] == job_id


async def test_run_once_promotes_due_retry_before_polling_queue(worker, scheduler_client, redis_client):
    job_id = scheduler_client.seed(payload={})
    from agentops_common.queue import schedule_retry

    await schedule_retry(redis_client, job_id, {"foo": "bar"}, ready_at=time.time() - 1)

    processed = await worker.run_once()

    assert processed is True
    assert scheduler_client.jobs[job_id].status == JobStatus.SUCCEEDED


async def test_run_once_returns_false_when_queue_empty(worker):
    assert await worker.run_once() is False


async def test_process_one_picks_up_job_pushed_by_scheduler(worker, scheduler_client, redis_client):
    job_id = scheduler_client.seed(payload={"x": 1})
    await push_job(redis_client, job_id, {"x": 1})

    job = await pop_job(redis_client, timeout=0.1)
    assert job is not None
    await worker.process_one(job["job_id"], job["payload"])

    assert scheduler_client.jobs[job_id].status == JobStatus.SUCCEEDED
