"""
collectors/gamma.py

Polymarket Gamma API collector: market and event metadata.

WHAT THIS IS FOR
----------------
The Data API (collectors/polymarket.py) tells us what was traded. It does not
tell us what the market *was*: when it opened, when it resolved, how much
liquidity stood behind it, what it was about. That is Gamma's job, and almost
every feature in WS7 needs it:

    time-before-event        needs endDate / the resolution date
    abnormal volume          needs volumeNum as a denominator
    share of market liquidity needs liquidityNum
    market selection          needs tags, closed/active, date ranges
    every trader feature      needs conditionId to join back to /trades

conditionId is the join key. A Gamma market record and a Data API trade record
meet there and nowhere else.

WHAT IT COLLECTS
----------------
    fetch_market_by_slug("will-...")            one market, by its slug
    fetch_market_by_condition_id("0x...")       one market, by its condition ID
    fetch_markets(MarketQuery(closed=True))     many markets, paginated
    fetch_events(EventQuery(tag_id=2))          many events, paginated
    collect_markets(query)  -> (rows, metadata) the same, with pagination evidence

Everything comes back normalised to the schema in docs/data_dictionary.md.
tests/test_gamma_collector.py asserts that the two agree, so the schema cannot
drift away from its documentation without a test failing.

The raw response is not thrown away - it is in the cache, byte for byte, with
its retrieval timestamp. normalise_market() is public so anything can be
re-derived from raw without re-fetching.

PAGINATION - READ THIS BEFORE CHANGING IT
-----------------------------------------
The story asks for keyset pagination. Gamma's list endpoints expose `limit` and
`offset`, not a cursor, so this module implements the *safety property* of
keyset pagination on top of offset transport rather than pretending a cursor
exists:

  * the ordering is pinned (`order=id`, `ascending=true`) so pages cannot be
    re-sorted underneath the walk;
  * the highest key seen is carried, and every row whose key has already been
    returned is dropped;
  * `offset` advances by rows *received*, never by the page size we asked for;
  * a page that yields no new keys ends the walk instead of looping forever.

What that buys: a market created while we walk cannot cause a record to be
returned twice, and a re-sorted page cannot corrupt the collection.

What it does NOT buy, and nobody should claim it does: if a market is *removed*
from the result set below the cursor mid-walk, offset shifts backwards and one
record is skipped. There is no client-side defence against that with an
offset-only API. It is recorded in the metadata as a known limitation, and it
is a reason to collect a market catalogue in one sitting rather than resuming a
walk hours later.

WHAT IS AND IS NOT CONFIRMED
----------------------------
Confirmed live on 20 Aug 2026 (docs/data_dictionary.md): the fields `question`,
`slug`, `conditionId`, `startDate`, `endDate`, `volumeNum`, and the parameters
`closed`, `end_date_min`, `end_date_max`, `order`, `ascending`, `limit`.

NOT confirmed, and taken from the published Gamma reference: the parameter
names `slug`, `condition_ids`, `offset`, `tag_id`, and the fields `id`,
`liquidityNum`, `createdAt`, `tags`, `outcomes`, `clobTokenIds`, `active`,
`archived`. They are module constants and normaliser branches precisely so a
disagreement with the live API is a one-line fix rather than a rewrite. Run
`python verify_gamma.py` from a normal connection to settle them and commit the
dated evidence file it writes.

A NOTE ON THE CACHE
-------------------
ResponseCache keys on endpoint + parameters, not on host. Gamma's endpoints
(/markets, /events, /tags) do not collide with the Data API's (/trades,
/activity, /positions, /closed-positions, /holders), so the two share
data/raw/ safely today. test_gamma_collector.py asserts that non-overlap on
every run; if the Data API ever grows a /markets route, that test fails and
tells you to separate them before the collision produces a wrong dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from collectors.cache import CachedClient, ResponseCache
from collectors.session import ThrottledRetryingSession


# ============================================================
# Configuration
# ============================================================

BASE_URL = "https://gamma-api.polymarket.com"

# Documented Gamma ceilings are 500 req/10s on /events and 300 req/10s on
# /markets (WS4 section 3.3). 0.1s between requests is an order of magnitude
# under that. Caching, not throttling, is what keeps the request count low.
MIN_INTERVAL_S = 0.1

DEFAULT_RETRIES = 5

MARKETS_ENDPOINT = "/markets"
EVENTS_ENDPOINT = "/events"

# Rows per request. Kept modest: a Gamma market record carries nested events
# and tags, so 100 records is already a large response.
PAGE_LIMIT = 100

# The field the walk orders by and de-duplicates on.
KEYSET_FIELD = "id"

# Runaway guard. A walk needing more than this many requests is a bug, not a
# big catalogue.
MAX_PAGES = 5_000

# Parameter names. Separated out because only some of them are confirmed
# against the live API - see the module docstring.
SLUG_PARAM = "slug"                     # unconfirmed
CONDITION_ID_PARAM = "condition_ids"    # unconfirmed
ORDER_PARAM = "order"                   # confirmed 20 Aug 2026
ASCENDING_PARAM = "ascending"           # confirmed 20 Aug 2026
LIMIT_PARAM = "limit"                   # confirmed 20 Aug 2026
OFFSET_PARAM = "offset"                 # unconfirmed

# Endpoints served by the Data API, used only by the cache-collision guard.
DATA_API_ENDPOINTS = frozenset({
    "/trades", "/activity", "/positions", "/closed-positions", "/holders",
})

GAMMA_ENDPOINTS = frozenset({MARKETS_ENDPOINT, EVENTS_ENDPOINT, "/tags"})


# ============================================================
# Errors
# ============================================================

class GammaError(RuntimeError):
    """The Gamma API returned something this collector cannot use."""


class MarketNotFound(GammaError):
    """No market matched the slug or condition ID asked for."""


class EventNotFound(GammaError):
    """No event matched the slug or ID asked for."""


class AmbiguousResultError(GammaError):
    """More than one record matched something that should identify one."""


# ============================================================
# Transport and storage
# ============================================================
#
# Same arrangement as collectors/polymarket.py: storage in
# collectors/cache.py, transport in collectors/session.py, and this module
# holding neither. See docs/caching_layer.md.

_default_client: Optional[CachedClient] = None


def default_client() -> CachedClient:
    """The client _get uses, built on first use rather than at import."""

    global _default_client

    if _default_client is None:
        _default_client = CachedClient(
            BASE_URL,
            cache=ResponseCache(),
            session=ThrottledRetryingSession(
                retries=DEFAULT_RETRIES,
                min_interval_s=MIN_INTERVAL_S,
            ),
        )

    return _default_client


def set_default_client(
    client: Optional[CachedClient],
) -> Optional[CachedClient]:
    """Point the module at a different client, or pass None to reset it."""

    global _default_client

    _default_client = client

    return _default_client


def _client_for(retries: int) -> CachedClient:
    """The shared client, unless a caller asked for a different retry budget."""

    if retries == DEFAULT_RETRIES:
        return default_client()

    return CachedClient(
        BASE_URL,
        cache=ResponseCache(),
        session=ThrottledRetryingSession(
            retries=retries,
            min_interval_s=MIN_INTERVAL_S,
        ),
    )


def _get(
    endpoint: str,
    params: dict,
    client: Optional[CachedClient] = None,
    use_cache: bool = True,
    retries: int = DEFAULT_RETRIES,
):
    """
    GET a Gamma endpoint through the cache and the throttled session.

    Pass client= to use a specific cache directory, an offline client, or a
    fake session in a test. Otherwise the module default is used.

    use_cache=False re-fetches; the response is still written to the cache,
    because a gap in the raw store is a gap in the run's evidence trail.
    """

    api = client if client is not None else _client_for(retries)

    return api.get_json(endpoint, params, refresh=not use_cache)


def _rows(payload, endpoint: str) -> list:
    """
    Get the list of records out of a response.

    Gamma serves a bare JSON array on the list endpoints. Some Polymarket
    services wrap results in an envelope instead, so both are accepted - but
    anything else raises rather than being coerced into an empty list, because
    "the response changed shape" and "there are no markets" must never look
    the same to a collector.
    """

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ("data", "markets", "events", "results"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return inner

    raise GammaError(
        "Gamma {} returned {}, not a list of records. The response shape has "
        "changed; do not paper over this - re-run verify_gamma.py and update "
        "the collector.".format(endpoint, type(payload).__name__)
    )


# ============================================================
# Coercion helpers
# ============================================================
#
# Gamma is loose about types: numbers arrive as strings, lists arrive as
# JSON-encoded strings, dates arrive with a trailing Z. Every one of those is
# handled here rather than in each caller, so downstream code can rely on the
# normalised record's types.

def _as_float(value) -> Optional[float]:
    """Money and volume figures, which arrive as either numbers or strings."""

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "")
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _as_bool(value) -> Optional[bool]:
    """closed / active / archived, which arrive as booleans or as strings."""

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in ("true", "1", "yes"):
        return True

    if text in ("false", "0", "no"):
        return False

    return None


def _as_str_list(value) -> list:
    """
    outcomes and clobTokenIds, which Gamma has been observed to serve as a
    JSON-encoded string - '["Yes", "No"]' rather than ["Yes", "No"].

    Returning [] for a missing value rather than None keeps the schema's type
    stable, which matters because these end up as dataframe columns.
    """

    if value is None:
        return []

    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]

    text = str(value).strip()
    if not text:
        return []

    if text.startswith("["):
        try:
            decoded = json.loads(text)
        except ValueError:
            return [text]

        if isinstance(decoded, list):
            return [str(item) for item in decoded]

    return [text]


def _parse_datetime(value) -> Optional[datetime]:
    """Parse an ISO 8601 string, treating a naive timestamp as UTC."""

    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _as_iso_utc(value) -> Optional[str]:
    """
    Normalise a date to UTC ISO 8601.

    An unparsable value is passed through unchanged rather than dropped: losing
    a date we could not parse would be worse than carrying it forward where
    somebody can see it and fix the parser.
    """

    parsed = _parse_datetime(value)

    if parsed is None:
        text = None if value is None else str(value).strip()
        return text or None

    return parsed.isoformat()


def _as_unix(value) -> Optional[int]:
    """
    The same date as Unix seconds.

    Carried alongside the ISO string because the Data API works in Unix
    seconds - collect_trades takes start/end that way - and converting at the
    call site is how off-by-a-timezone bugs get in.
    """

    parsed = _parse_datetime(value)

    return None if parsed is None else int(parsed.timestamp())


def _as_text(value) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def extract_tags(raw: dict) -> list:
    """
    The tag slugs attached to a market or event.

    Gamma attaches tags to events. A market record has been documented to carry
    both its own `tags` and its parent `events`, each of which may carry tags,
    so both are read and the result de-duplicated with order preserved. A tag
    may be an object ({id, label, slug}) or a bare string; slug is preferred
    because it is the stable identifier, with label and id as fallbacks.

    UNCONFIRMED against the live API - see the module docstring.
    """

    found = []
    seen = set()

    def add(tag):
        if isinstance(tag, dict):
            value = tag.get("slug") or tag.get("label") or tag.get("id")
        else:
            value = tag

        if value is None:
            return

        text = str(value).strip()

        if text and text not in seen:
            seen.add(text)
            found.append(text)

    for tag in raw.get("tags") or []:
        add(tag)

    for event in raw.get("events") or []:
        if isinstance(event, dict):
            for tag in event.get("tags") or []:
                add(tag)

    return found


# ============================================================
# Normalisation
# ============================================================
#
# The field names and order below ARE the schema in
# docs/data_dictionary.md. Change one and the other must change with it;
# test_gamma_collector.py fails if they disagree.

MARKET_FIELDS = (
    "condition_id",
    "market_id",
    "question",
    "slug",
    "event_slug",
    "tags",
    "liquidity_num",
    "volume_num",
    "start_date",
    "end_date",
    "created_at",
    "start_date_ts",
    "end_date_ts",
    "created_at_ts",
    "closed",
    "active",
    "archived",
    "outcomes",
    "clob_token_ids",
)

EVENT_FIELDS = (
    "event_id",
    "title",
    "slug",
    "tags",
    "liquidity_num",
    "volume_num",
    "start_date",
    "end_date",
    "created_at",
    "start_date_ts",
    "end_date_ts",
    "created_at_ts",
    "closed",
    "active",
    "archived",
    "market_condition_ids",
    "market_count",
)


def _first_event_slug(raw: dict) -> Optional[str]:
    """A market's event slug, whether it is given directly or via events[]."""

    direct = _as_text(raw.get("eventSlug"))
    if direct:
        return direct

    for event in raw.get("events") or []:
        if isinstance(event, dict):
            slug = _as_text(event.get("slug"))
            if slug:
                return slug

    return None


def normalise_market(raw: dict) -> dict:
    """
    One raw Gamma market record -> the project's market schema.

    Public so a stored raw response can be re-normalised without re-fetching.
    """

    if not isinstance(raw, dict):
        raise GammaError(
            "Expected a market object, got {}.".format(type(raw).__name__)
        )

    return {
        "condition_id": _as_text(raw.get("conditionId")),
        "market_id": _as_text(raw.get("id")),
        "question": _as_text(raw.get("question")),
        "slug": _as_text(raw.get("slug")),
        "event_slug": _first_event_slug(raw),
        "tags": extract_tags(raw),
        "liquidity_num": _as_float(
            raw.get("liquidityNum", raw.get("liquidity"))
        ),
        "volume_num": _as_float(
            raw.get("volumeNum", raw.get("volume"))
        ),
        "start_date": _as_iso_utc(raw.get("startDate")),
        "end_date": _as_iso_utc(raw.get("endDate")),
        "created_at": _as_iso_utc(raw.get("createdAt")),
        "start_date_ts": _as_unix(raw.get("startDate")),
        "end_date_ts": _as_unix(raw.get("endDate")),
        "created_at_ts": _as_unix(raw.get("createdAt")),
        "closed": _as_bool(raw.get("closed")),
        "active": _as_bool(raw.get("active")),
        "archived": _as_bool(raw.get("archived")),
        "outcomes": _as_str_list(raw.get("outcomes")),
        "clob_token_ids": _as_str_list(raw.get("clobTokenIds")),
    }


def normalise_event(raw: dict) -> dict:
    """One raw Gamma event record -> the project's event schema."""

    if not isinstance(raw, dict):
        raise GammaError(
            "Expected an event object, got {}.".format(type(raw).__name__)
        )

    condition_ids = []
    for market in raw.get("markets") or []:
        if isinstance(market, dict):
            condition_id = _as_text(market.get("conditionId"))
            if condition_id and condition_id not in condition_ids:
                condition_ids.append(condition_id)

    return {
        "event_id": _as_text(raw.get("id")),
        "title": _as_text(raw.get("title")),
        "slug": _as_text(raw.get("slug")),
        "tags": extract_tags(raw),
        "liquidity_num": _as_float(
            raw.get("liquidityNum", raw.get("liquidity"))
        ),
        "volume_num": _as_float(
            raw.get("volumeNum", raw.get("volume"))
        ),
        "start_date": _as_iso_utc(raw.get("startDate")),
        "end_date": _as_iso_utc(raw.get("endDate")),
        "created_at": _as_iso_utc(raw.get("createdAt")),
        "start_date_ts": _as_unix(raw.get("startDate")),
        "end_date_ts": _as_unix(raw.get("endDate")),
        "created_at_ts": _as_unix(raw.get("createdAt")),
        "closed": _as_bool(raw.get("closed")),
        "active": _as_bool(raw.get("active")),
        "archived": _as_bool(raw.get("archived")),
        "market_condition_ids": condition_ids,
        "market_count": len(condition_ids),
    }


# ============================================================
# Queries
# ============================================================

@dataclass
class MarketQuery:
    """
    Which markets to collect.

    Every filter is optional and only the ones you set are sent, so an empty
    MarketQuery() walks the whole catalogue. `closed`, `end_date_min` and
    `end_date_max` are confirmed against the live API; the rest are documented
    but unconfirmed.

    max_records is a deliberate brake. Walking every market Polymarket has ever
    listed is rarely what anyone means, and finding that out after 4,000
    requests is worse than being stopped early with it recorded in the
    metadata.
    """

    closed: Optional[bool] = None
    active: Optional[bool] = None
    archived: Optional[bool] = None

    start_date_min: Optional[str] = None
    start_date_max: Optional[str] = None
    end_date_min: Optional[str] = None
    end_date_max: Optional[str] = None

    liquidity_num_min: Optional[float] = None
    volume_num_min: Optional[float] = None

    tag_id: Optional[int] = None

    limit: int = PAGE_LIMIT
    max_records: Optional[int] = None

    # Anything else the API accepts that this dataclass does not name yet.
    # Recorded in the metadata like every other filter, so an ad-hoc parameter
    # still ends up in the evidence trail.
    extra: dict = field(default_factory=dict)

    def filters(self) -> dict:
        """The filter parameters, without paging or ordering."""

        named = {
            "closed": self.closed,
            "active": self.active,
            "archived": self.archived,
            "start_date_min": self.start_date_min,
            "start_date_max": self.start_date_max,
            "end_date_min": self.end_date_min,
            "end_date_max": self.end_date_max,
            "liquidity_num_min": self.liquidity_num_min,
            "volume_num_min": self.volume_num_min,
            "tag_id": self.tag_id,
        }

        chosen = {
            name: value
            for name, value in named.items()
            if value is not None
        }

        chosen.update(
            {
                name: value
                for name, value in (self.extra or {}).items()
                if value is not None
            }
        )

        return chosen


@dataclass
class EventQuery(MarketQuery):
    """Which events to collect. Same filters as MarketQuery."""


# ============================================================
# Keyset pagination
# ============================================================

def _new_walk_stats(endpoint: str, query: MarketQuery) -> dict:
    return {
        "endpoint": endpoint,
        "keyset_field": KEYSET_FIELD,
        "page_limit": query.limit,
        "filters": query.filters(),
        "requests": 0,
        "pages": 0,
        "raw_records_received": 0,
        "duplicates_dropped": 0,
        "rows_without_key": 0,
        "records_returned": 0,
        "stopped_because": None,
        "truncated_by_max_records": False,
    }


def _walk(
    endpoint: str,
    query: MarketQuery,
    client: Optional[CachedClient],
    stats: dict,
) -> Iterator[dict]:
    """
    Walk a Gamma list endpoint, yielding each raw record exactly once.

    See the module docstring for what this does and does not guarantee. The
    short version: ordering is pinned, keys already seen are dropped, offset
    advances by rows received, and a page with no new keys ends the walk.
    """

    if query.limit <= 0:
        raise ValueError("limit must be greater than zero.")

    if query.max_records is not None and query.max_records <= 0:
        raise ValueError("max_records must be greater than zero, or None.")

    offset = 0
    seen_keys = set()

    while True:
        if stats["pages"] >= MAX_PAGES:
            raise GammaError(
                "Gamma {} walk exceeded {} requests. That is a bug or a "
                "filter that matches the whole catalogue - set max_records "
                "or narrow the query.".format(endpoint, MAX_PAGES)
            )

        params = dict(query.filters())
        params[LIMIT_PARAM] = query.limit
        params[OFFSET_PARAM] = offset
        params[ORDER_PARAM] = KEYSET_FIELD
        params[ASCENDING_PARAM] = True

        rows = _rows(_get(endpoint, params, client=client), endpoint)

        stats["requests"] += 1
        stats["pages"] += 1
        stats["raw_records_received"] += len(rows)

        if not rows:
            stats["stopped_because"] = "empty page"
            return

        new_this_page = 0

        for row in rows:
            key = row.get(KEYSET_FIELD) if isinstance(row, dict) else None

            if key is None:
                # Cannot de-duplicate a record with no key. Keeping it is the
                # lesser evil - dropping records because of a missing field
                # would be a silent data loss - but the count is reported so
                # nobody has to guess whether it happened.
                stats["rows_without_key"] += 1
            else:
                text_key = str(key)

                if text_key in seen_keys:
                    stats["duplicates_dropped"] += 1
                    continue

                seen_keys.add(text_key)

            new_this_page += 1
            stats["records_returned"] += 1

            yield row

            if (
                query.max_records is not None
                and stats["records_returned"] >= query.max_records
            ):
                stats["truncated_by_max_records"] = True
                stats["stopped_because"] = "max_records reached"
                return

        offset += len(rows)

        # A short page means the end of the result set.
        if len(rows) < query.limit:
            stats["stopped_because"] = "short page"
            return

        # A full page of records we have already returned means the walk has
        # stopped advancing. Continuing would loop forever.
        if new_this_page == 0:
            stats["stopped_because"] = "page contained no new keys"
            return


# ============================================================
# Single-record lookups
# ============================================================

def _exactly_one(rows, description, error_class, match=None):
    """
    One record, or a loud failure.

    A lookup by slug or condition ID is supposed to identify a single market.
    Returning rows[0] out of several would quietly pick one at random, and the
    project would carry an arbitrary market through to the case studies.
    """

    if not rows:
        raise error_class("No Gamma record matched {}.".format(description))

    candidates = rows

    if match is not None:
        exact = [row for row in rows if isinstance(row, dict) and match(row)]

        if exact:
            candidates = exact

    if len(candidates) > 1:
        raise AmbiguousResultError(
            "{} matched {} records. That identifier is supposed to identify "
            "one market - do not guess which.".format(
                description, len(candidates)
            )
        )

    return candidates[0]


def fetch_market_by_slug(
    slug: str,
    client: Optional[CachedClient] = None,
) -> dict:
    """
    One market, by slug, normalised.

    Raises MarketNotFound if nothing matches, AmbiguousResultError if more
    than one does.
    """

    if not slug or not str(slug).strip():
        raise ValueError("slug is required.")

    slug = str(slug).strip()

    params = {SLUG_PARAM: slug, LIMIT_PARAM: query_limit_for_lookup()}

    rows = _rows(
        _get(MARKETS_ENDPOINT, params, client=client), MARKETS_ENDPOINT
    )

    record = _exactly_one(
        rows,
        "slug {!r}".format(slug),
        MarketNotFound,
        match=lambda row: _as_text(row.get("slug")) == slug,
    )

    return normalise_market(record)


def fetch_market_by_condition_id(
    condition_id: str,
    client: Optional[CachedClient] = None,
) -> dict:
    """
    One market, by condition ID, normalised.

    conditionId is the join key to the Data API, so this is the lookup the
    rest of the pipeline uses. Matching is case-insensitive: a 0x hash is the
    same hash whatever case it is written in, and seeds.json, the API and a
    block explorer do not always agree on that.
    """

    if not condition_id or not str(condition_id).strip():
        raise ValueError("condition_id is required.")

    condition_id = str(condition_id).strip()

    params = {
        CONDITION_ID_PARAM: condition_id,
        LIMIT_PARAM: query_limit_for_lookup(),
    }

    rows = _rows(
        _get(MARKETS_ENDPOINT, params, client=client), MARKETS_ENDPOINT
    )

    record = _exactly_one(
        rows,
        "condition ID {!r}".format(condition_id),
        MarketNotFound,
        match=lambda row: (
            str(row.get("conditionId") or "").lower() == condition_id.lower()
        ),
    )

    return normalise_market(record)


def fetch_event_by_slug(
    slug: str,
    client: Optional[CachedClient] = None,
) -> dict:
    """One event, by slug, normalised."""

    if not slug or not str(slug).strip():
        raise ValueError("slug is required.")

    slug = str(slug).strip()

    params = {SLUG_PARAM: slug, LIMIT_PARAM: query_limit_for_lookup()}

    rows = _rows(_get(EVENTS_ENDPOINT, params, client=client), EVENTS_ENDPOINT)

    record = _exactly_one(
        rows,
        "slug {!r}".format(slug),
        EventNotFound,
        match=lambda row: _as_text(row.get("slug")) == slug,
    )

    return normalise_event(record)


def query_limit_for_lookup() -> int:
    """
    How many rows a by-name lookup asks for.

    More than one, deliberately. Asking for exactly one row would make an
    ambiguous slug indistinguishable from a unique one - the API would hand
    back a single record either way and _exactly_one could never fire.
    """

    return 5


# ============================================================
# Collection
# ============================================================

def fetch_markets(
    query: Optional[MarketQuery] = None,
    client: Optional[CachedClient] = None,
    stats: Optional[dict] = None,
) -> Iterator[dict]:
    """
    Every market matching the query, normalised, one at a time.

    Pass a dict as stats= to receive the pagination evidence, or use
    collect_markets() which does that for you.
    """

    query = query if query is not None else MarketQuery()

    tracker = _new_walk_stats(MARKETS_ENDPOINT, query)

    if stats is not None:
        stats.clear()
        stats.update(tracker)
        tracker = stats

    for row in _walk(MARKETS_ENDPOINT, query, client, tracker):
        yield normalise_market(row)


def fetch_events(
    query: Optional[EventQuery] = None,
    client: Optional[CachedClient] = None,
    stats: Optional[dict] = None,
) -> Iterator[dict]:
    """Every event matching the query, normalised, one at a time."""

    query = query if query is not None else EventQuery()

    tracker = _new_walk_stats(EVENTS_ENDPOINT, query)

    if stats is not None:
        stats.clear()
        stats.update(tracker)
        tracker = stats

    for row in _walk(EVENTS_ENDPOINT, query, client, tracker):
        yield normalise_event(row)


def _collection_metadata(stats: dict, records: list) -> dict:
    """The evidence record that travels with a collection."""

    return {
        "source": "Polymarket Gamma API",
        "base_url": BASE_URL,
        "endpoint": stats["endpoint"],
        "filters": stats["filters"],
        "pagination_method": (
            "keyset safety over offset transport: ordering pinned to "
            "{}={} ascending, offset advanced by rows received, keys already "
            "returned dropped".format(ORDER_PARAM, KEYSET_FIELD)
        ),
        "keyset_field": stats["keyset_field"],
        "page_limit": stats["page_limit"],
        "request_count": stats["requests"],
        "pages": stats["pages"],
        "raw_records_received": stats["raw_records_received"],
        "duplicates_dropped": stats["duplicates_dropped"],
        "rows_without_key": stats["rows_without_key"],
        "final_record_count": len(records),
        "truncated_by_max_records": stats["truncated_by_max_records"],
        "stopped_because": stats["stopped_because"],
        "known_limitation": (
            "Offset pagination cannot detect a record removed from the result "
            "set below the cursor mid-walk; such a record would be skipped. "
            "Collect a catalogue in one sitting rather than resuming later."
        ),
    }


def collect_markets(
    query: Optional[MarketQuery] = None,
    client: Optional[CachedClient] = None,
):
    """
    Collect markets and the evidence of how they were collected.

    Returns
    -------
    markets : list
        Normalised market records, in ascending key order.

    metadata : dict
        Filters, pagination method and per-request counts.
    """

    stats: dict = {}

    markets = list(fetch_markets(query, client=client, stats=stats))

    return markets, _collection_metadata(stats, markets)


def collect_events(
    query: Optional[EventQuery] = None,
    client: Optional[CachedClient] = None,
):
    """Collect events and the evidence of how they were collected."""

    stats: dict = {}

    events = list(fetch_events(query, client=client, stats=stats))

    return events, _collection_metadata(stats, events)


# ============================================================
# Saving
# ============================================================

def save_collection(
    records: list,
    metadata: dict,
    output_dir="data/raw/gamma",
    name="markets",
):
    """
    Save a normalised collection and its metadata, the same way
    collectors.polymarket.save_trade_collection does.

    The raw responses are already in the cache with their retrieval
    timestamps; this is the analysis-ready copy.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records_path = output_dir / "{}.json".format(name)
    metadata_path = output_dir / "{}_metadata.json".format(name)

    records_path.write_text(
        json.dumps(records, indent=2, default=str), encoding="utf-8"
    )

    metadata_path.write_text(
        json.dumps(metadata, indent=2, default=str), encoding="utf-8"
    )

    return records_path, metadata_path
