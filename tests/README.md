# Tests

Everything here runs offline, in about a second, with no API key and no
network. If you have just cloned the repository:

```bash
pip install -r requirements.txt
pytest -q
```

That is the whole setup. If it passes, the pipeline works on your machine.

## Why the tests never touch the API

Three reasons, and they all bite eventually:

**Speed.** A test that calls Polymarket takes seconds. Nobody runs a suite
that takes five minutes, so it stops being run, so it stops catching things.

**Determinism.** The API is a moving target. Markets resolve and trades
accumulate. A test asserting "this market has 11,588 trades" is true on
Tuesday and false on Wednesday, and you will spend an afternoon on a bug that
does not exist.

**Honesty.** If the tests need the network, CI needs the network, and a broken
build might mean our code is wrong or might mean Polymarket had a bad minute.
You can no longer tell, so the build stops meaning anything.

So instead the tests use **recorded fixtures**: real API responses, saved to
disk, replayed. And `conftest.py` blocks real sockets, so this is enforced
rather than hoped for — a test that tries to reach the internet fails with
`NetworkAccessDenied` and names itself.

## The fixtures

Real responses in `tests/fixtures/`, with `MANIFEST.json` recording where each
one came from. **Read the manifest before trusting a fixture.** Each is marked:

- **observed** — real bytes the API returned on the recorded date. Citable.
- **unverified** — the shape was written from documentation and has never been
  seen from the live API. Fine to test against; do **not** cite it in the
  report as evidence of what the API returns.

| Fixture | Endpoint | Status |
|---|---|---|
| `trades.json` | `/trades` | observed, 2026-08-20 |
| `trades_maduro.json` | `/trades` | observed, 2026-09-06, seed-case market |
| `activity.json` | `/activity` | observed, 2026-08-20 |
| `closed_positions.json` | `/closed-positions` | observed, 2026-08-20 |
| `positions.json` | `/positions` | **unverified** — never called |
| `error_429.json` | any | **unverified** — body is a guess |

Two known gaps, both recorded in the manifest: `/positions` has never been
called, and `activity.json` contains no `DEPOSIT` or `WITHDRAWAL` rows, so it
cannot exercise the wallet-funding features that WS7 needs. Record a wallet
that has funding events before starting those.

### Fixtures are anonymised, and that is not optional

The API returns `name`, `pseudonym`, `bio` and `profileImage` on every trade.
Our ethics protocol says those are never published, and this repository is
public. So every recorded fixture goes through `processing/anonymise.py`:
profile fields removed, `proxyWallet` replaced with a stable hash.

`test_fixtures.py` re-checks this on every run. If you add a fixture by hand
and it carries a real display name, the suite fails. That is deliberate.

## Writing a test

The fake API lives in `tests/conftest.py`. You do not need to build one.

**A response you choose.** `ReplaySession` hands back the bodies you give it,
in order, and the last one repeats — which is what makes a pagination loop
finish:

```python
from tests.conftest import ReplaySession, fixture_bytes

def test_it_stops_at_the_end_of_the_pages(make_api):
    api = make_api(ReplaySession(fixture_bytes("trades.json"), b"[]"))

    api.get_json("/trades", {"market": "0xabc", "takerOnly": False})

    assert api.network_calls == 1
    assert api.session.params_sent["takerOnly"] == "false"
```

**Every endpoint at once.** `fixture_api` answers each endpoint from its own
recorded fixture:

```python
def test_activity_comes_back(fixture_api):
    rows = fixture_api.get_json("/activity", {"user": "0xabc"})
    assert rows[0]["type"] == "TRADE"
```

**Through the collector.** `collect_trades()` and `fetch_activity()` reach the
API through the module-level `_get`, so there is no argument to pass a client
into. `installed_api` swaps the collector's default client instead, and puts
it back afterwards:

```python
@pytest.mark.session("fixtures")
def test_the_collector_works(installed_api):
    trades, metadata = polymarket.collect_trades(query)
    assert installed_api.network_calls == 1
```

Prefer this over monkeypatching `_get`: it exercises the real cache path, so
the test proves the caching actually happens rather than assuming it.

### Asserting on what was sent

`session.calls` holds every `(url, params)` the code produced, and
`session.params_sent` is the most recent call's parameters as a dict. This is
how the two silent-failure guards are tested — that `takerOnly` goes out as
the string `"false"` and not Python's `"False"`, and that an unscoped
`/trades` call is refused *before* anything is sent.

## Recording a new fixture

Do this deliberately, not casually. A test that quietly starts passing against
different data is worse than one that fails.

```bash
python tests/record_fixtures.py --list                          # what exists
python tests/record_fixtures.py --endpoint /positions --user 0x…
```

Needs a normal network connection. It anonymises before writing, refuses to
write anything still carrying profile fields, and updates `MANIFEST.json` with
the date and the exact call. Then: **edit the `notes` field** to say what the
sample covers and what it does not, run `pytest`, and say in the commit
message what changed and why.

## The files

| File | What it covers |
|---|---|
| `conftest.py` | The harness — fake sessions, ready-made clients, the network guard |
| `test_cache.py` | The caching layer on its own (WS5 acceptance criteria) |
| `test_polymarket_collector.py` | The collector's wiring into the cache |
| `test_trade_pagination.py` | Window walking and offset-cap splitting |
| `test_fixtures.py` | Collectors against recorded responses; fixture provenance and anonymisation |
| `test_verify_apis.py` | The WS4 verification suite's own logic |

## If a test fails

**`NetworkAccessDenied`** — something tried to reach the real API. You gave a
client no session, or a code path you did not expect went out to the network.
Give it a fake session.

**`UnscopedRequestError`** — a `/trades` or `/activity` call had no `user`,
`market` or `eventId`. That is the WS4 test 8 guard, and it is correct: an
unscoped call ignores `start` and `end` and returns *current* trades with no
error. Add a scope; do not remove the check.

**`MANIFEST.json and tests/fixtures/ disagree`** — you added or deleted a
fixture without updating the manifest. Every fixture records where it came
from; that is what makes it evidence rather than a magic file.

**A fixture test fails after re-recording** — the API's shape changed. That is
the fixture doing its job. Work out what changed, update
`docs/data_dictionary.md`, and say so in the commit.
