"""
collectors/session.py

Transport for the collectors: polite pacing and retries. Nothing else.

WHY THIS IS ITS OWN MODULE
--------------------------
CachedClient (collectors/cache.py) needs an object with one method,
.get(url, params, timeout) -> response. That is the whole contract. Keeping
transport behind it means three things stay true:

  * The cache is a storage layer. It never sleeps, never retries, and can be
    tested with a fake session that counts calls - which is how "zero network
    calls on a re-run" is proven rather than assumed.
  * The Sprint 2 story "Add rate limiting, retry and error handling" replaces
    this file without touching the cache or the collector.
  * Any collector added later gets the same pacing without reimplementing it.

WHAT IT DOES NOT DO
-------------------
It does not decide what to do with a failed request beyond retrying it. The
final attempt is handed back as-is, so CachedClient raises on it and nothing
is written to disk. A cached 429 page would be replayed forever as though it
were data.
"""
import time

import requests

# Well under the documented ceilings: Polymarket allows 200 req/10s on /trades
# and 150 req/10s on positions (WS4 section 3.3). Caching, not throttling, is
# what keeps our request count low; this is good manners rather than a
# constraint we are anywhere near.
DEFAULT_MIN_INTERVAL_S = 0.3


class ThrottledRetryingSession:
    """A stand-in for requests.Session that paces itself and backs off.

    Arguments:
        retries         attempts per request, including the first
        min_interval_s  minimum gap between requests from this session
    """

    def __init__(self, retries: int = 5,
                 min_interval_s: float = DEFAULT_MIN_INTERVAL_S):
        self._session = requests.Session()
        self.retries = retries
        self.min_interval_s = min_interval_s
        self._last_call = 0.0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_call = time.monotonic()

    def get(self, url, params=None, timeout=None):
        backoff = 1.0
        for attempt in range(self.retries):
            self._throttle()
            last_attempt = attempt == self.retries - 1
            try:
                response = self._session.get(url, params=params, timeout=timeout)
            except requests.RequestException:
                if last_attempt:
                    raise
                time.sleep(backoff)
                backoff *= 2
                continue
            if response.status_code == 429 or response.status_code >= 500:
                # Hand the last one back rather than raising here: the caller
                # raises and, crucially, does not save it.
                if last_attempt:
                    return response
                time.sleep(backoff)
                backoff *= 2
                continue
            return response
        raise RuntimeError("Exhausted retries for {}".format(url))
