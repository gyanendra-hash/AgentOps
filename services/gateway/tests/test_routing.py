import pytest

from app.routing import Router, ServiceUnavailableError


def test_round_robin_cycles_through_instances():
    router = Router({"backend": ["http://a", "http://b", "http://c"]})

    picks = [router.next_instance("backend") for _ in range(6)]

    assert picks == ["http://a", "http://b", "http://c", "http://a", "http://b", "http://c"]


def test_single_instance_always_returned():
    router = Router({"backend": ["http://only"]})

    picks = [router.next_instance("backend") for _ in range(3)]

    assert picks == ["http://only", "http://only", "http://only"]


def test_unknown_service_raises():
    router = Router({"backend": ["http://a"]})

    with pytest.raises(ServiceUnavailableError):
        router.next_instance("does-not-exist")


def test_empty_instance_list_raises():
    router = Router({"backend": []})

    with pytest.raises(ServiceUnavailableError):
        router.next_instance("backend")
