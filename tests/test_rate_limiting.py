"""
tests/test_rate_limiting.py

Tests for the rate-limit/retry acceptance criteria.

Run:
    pytest tests/test_rate_limiting.py -v
"""

import json

import requests

from collectors.session import ThrottledRetryingSession


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.content = json.dumps(payload).encode("utf-8")
        self.url = "https://data-api.polymarket.com/trades"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class SequenceSession:
    """Returns prepared responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


def test_forced_429_recovers_without_data_loss(tmp_path, monkeypatch):
    expected_data = [
        {"id": 1, "price": 0.42},
        {"id": 2, "price": 0.43},
    ]

    fake = SequenceSession(
        [
            FakeResponse(429, {"error": "rate limited"}, {"Retry-After": "0"}),
            FakeResponse(200, expected_data),
        ]
    )

    transport = ThrottledRetryingSession(
        retries=3,
        min_interval_s=0,
        token_bucket_capacity=100,
        token_refill_rate=1000,
        failure_log_path=tmp_path / "failures.jsonl",
    )
    transport._session = fake

    # Avoid real sleeping during a unit test.
    monkeypatch.setattr("collectors.session.time.sleep", lambda _: None)

    params = {
        "market": "0xexample",
        "limit": 500,
        "offset": 0,
        "takerOnly": "false",
    }

    response = transport.get(
        "https://data-api.polymarket.com/trades",
        params=params,
        timeout=20,
    )

    assert response.status_code == 200
    assert response.json() == expected_data
    assert len(fake.calls) == 2
    assert fake.calls[0]["params"] == fake.calls[1]["params"]


def test_429_failure_is_structured_and_contains_endpoint_and_params(
    tmp_path,
    monkeypatch,
):
    fake = SequenceSession(
        [
            FakeResponse(429, {"error": "rate limited"}, {"Retry-After": "0"}),
            FakeResponse(200, [{"id": 1}]),
        ]
    )

    log_path = tmp_path / "failures.jsonl"

    transport = ThrottledRetryingSession(
        retries=2,
        min_interval_s=0,
        token_bucket_capacity=100,
        token_refill_rate=1000,
        failure_log_path=log_path,
    )
    transport._session = fake

    monkeypatch.setattr("collectors.session.time.sleep", lambda _: None)

    params = {
        "market": "0xexample",
        "limit": 500,
        "offset": 0,
        "takerOnly": "false",
    }

    transport.get(
        "https://data-api.polymarket.com/trades",
        params=params,
        timeout=20,
    )

    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(records) == 1
    assert records[0]["endpoint"] == "/trades"
    assert records[0]["params"] == params
    assert records[0]["status_code"] == 429
    assert records[0]["attempt"] == 1


def test_5xx_retries_with_exponential_backoff(tmp_path, monkeypatch):
    fake = SequenceSession(
        [
            FakeResponse(500, {"error": "server"}),
            FakeResponse(503, {"error": "server"}),
            FakeResponse(200, [{"id": 9}]),
        ]
    )

    sleeps = []

    transport = ThrottledRetryingSession(
        retries=4,
        min_interval_s=0,
        token_bucket_capacity=100,
        token_refill_rate=1000,
        failure_log_path=tmp_path / "failures.jsonl",
    )
    transport._session = fake

    monkeypatch.setattr(
        "collectors.session.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    response = transport.get(
        "https://data-api.polymarket.com/trades",
        params={"market": "0xexample"},
        timeout=20,
    )

    assert response.status_code == 200

    # Retry sleeps should include 1 second then 2 seconds.
    assert 1.0 in sleeps
    assert 2.0 in sleeps


def test_non_retryable_4xx_is_logged_once(tmp_path):
    fake = SequenceSession(
        [
            FakeResponse(400, {"error": "bad request"}),
        ]
    )

    log_path = tmp_path / "failures.jsonl"

    transport = ThrottledRetryingSession(
        retries=5,
        min_interval_s=0,
        token_bucket_capacity=100,
        token_refill_rate=1000,
        failure_log_path=log_path,
    )
    transport._session = fake

    response = transport.get(
        "https://data-api.polymarket.com/trades",
        params={"market": "0xexample"},
        timeout=20,
    )

    assert response.status_code == 400
    assert len(fake.calls) == 1

    record = json.loads(
        log_path.read_text(encoding="utf-8").splitlines()[0]
    )

    assert record["endpoint"] == "/trades"
    assert record["params"]["market"] == "0xexample"
    assert record["status_code"] == 400
