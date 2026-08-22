from app.retry import next_backoff_seconds, should_retry


def test_backoff_doubles_each_attempt():
    assert next_backoff_seconds(1, base_seconds=1.0) == 1.0
    assert next_backoff_seconds(2, base_seconds=1.0) == 2.0
    assert next_backoff_seconds(3, base_seconds=1.0) == 4.0
    assert next_backoff_seconds(4, base_seconds=1.0) == 8.0


def test_backoff_is_capped():
    assert next_backoff_seconds(10, base_seconds=1.0, cap_seconds=60.0) == 60.0


def test_should_retry_below_max():
    assert should_retry(attempt=1, max_retries=3) is True
    assert should_retry(attempt=2, max_retries=3) is True


def test_should_not_retry_at_or_above_max():
    assert should_retry(attempt=3, max_retries=3) is False
    assert should_retry(attempt=4, max_retries=3) is False
