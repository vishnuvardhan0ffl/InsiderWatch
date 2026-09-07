# The caching layer, explained

**Module:** `collectors/cache.py` · **Tests:** `tests/test_cache.py` · **Live check:** `verify_cache.py`

This note is for whoever picks the project up next. It explains what the cache
is for and how to work with it. The code itself is commented; this is the
five-minute version.

## The idea in one paragraph

Every request we make to the Polymarket API is saved to disk before anything
parses it. The endpoint and its parameters are turned into a short text
description, that description is hashed, and the hash becomes the filename. Ask
the same question again and the file is already there, so no request is made.
Ask a different question and you get a different filename. That is the whole
mechanism.

## Why we bother

**The API is a moving target.** Markets resolve, trades accumulate. An analysis
that re-downloads its data on every run gives different answers on different
days, which is not research, it is weather. Saving the response pins the data to
a date.

**The saved file is evidence.** It is byte-for-byte what the API sent, and the
metadata beside it records the SHA-256 of the body. When the report says "the
API returned X on this date", the file backs that up and can be checked.

**Collection is long and fragile.** A busy market takes thousands of requests.
When one fails, everything already collected is on disk. You resume; you do not
start over.

**Frozen means frozen.** Once the dataset is frozen at M3, nothing downstream
should touch the network at all. `offline=True` enforces that rather than
trusting everyone to remember.

## What lands on disk

```
data/raw/
    index.jsonl                     one line per saved response
    trades/
        e414071.....json            the response body, untouched
        e414071.....meta.json       url, parameters, timestamp, hash
    activity/
        f81a103.....json
        f81a103.....meta.json
```

A metadata file looks like this:

```json
{
  "cache_format_version": 1,
  "key": "e414071...",
  "endpoint": "/trades",
  "params": [["limit", "500"], ["market", "0xd1e4e03a"], ["takerOnly", "false"]],
  "url": "https://data-api.polymarket.com/trades",
  "status_code": 200,
  "retrieved_at": "2026-09-06T13:18:06+00:00",
  "body_sha256": "f4ef864f...",
  "body_bytes": 42
}
```

`index.jsonl` holds the same records, one JSON object per line, so the whole
collection can be summarised with
`pandas.read_json("data/raw/index.jsonl", lines=True)`. That is where the
dataset manifest at M3 comes from.

## Using it

```python
from collectors.cache import ResponseCache, CachedClient

api = CachedClient(
    "https://data-api.polymarket.com",
    ResponseCache("data/raw"),
)

trades = api.get_json("/trades", {
    "market": "0xd1e4e03a...",
    "takerOnly": False,
    "limit": 500,
})
```

Run it twice, the API is contacted once.

To replay a frozen dataset with no network access at all:

```python
api = CachedClient("https://data-api.polymarket.com",
                   ResponseCache("data/raw"),
                   offline=True)
```

Anything not already collected raises `CacheMiss` instead of quietly
downloading fresh data.

To put the cache somewhere else, either pass the path to `ResponseCache(...)`
or set `INSIDERWATCH_CACHE_DIR`. The argument wins over the environment
variable, which wins over the default of `data/raw`.

## The collector goes through it

The collector no longer keeps a cache of its own, and that matters more than it
sounds. `collectors/polymarket.py` used to hash its parameters and write the
*parsed* body back out with `json.dumps` — a re-serialised copy, with no record
of when it was retrieved. It could not be cited as evidence, which is the whole
reason for keeping raw responses.

It now calls `CachedClient`. Transport — pacing and backoff on 429/5xx — lives
in `collectors/session.py`, sitting *outside* the cache, so the cache never
sleeps and never retries. Any collector added later inherits both.

```
fetch_trades()  ─┐
                 ├─→ CachedClient ─→ ResponseCache ─→ data/raw/
fetch_activity()─┘        │
                          └─→ ThrottledRetryingSession ─→ the API
```

Every `fetch_*` function takes an optional `client=`, so a test or the CLI can
substitute a different cache directory, an offline client, or a fake session:

```python
list(fetch_trades(query, client=CachedClient(BASE_URL,
                                             ResponseCache("data/raw"),
                                             offline=True)))
```

## Two rules the module enforces for you

**Always scope a `/trades` or `/activity` call.** An unscoped call ignores
`start` and `end` and returns current trades instead of history, with no error
and no empty result (WS4 test 8). A collector walking history by time window
would produce a dataset full of today's data while looking perfectly healthy.
The module raises `UnscopedRequestError` rather than letting that happen. If you
hit it, add `user=`, `market=` or `eventId=`; do not remove the check.

**`takerOnly` is part of the cache key.** It defaults to `true` on the API,
which silently drops maker-side fills. True and false are stored as two
separate files, so the two can be collected and compared. Set it explicitly on
every call; the value you used is recorded in the metadata.

## Things that are deliberately not in here

- **Retries and rate limiting.** `collectors/session.py`, outside this module
  and passed in as the `session`. The Sprint 2 rate-limiting story replaces that
  file without touching the cache.
- **Caching failures.** Only HTTP 200 responses are saved. A cached rate-limit
  page would be replayed forever as though it were data.
- **Cache expiry.** There is none, on purpose. Entries do not go stale, they go
  *historical*. Use `refresh=True` if you deliberately want a fresh copy, and do
  not use it against a frozen dataset.

## Proving it works

Two levels, and they answer different questions.

`pytest -q` runs offline and proves the *behaviour*. The tests pass in a fake
session that counts calls, so "zero network calls on a re-run" is asserted, not
assumed. `tests/test_cache.py` covers the cache itself; the collector tests
prove the wiring, i.e. that a repeated `fetch_trades` really does make no
requests.

`python verify_cache.py` runs against the **live** API and proves the same three
acceptance criteria there, writing dated evidence to
`data/external/cache_check_<date>.json` the way `verify_apis.py` does. It needs
a normal, unblocked network connection, and it works in a throwaway temp
directory, so it can never disturb `data/raw/`. Commit the evidence file.

## If you change this module

Run `pytest -q` first.

If you change how the cache key is built, or the layout of the saved files,
increment `CACHE_FORMAT_VERSION`. The version is part of the hash, so old files
stop being found rather than being read wrongly. Old entries stay on disk and
can be deleted once you are sure nothing cites them.
