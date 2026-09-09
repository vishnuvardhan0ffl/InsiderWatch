"""
Shared test harness. pytest loads this automatically - never import it.

Everything here exists so a test can pretend to talk to the Polymarket API
without a network connection. Read tests/README.md first; this file is the
reference, that one is the explanation.

What you get:

    load_fixture("trades.json")     a recorded API response, as Python objects
    fixture_bytes("trades.json")    the same, as bytes (what a response holds)

    ReplaySession(...)              a fake session that hands back what you give it
    FixtureSession()                a fake session that answers by endpoint

    make_api(session)               a client with the fake session you choose
    fixture_api                     a client answering from the fixtures
    installed_api                   the same, installed as the collector default

And one thing you do not get: a working network. Any test that opens a real
socket fails immediately - see block_network at the bottom.
"""

import json
import socket
from pathlib import Path

import pytest

from collectors.cache import CachedClient, ResponseCache

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Reading fixtures
# ---------------------------------------------------------------------------

def load_fixture(name):
    """A recorded response as Python lists and dicts."""

    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def fixture_bytes(name):
    """The same fixture as raw bytes - what a response body actually holds.

    Use this for fake response bodies. Responses arrive as bytes and the cache
    stores bytes, so handing it a dict tests something the real code never does.
    """

    return (FIXTURE_DIR / name).read_bytes()


# ---------------------------------------------------------------------------
# Fake sessions
# ---------------------------------------------------------------------------

class FakeResponse:
    """The handful of things CachedClient uses from a real response."""

    def __init__(self, body, status_code=200, url="https://fake-api/endpoint"):
        self.content = body
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP {}".format(self.status_code))


class ReplaySession:
    """Hands back the responses you gave it, in order, and remembers the calls.

    The last response repeats once the list runs out, which is what makes a
    pagination loop terminate:

        ReplaySession(fixture_bytes("trades.json"), b"[]")

    gives one page of trades and then empty pages forever. Pass a
    (body, status_code) pair for an error:

        ReplaySession((b"rate limited", 429))

    Every call is recorded in .calls as (url, params), so a test can assert
    what was actually sent - which is how the takerOnly and scope checks work.
    """

    def __init__(self, *responses):
        self.responses = list(responses) or [b"[]"]
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, list(params or [])))

        index = min(len(self.calls) - 1, len(self.responses) - 1)
        response = self.responses[index]

        body, status = response if isinstance(response, tuple) else (response, 200)
        return FakeResponse(body, status, url=url)

    @property
    def params_sent(self):
        """The parameters of the most recent call, as a dict.

            assert session.params_sent["takerOnly"] == "false"
        """

        return dict(self.calls[-1][1]) if self.calls else {}


class FixtureSession:
    """Answers each endpoint from its own recorded fixture.

    For tests about a collector doing its job end to end, rather than about one
    specific response. An endpoint with no fixture returns an empty list, so
    pagination loops stop.
    """

    BY_ENDPOINT = {
        "/trades": "trades.json",
        "/activity": "activity.json",
        "/positions": "positions.json",
        "/closed-positions": "closed_positions.json",
    }

    def __init__(self, once=True):
        # once=True serves each endpoint's fixture on the first call and empty
        # pages after it, so a collector that paginates finishes. Set it False
        # to serve the same page every time.
        self.once = once
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, list(params or [])))

        endpoint = "/" + url.split("/")[-1]
        name = self.BY_ENDPOINT.get(endpoint)

        already_served = sum(1 for call, _ in self.calls[:-1] if call == url)
        if name is None or (self.once and already_served):
            return FakeResponse(b"[]", url=url)

        return FakeResponse(fixture_bytes(name), url=url)


# ---------------------------------------------------------------------------
# Ready-made clients
# ---------------------------------------------------------------------------

BASE_URL = "https://data-api.polymarket.com"


@pytest.fixture
def cache_dir(tmp_path):
    """A throwaway cache directory, so no test writes to the real data/raw/."""

    return tmp_path / "raw"


@pytest.fixture
def make_api(cache_dir):
    """Build a client with the fake session of your choosing.

        api = make_api(ReplaySession(fixture_bytes("trades.json")))
    """

    def build(session=None, **kwargs):
        return CachedClient(
            BASE_URL,
            cache=ResponseCache(cache_dir),
            session=session,
            **kwargs
        )

    return build


@pytest.fixture
def fixture_api(make_api):
    """A client answering each endpoint from its own recorded fixture."""

    return make_api(FixtureSession())


@pytest.fixture
def installed_api(make_api, request):
    """A client installed as the collector module's default, then removed.

    collect_trades() and fetch_activity() reach the API through the module
    level _get, so there is no argument to pass a client into. Swapping the
    module's client means the test still goes through the real cache, unlike
    monkeypatching _get. Pick the session with @pytest.mark.session("fixtures");
    the default serves the recorded /trades.
    """

    from collectors import polymarket

    marker = request.node.get_closest_marker("session")
    wanted = marker.args[0] if marker else "trades"

    session = (
        FixtureSession() if wanted == "fixtures"
        else ReplaySession(fixture_bytes("trades.json"), b"[]")
    )

    client = make_api(session)
    polymarket.set_default_client(client)
    yield client
    polymarket.set_default_client(None)


# ---------------------------------------------------------------------------
# The no-network guard
# ---------------------------------------------------------------------------

class NetworkAccessDenied(RuntimeError):
    """A test tried to reach the real internet."""


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Stop any test from reaching the network. Applied to every test.

    "The suite runs offline" is easy to claim and easy to break: one forgotten
    fake session and a test quietly starts calling Polymarket - slow, flaky,
    dependent on the API being up, and different every run. This turns that
    into an immediate, obvious failure.

    Loopback is still allowed so a local server in some future test works.
    """

    real_connect = socket.socket.connect

    def guard(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)

        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *args, **kwargs)

        raise NetworkAccessDenied(
            "This test tried to connect to {}. Tests must run offline - "
            "give the client a fake session (see tests/README.md).".format(host)
        )

    monkeypatch.setattr(socket.socket, "connect", guard)
