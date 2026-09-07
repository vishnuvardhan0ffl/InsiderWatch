"""
Raw response cache for insiderwatch.

WHAT THIS DOES
--------------
Every question we ask the Polymarket API gets its answer saved to a file before
anything else happens to it. Ask the same question again and we read the file
instead of the API.

WHY WE DO IT
------------
1. Reproducibility. The API is a moving target. If the analysis re-downloads
   its data every time it runs, two people running the same script on two days
   get two different answers. Saving the raw response pins the data to a date.

2. Evidence. The saved file is exactly what the API sent us, byte for byte. We
   can point at it in the report and say "this is what the API returned on
   20 August 2026" - the same way WS4 cites feasibility_check_2026-08-20.json.

3. Nothing gets lost. Collecting a busy market takes thousands of requests. If
   request 4,000 fails, the first 3,999 are already on disk. We resume, we do
   not start again.

4. Offline analysis. Once a dataset is frozen, nothing downstream should touch
   the network at all. Set offline=True and this module will refuse to.

HOW IT WORKS
------------
Each request is identified by its endpoint plus its parameters. We turn those
into one short text string, take a SHA-256 hash of it, and use that hash as the
filename. Same question -> same hash -> same file. Different question -> a
different file. That is the whole idea; everything below is bookkeeping.

For each saved response we write two files:

    data/raw/trades/a3f9....json         the response body, untouched
    data/raw/trades/a3f9....meta.json    where it came from and when

and append one line to data/raw/index.jsonl so a human can see what has been
collected without opening every file.

HOW TO USE IT
-------------
    from collectors.cache import ResponseCache, CachedClient

    api = CachedClient(
        "https://data-api.polymarket.com",
        ResponseCache("data/raw"),
    )

    trades = api.get_json("/trades", {
        "market": "0xd1e4e03a...",   # always scope the call - see require_scope()
        "takerOnly": False,          # always set this explicitly - see below
        "limit": 500,
    })

Run that twice and the API is contacted once.

TWO TRAPS THIS MODULE GUARDS AGAINST
------------------------------------
Both were found in Sprint 1 and both fail silently, which is why they are
handled here rather than left to whoever writes the next collector.

* An unscoped /trades call ignores start and end. You ask for October 2024 and
  you get today, with no error. require_scope() below refuses to make the call.

* takerOnly defaults to true, which quietly drops maker-side fills. This module
  cannot force you to think about it, but it does treat true and false as two
  different questions with two different files, so the two can be compared.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Bump this if the layout of the saved files ever changes. It is part of the
# hash, so old files stop being read rather than being read wrongly.
CACHE_FORMAT_VERSION = 1

# Where responses go if nobody says otherwise.
DEFAULT_CACHE_DIR = "data/raw"

# An environment variable can override the default, e.g. if the cache lives on
# an external drive: export INSIDERWATCH_CACHE_DIR=/media/usb/insiderwatch-cache
CACHE_DIR_ENV_VAR = "INSIDERWATCH_CACHE_DIR"

# Endpoints where a missing scope gives a wrong answer instead of an error.
SCOPE_REQUIRED_ENDPOINTS = ["/trades", "/activity"]

# Any one of these counts as scoping the call.
SCOPING_PARAMS = ["user", "market", "eventId"]


class CacheMiss(Exception):
    """We are running offline and the answer is not on disk."""


class UnscopedRequestError(Exception):
    """A call was made to /trades or /activity without saying whose trades."""


# ---------------------------------------------------------------------------
# Small helpers - each does one thing, each is easy to test on its own
# ---------------------------------------------------------------------------

def resolve_cache_dir(cache_dir=None):
    """Decide where the cache lives.

    Order of preference: what the caller passed in, then the environment
    variable, then the default. First one wins.
    """
    if cache_dir is not None:
        return Path(cache_dir).expanduser()

    from_environment = os.environ.get(CACHE_DIR_ENV_VAR)
    if from_environment:
        return Path(from_environment).expanduser()

    return Path(DEFAULT_CACHE_DIR)


def tidy_endpoint(endpoint):
    """Accept "trades", "/trades" or "/trades/" and always return "/trades".

    Without this, three spellings of the same endpoint would produce three
    different cache files holding identical data.
    """
    return "/" + endpoint.strip("/")


def endpoint_folder(endpoint):
    """The folder name for an endpoint: "/closed-positions" -> "closed-positions".

    Purely so a human browsing data/raw/ can find things.
    """
    return tidy_endpoint(endpoint).strip("/").replace("/", "_")


def tidy_params(params):
    """Put the request parameters into one predictable form.

    Returns a sorted list of (name, value) pairs where every value is a string.
    This exact list is used for two things: building the cache key, and being
    sent to the API. Using it for both means the filename can never describe a
    different request from the one we actually made.

    Three tidying rules, each there for a reason:

    * Parameters set to None are dropped. {"side": None} means "I did not ask
      for a side", which is the same request as not mentioning side at all.

    * True and False become "true" and "false". Python would otherwise send
      "True" and "False", which the Polymarket API does not understand.

    * Lists become comma-separated, because that is how the API takes multiple
      condition IDs.

    Finally the list is sorted, so {"market": x, "limit": 10} and
    {"limit": 10, "market": x} are recognised as the same request.
    """
    if not params:
        return []

    tidied = []
    for name, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            text = ",".join(str(item) for item in value)
        else:
            text = str(value)
        tidied.append((str(name), text))

    return sorted(tidied)


def build_cache_key(endpoint, params):
    """Turn a request into the filename it will be stored under.

    We hash rather than using the parameters directly because a wallet address
    plus a time window plus an offset makes for a very long and awkward
    filename. The hash is short, safe on every filesystem, and the readable
    version of the request is kept in the .meta.json file next to it.
    """
    description = json.dumps(
        [CACHE_FORMAT_VERSION, tidy_endpoint(endpoint), tidy_params(params)],
        separators=(",", ":"),
    )
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


def require_scope(endpoint, params):
    """Refuse a /trades or /activity call that does not say whose trades.

    WS4 test 8: on an unscoped /trades call the API ignores start and end and
    returns current trades instead. There is no error and no empty result, so a
    collector walking history by time window would produce a dataset full of
    today's data while looking perfectly healthy.

    Raising here is deliberate. A loud failure now is much cheaper than a quiet
    wrong dataset discovered in November.
    """
    if tidy_endpoint(endpoint) not in SCOPE_REQUIRED_ENDPOINTS:
        return

    supplied = dict(tidy_params(params))
    if not any(supplied.get(name) for name in SCOPING_PARAMS):
        raise UnscopedRequestError(
            "{} needs one of {} or the API will ignore start/end and return "
            "current data instead of history (WS4 test 8).".format(
                tidy_endpoint(endpoint), ", ".join(SCOPING_PARAMS)
            )
        )


def utc_now():
    """Current time as text, e.g. 2026-09-06T13:15:02+00:00.

    Always UTC. Trade timestamps are UTC, so mixing in local Adelaide time
    would create off-by-hours bugs that are painful to find later.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# The cache itself - reading and writing files
# ---------------------------------------------------------------------------

@dataclass
class CachedResponse:
    """One saved response, plus everything needed to cite it in the report."""

    key: str            # the hash, i.e. the filename
    endpoint: str       # e.g. "/trades"
    params: list        # [("market", "0x..."), ("takerOnly", "false")]
    url: str            # the full URL that was requested
    status_code: int    # 200, always, since we only save successes
    retrieved_at: str   # UTC timestamp of when we asked
    body: bytes         # exactly what the API sent
    from_cache: bool    # True if read from disk, False if just downloaded

    def json(self):
        """The response body parsed into Python lists and dicts."""
        return json.loads(self.body.decode("utf-8"))


class ResponseCache:
    """Saves and loads raw API responses under a directory."""

    def __init__(self, cache_dir=None):
        self.cache_dir = resolve_cache_dir(cache_dir)

    def paths_for(self, endpoint, params):
        """The two file paths used for this request: the body and its metadata."""
        key = build_cache_key(endpoint, params)
        folder = self.cache_dir / endpoint_folder(endpoint)
        return folder / (key + ".json"), folder / (key + ".meta.json")

    def has(self, endpoint, params):
        """Is this request already saved?"""
        body_path, meta_path = self.paths_for(endpoint, params)
        return body_path.exists() and meta_path.exists()

    def read(self, endpoint, params):
        """Return the saved response, or None if we have not collected it yet."""
        body_path, meta_path = self.paths_for(endpoint, params)
        if not (body_path.exists() and meta_path.exists()):
            return None

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return CachedResponse(
            key=meta["key"],
            endpoint=meta["endpoint"],
            params=[tuple(pair) for pair in meta["params"]],
            url=meta["url"],
            status_code=meta["status_code"],
            retrieved_at=meta["retrieved_at"],
            body=body_path.read_bytes(),
            from_cache=True,
        )

    def write(self, endpoint, params, url, status_code, body, retrieved_at=None):
        """Save a response and return it."""
        response = CachedResponse(
            key=build_cache_key(endpoint, params),
            endpoint=tidy_endpoint(endpoint),
            params=tidy_params(params),
            url=url,
            status_code=status_code,
            retrieved_at=retrieved_at or utc_now(),
            body=body,
            from_cache=False,
        )

        body_path, meta_path = self.paths_for(endpoint, params)
        body_path.parent.mkdir(parents=True, exist_ok=True)

        # The body is written first and read() requires both files to exist.
        # So if the program is interrupted between the two writes, the next run
        # sees a cache miss and re-downloads - which is right. The alternative
        # ordering would leave a metadata file describing a body that is not
        # there, or worse, a half-written body that looks complete.
        body_path.write_bytes(response.body)
        meta = describe(response, body_path)
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")

        self._append_to_index(meta)
        return response

    def _append_to_index(self, meta):
        """Add one line to index.jsonl - a running log of everything collected.

        One JSON object per line, so it can be read with pandas.read_json(...,
        lines=True) when we build the dataset manifest at the freeze.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(meta, separators=(",", ":"), sort_keys=True)
        with (self.cache_dir / "index.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def describe(response, body_path):
    """Build the metadata record that sits beside a saved response.

    The SHA-256 of the body is included so anyone can verify later that the
    file has not been edited since it was collected. That is what makes it
    usable as evidence rather than just as a convenient copy.
    """
    return {
        "cache_format_version": CACHE_FORMAT_VERSION,
        "key": response.key,
        "endpoint": response.endpoint,
        "params": [list(pair) for pair in response.params],
        "url": response.url,
        "status_code": response.status_code,
        "retrieved_at": response.retrieved_at,
        "body_sha256": hashlib.sha256(response.body).hexdigest(),
        "body_bytes": len(response.body),
        "body_path": str(body_path),
    }


# ---------------------------------------------------------------------------
# The client - what collectors actually call
# ---------------------------------------------------------------------------

class CachedClient:
    """An API client that checks the cache before it checks the network.

    Arguments:
        base_url  the API root, e.g. "https://data-api.polymarket.com"
        cache     a ResponseCache; one is created with default settings if
                  you do not pass one
        session   normally left alone. Tests pass a fake session in so they can
                  count how many network calls really happened, which is how we
                  prove the cache works instead of assuming it does
        offline   if True, never use the network. A request that is not already
                  cached raises CacheMiss. Use this when running analysis over
                  a frozen dataset, and for the M2 demonstration
        timeout   seconds to wait for the API before giving up
    """

    def __init__(self, base_url, cache=None, session=None, offline=False, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.cache = cache if cache is not None else ResponseCache()
        self.session = session
        self.offline = offline
        self.timeout = timeout

        # Handy for logging and for tests: how many times we actually went out
        # to the API during this run.
        self.network_calls = 0

    def get(self, endpoint, params=None, refresh=False):
        """Fetch an endpoint, from disk if we can, from the API if we must.

        Set refresh=True to ignore the cached copy and download again. That
        overwrites the old copy, so do not use it on a frozen dataset.
        """
        # 1. Refuse requests that would silently return the wrong data.
        require_scope(endpoint, params)

        # 2. Do we already have the answer?
        if not refresh:
            saved = self.cache.read(endpoint, params)
            if saved is not None:
                return saved

        # 3. We do not. Are we allowed to ask?
        if self.offline:
            raise CacheMiss(
                "Nothing cached for {} {} and this client is offline.".format(
                    tidy_endpoint(endpoint), tidy_params(params)
                )
            )

        # 4. Ask the API.
        url = self.base_url + tidy_endpoint(endpoint)
        response = self._session().get(
            url, params=tidy_params(params), timeout=self.timeout
        )
        self.network_calls += 1

        # Only successful responses are saved. If we cached a rate-limit page or
        # a 500, every future run would read that file back and believe it was
        # data. Raising here hands the problem to the retry layer, which is
        # where it belongs.
        response.raise_for_status()

        return self.cache.write(
            endpoint,
            params,
            url=getattr(response, "url", url),
            status_code=response.status_code,
            body=response.content,
        )

    def get_json(self, endpoint, params=None, refresh=False):
        """Same as get(), but returns the parsed JSON rather than the wrapper."""
        return self.get(endpoint, params, refresh=refresh).json()

    def _session(self):
        """Create the requests session the first time it is actually needed.

        Importing requests lazily means an offline replay of a frozen dataset
        works even in an environment where requests is not installed.
        """
        if self.session is None:
            import requests
            self.session = requests.Session()
        return self.session
