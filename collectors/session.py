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
"""
collectors/session.py

Transport layer for the collectors.

Provides:
- Token-bucket client-side rate limiting
- Exponential backoff for HTTP 429 and 5xx errors
- Retry handling for network errors
- Structured JSON logging for failed API calls
"""

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


# =========================================================
# SETTINGS
# =========================================================

DEFAULT_RETRIES = 5

# Polymarket /trades ceiling:
# 200 requests per 10 seconds = 20 requests per second.
#
# We deliberately use 5 requests per second,
# which is well below that ceiling.
DEFAULT_REFILL_RATE = 5.0

# Allow a small initial burst.
DEFAULT_BUCKET_CAPACITY = 10

# Failed API calls are recorded here.
DEFAULT_FAILURE_LOG = Path("logs/api_failures.jsonl")

# Maximum exponential-backoff delay.
MAX_BACKOFF_SECONDS = 60.0


# =========================================================
# TOKEN BUCKET RATE LIMITER
# =========================================================

class TokenBucket:
    """
    Thread-safe token-bucket rate limiter.

    Every request needs one token.

    Tokens are continuously refilled according to
    refill_rate.
    """

    def __init__(
        self,
        capacity=DEFAULT_BUCKET_CAPACITY,
        refill_rate=DEFAULT_REFILL_RATE,
    ):
        if capacity <= 0:
            raise ValueError(
                "capacity must be greater than 0"
            )

        if refill_rate <= 0:
            raise ValueError(
                "refill_rate must be greater than 0"
            )

        self.capacity = float(capacity)

        self.refill_rate = float(refill_rate)

        # Start with a full bucket.
        self.tokens = float(capacity)

        self.last_refill = time.monotonic()

        # Makes the token bucket safe for multiple threads.
        self.lock = threading.Lock()

    def acquire(self):
        """
        Wait until one request token is available.
        """

        while True:

            with self.lock:

                now = time.monotonic()

                elapsed = (
                    now
                    - self.last_refill
                )

                # Refill tokens according to elapsed time.
                self.tokens = min(
                    self.capacity,
                    self.tokens
                    + elapsed
                    * self.refill_rate,
                )

                self.last_refill = now

                # If a token is available, use it.
                if self.tokens >= 1.0:

                    self.tokens -= 1.0

                    return

                # Otherwise calculate how long we need
                # to wait for the next token.
                wait_seconds = (
                    1.0
                    - self.tokens
                ) / self.refill_rate

            time.sleep(
                wait_seconds
            )


# =========================================================
# THROTTLED RETRYING SESSION
# =========================================================

class ThrottledRetryingSession:
    """
    requests.Session wrapper providing:

    - Token-bucket rate limiting
    - Exponential backoff
    - Retry handling
    - Structured failure logging

    The public get() method keeps the same interface
    expected by the existing collector and cache code.
    """

    def __init__(
        self,
        retries=DEFAULT_RETRIES,
        min_interval_s=0.0,
        token_bucket_capacity=DEFAULT_BUCKET_CAPACITY,
        token_refill_rate=DEFAULT_REFILL_RATE,
        failure_log_path=DEFAULT_FAILURE_LOG,
    ):

        if retries <= 0:
            raise ValueError(
                "retries must be greater than 0"
            )

        self._session = requests.Session()

        self.retries = retries

        # Kept for compatibility with the existing
        # collector and existing tests.
        self.min_interval_s = max(
            0.0,
            float(min_interval_s),
        )

        self._last_call = None

        # Create token bucket.
        self.bucket = TokenBucket(
            capacity=token_bucket_capacity,
            refill_rate=token_refill_rate,
        )

        self.failure_log_path = Path(
            failure_log_path
        )

        self._log_lock = threading.Lock()


    # =====================================================
    # RATE LIMITING
    # =====================================================

    def _throttle(self):
        """
        Apply token-bucket rate limiting.

        The optional min_interval_s is also retained
        for compatibility with the original transport.
        """

        # Wait until a token is available.
        self.bucket.acquire()

        # Optional minimum interval between requests.
        if (
            self._last_call is not None
            and self.min_interval_s > 0
        ):

            elapsed = (
                time.monotonic()
                - self._last_call
            )

            if elapsed < self.min_interval_s:

                time.sleep(
                    self.min_interval_s
                    - elapsed
                )

        self._last_call = time.monotonic()


    # =====================================================
    # STRUCTURED FAILURE LOGGING
    # =====================================================

    def _log_failure(
        self,
        url,
        params,
        attempt,
        status_code=None,
        error=None,
        retry_in_seconds=None,
    ):
        """
        Write one JSON object for every failed API call.

        Example:

        {
            "endpoint": "/trades",
            "params": {
                "market": "0x..."
            },
            "attempt": 1,
            "status_code": 429,
            "error": "HTTP 429",
            "retry_in_seconds": 1.0
        }
        """

        endpoint = (
            urlparse(url).path
            or "/"
        )

        record = {
            "timestamp_unix": time.time(),

            "endpoint": endpoint,

            "url": url,

            "params": dict(
                params or {}
            ),

            "attempt": attempt,

            "status_code": status_code,

            "error": error,

            "retry_in_seconds":
                retry_in_seconds,
        }

        # Create logs directory automatically.
        self.failure_log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Write one JSON object per line.
        with self._log_lock:

            with self.failure_log_path.open(
                "a",
                encoding="utf-8",
            ) as file:

                file.write(
                    json.dumps(
                        record,
                        sort_keys=True,
                        default=str,
                    )
                    + "\n"
                )


    # =====================================================
    # RETRY-AFTER HANDLING
    # =====================================================

    @staticmethod
    def _retry_after_seconds(
        response,
        fallback,
    ):
        """
        Use Retry-After when the server provides it.

        If the response has no headers attribute,
        use the normal exponential-backoff value.

        This also keeps the code compatible with
        the repository's simple fake Reply objects
        used in unit tests.
        """

        headers = getattr(
            response,
            "headers",
            {},
        ) or {}

        value = headers.get(
            "Retry-After"
        )

        if value is None:
            return fallback

        try:

            return max(
                float(value),
                fallback,
            )

        except (
            TypeError,
            ValueError,
        ):

            return fallback


    # =====================================================
    # GET REQUEST
    # =====================================================

    def get(
        self,
        url,
        params=None,
        timeout=None,
    ):
        """
        Perform an HTTP GET request.

        Retries:

        - HTTP 429
        - HTTP 5xx
        - requests.RequestException

        Exponential backoff:

        1 second
        2 seconds
        4 seconds
        8 seconds
        ...

        The final failed HTTP response is returned to
        the caller. This preserves the repository's
        existing behaviour: CachedClient can then call
        raise_for_status() and avoid caching bad data.
        """

        backoff = 1.0

        for attempt_index in range(
            self.retries
        ):

            attempt = (
                attempt_index
                + 1
            )

            last_attempt = (
                attempt
                == self.retries
            )

            # Apply client-side rate limiting.
            self._throttle()

            try:

                response = (
                    self._session.get(
                        url,
                        params=params,
                        timeout=timeout,
                    )
                )

            # =================================================
            # NETWORK ERROR
            # =================================================

            except requests.RequestException as error:

                retry_in = (
                    None
                    if last_attempt
                    else backoff
                )

                self._log_failure(
                    url=url,
                    params=params,
                    attempt=attempt,
                    status_code=None,
                    error=(
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                    retry_in_seconds=retry_in,
                )

                if last_attempt:
                    raise

                time.sleep(
                    backoff
                )

                backoff = min(
                    backoff * 2,
                    MAX_BACKOFF_SECONDS,
                )

                continue


            status = response.status_code


            # =================================================
            # HTTP 429 OR HTTP 5xx
            # =================================================

            if (
                status == 429
                or 500 <= status < 600
            ):

                wait_seconds = (
                    self._retry_after_seconds(
                        response,
                        backoff,
                    )
                )

                retry_in = (
                    None
                    if last_attempt
                    else wait_seconds
                )

                self._log_failure(
                    url=url,
                    params=params,
                    attempt=attempt,
                    status_code=status,
                    error=f"HTTP {status}",
                    retry_in_seconds=retry_in,
                )

                # If this is the final attempt,
                # hand the failed response back.
                #
                # CachedClient will raise on it,
                # which prevents failed responses
                # from being cached as real data.
                if last_attempt:

                    return response

                # Wait before retrying.
                time.sleep(
                    wait_seconds
                )

                # Exponential backoff:
                #
                # 1 -> 2 -> 4 -> 8 -> ...
                backoff = min(
                    backoff * 2,
                    MAX_BACKOFF_SECONDS,
                )

                continue


            # =================================================
            # OTHER HTTP 4xx FAILURE
            # =================================================

            if status >= 400:

                self._log_failure(
                    url=url,
                    params=params,
                    attempt=attempt,
                    status_code=status,
                    error=f"HTTP {status}",
                    retry_in_seconds=None,
                )


            # =================================================
            # SUCCESS
            # =================================================

            return response


        # This should normally never be reached.
        raise RuntimeError(
            f"Exhausted retries for {url}"
        )