from app.heap import PriorityQueue


def test_empty_queue():
    queue = PriorityQueue()
    assert len(queue) == 0
    assert bool(queue) is False
    assert queue.pop() is None
    assert queue.peek() is None


def test_higher_priority_pops_first():
    queue = PriorityQueue()
    queue.push("low", priority=1)
    queue.push("high", priority=10)
    queue.push("mid", priority=5)

    assert queue.pop() == "high"
    assert queue.pop() == "mid"
    assert queue.pop() == "low"


def test_equal_priority_is_fifo_no_starvation():
    queue = PriorityQueue()
    queue.push("first", priority=3)
    queue.push("second", priority=3)
    queue.push("third", priority=3)

    assert [queue.pop(), queue.pop(), queue.pop()] == ["first", "second", "third"]


def test_older_equal_priority_job_not_starved_by_newer_arrivals():
    queue = PriorityQueue()
    queue.push("old", priority=5)
    queue.push("newer_a", priority=5)
    queue.push("newer_b", priority=5)

    # even though more same-priority jobs keep arriving, the oldest one is
    # still next out -- FIFO within a tier prevents indefinite starvation
    assert queue.peek() == "old"


def test_len_and_bool_reflect_size():
    queue = PriorityQueue()
    assert not queue
    queue.push("a", priority=0)
    assert queue
    assert len(queue) == 1
    queue.pop()
    assert not queue
