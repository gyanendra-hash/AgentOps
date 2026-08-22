import pytest

from app.dag import CycleDetectedError, topological_order


def test_linear_chain():
    order = topological_order({"a": set(), "b": {"a"}, "c": {"b"}})
    assert order.index("a") < order.index("b") < order.index("c")


def test_diamond_dependency():
    order = topological_order({"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}})
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_independent_nodes_all_included():
    order = topological_order({"a": set(), "b": set(), "c": set()})
    assert set(order) == {"a", "b", "c"}


def test_direct_cycle_rejected():
    with pytest.raises(CycleDetectedError) as exc_info:
        topological_order({"a": {"b"}, "b": {"a"}})
    assert exc_info.value.remaining == {"a", "b"}


def test_indirect_cycle_rejected():
    with pytest.raises(CycleDetectedError):
        topological_order({"a": {"c"}, "b": {"a"}, "c": {"b"}})


def test_self_dependency_rejected():
    with pytest.raises(CycleDetectedError):
        topological_order({"a": {"a"}})


def test_five_job_dag_mixed_priorities_resolves():
    # j1 -> j3 -> j5, j2 -> j4 -> j5 (mirrors the Milestone 2 integration test DAG)
    dependencies = {
        "j1": set(),
        "j2": set(),
        "j3": {"j1"},
        "j4": {"j2"},
        "j5": {"j3", "j4"},
    }
    order = topological_order(dependencies)
    assert order.index("j1") < order.index("j3") < order.index("j5")
    assert order.index("j2") < order.index("j4") < order.index("j5")
