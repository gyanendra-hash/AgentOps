import httpx
import pytest
import respx

from app.tools import TOOLS, InvalidToolArgsError, UnknownToolError, execute_tool
from tests.conftest import SCHEDULER_BASE_URL


def test_tool_registry_has_expected_tools():
    assert set(TOOLS) == {"create_job", "cancel_job", "get_job_status", "list_failed_jobs"}


def test_only_cancel_job_is_destructive():
    assert TOOLS["cancel_job"].destructive is True
    assert TOOLS["create_job"].destructive is False
    assert TOOLS["get_job_status"].destructive is False
    assert TOOLS["list_failed_jobs"].destructive is False


@respx.mock
async def test_execute_tool_create_job_passes_args_through(scheduler_client):
    route = respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs").mock(
        return_value=httpx.Response(
            201, json={"jobs": [{"id": "job-1", "name": "extract", "priority": 7}]}
        )
    )

    result = await execute_tool(
        scheduler_client, "create_job", {"name": "extract", "priority": 7, "payload": {"x": 1}}
    )

    sent_body = route.calls.last.request.content
    assert b'"priority":7' in sent_body or b'"priority": 7' in sent_body
    assert result["id"] == "job-1"


async def test_execute_tool_unknown_tool_raises(scheduler_client):
    with pytest.raises(UnknownToolError):
        await execute_tool(scheduler_client, "delete_everything", {})


async def test_execute_tool_malformed_args_raises_invalid_tool_args(scheduler_client):
    with pytest.raises(InvalidToolArgsError):
        await execute_tool(scheduler_client, "cancel_job", {})  # missing required job_id


@respx.mock
async def test_execute_tool_get_job_status_not_found_raises_value_error(scheduler_client):
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/ghost").mock(return_value=httpx.Response(404))

    with pytest.raises(ValueError):
        await execute_tool(scheduler_client, "get_job_status", {"job_id": "ghost"})


@respx.mock
async def test_execute_tool_list_failed_jobs_defaults_to_dlq(scheduler_client):
    route = respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )

    result = await execute_tool(scheduler_client, "list_failed_jobs", {})

    assert route.calls.last.request.url.params["status"] == "DLQ"
    assert result == {"jobs": [], "count": 0}
