"""
The transport layer: pacing and retries (collectors/session.py).

This is the module that decides what happens when Polymarket says no. It had
almost no tests, which is a poor place for a gap - a retry bug does not show
up as an error, it shows up as a collection that quietly stopped early.

time.sleep is patched out in every test here, so the backoff is asserted on
rather than waited for. A suite that actually slept through exponential
backoff would take about half a minute for this file alone.
"""

import pytest
import requests

from collectors.session import ThrottledRetryingSession


@pytest.fixture
def no_sleeping(monkeypatch):
    """Record what the session would have slept, without sleeping."""

    slept = []
    monkeypatch.setattr("collectors.session.time.sleep", slept.append)
    monkeypatch.setattr("collectors.session.time.monotonic", lambda: 0.0)
    return slept


class Reply:
    def __init__(self, status_code):
        self.status_code = status_code
        self.content = b"[]"
        self.url = "https://fake/trades"


class Upstream:
    """Stands in for the requests.Session inside ThrottledRetryingSession."""

    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.attempts = 0

    def get(self, url, params=None, timeout=None):
        status = self.statuses[min(self.attempts, len(self.statuses) - 1)]
        self.attempts += 1

        if isinstance(status, Exception):
            raise status

        return Reply(status)


def make_session(upstream, retries=5):
    session = ThrottledRetryingSession(retries=retries, min_interval_s=0)
    session._session = upstream
    return session


def test_a_rate_limited_request_is_retried_until_it_succeeds(no_sleeping):
    upstream = Upstream(429, 429, 200)
    session = make_session(upstream)

    response = session.get("https://fake/trades")

    assert response.status_code == 200
    assert upstream.attempts == 3


def test_a_server_error_is_retried_too(no_sleeping):
    upstream = Upstream(503, 200)

    assert make_session(upstream).get("https://fake/trades").status_code == 200
    assert upstream.attempts == 2


def test_the_wait_doubles_between_attempts(no_sleeping):
    """Exponential backoff: a retry storm makes rate limiting worse."""

    make_session(Upstream(429, 429, 429, 200)).get("https://fake/trades")

    assert no_sleeping == [1.0, 2.0, 4.0]


def test_a_success_is_returned_immediately_without_retrying(no_sleeping):
    upstream = Upstream(200)

    make_session(upstream).get("https://fake/trades")

    assert upstream.attempts == 1
    assert no_sleeping == []


def test_the_last_failed_attempt_is_handed_back_not_raised(no_sleeping):
    """Deliberate: CachedClient raises on it, and so does NOT cache it.

    If this raised here instead, the caller could not tell a rate limit from a
    bug - and the important part is that nothing gets written to disk. A cached
    429 would be replayed as data for the rest of the project.
    """

    upstream = Upstream(429)
    response = make_session(upstream, retries=3).get("https://fake/trades")

    assert response.status_code == 429
    assert upstream.attempts == 3


def test_a_dropped_connection_is_retried_then_finally_raised(no_sleeping):
    upstream = Upstream(requests.RequestException("connection reset"))

    with pytest.raises(requests.RequestException):
        make_session(upstream, retries=3).get("https://fake/trades")

    assert upstream.attempts == 3


def test_a_connection_that_recovers_is_not_raised(no_sleeping):
    upstream = Upstream(requests.RequestException("reset"), 200)

    assert make_session(upstream).get("https://fake/trades").status_code == 200


def test_requests_are_paced_apart(monkeypatch):
    """The throttle asks for the gap it is short of, and no more.

    The first request never waits: monotonic() counts from an arbitrary point,
    so treating "no request yet" as "a request at time zero" would pause the
    first call on a freshly booted machine.
    """

    slept = []
    clock = {"now": 0.0}
    monkeypatch.setattr("collectors.session.time.sleep", slept.append)
    monkeypatch.setattr("collectors.session.time.monotonic", lambda: clock["now"])

    session = ThrottledRetryingSession(min_interval_s=0.3)
    session._session = Upstream(200, 200)

    session.get("https://fake/trades")     # first call: clock is at 0
    clock["now"] = 0.1                     # 0.1s later
    session.get("https://fake/trades")

    assert slept == [pytest.approx(0.2)]   # only the second call waited, 0.2s
