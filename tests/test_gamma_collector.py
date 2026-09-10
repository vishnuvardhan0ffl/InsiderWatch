"""
The Gamma market and event collector.

Three jobs, in order of how much trouble they save:

  1. The by-name lookups do what the story says - a market by slug and a market
     by condition ID - and fail loudly rather than guessing when the answer is
     not exactly one market.

  2. The collector's output schema and docs/data_dictionary.md agree, field for
     field. Not "roughly agree": the test reads the markdown table and compares
     it to what normalise_market() actually emits. A schema documented in one
     place and implemented in another drifts apart within a fortnight, and
     nobody notices until a feature is computed from a column that no longer
     exists.

  3. The keyset walk returns every record exactly once. Gamma pages by offset,
     which is not safe on its own - see the module docstring in
     collectors/gamma.py. The tests below prove the guard works by feeding the
     collector pages that overlap the way a shifting result set would.

Everything runs against tests/fixtures/gamma_markets.json and
gamma_events.json, offline, through the real cache. Those fixtures are marked
UNVERIFIED in MANIFEST.json: their shape comes from documentation, not from a
live response. They are safe to test against and must not be cited as evidence
of what Gamma returns. Run verify_gamma.py to settle that.
"""

import json
from pathlib import Path

import pytest

from collectors import gamma
from collectors.cache import CachedClient, ResponseCache, endpoint_folder

from tests.conftest import FakeResponse, ReplaySession, load_fixture

REPO_ROOT = Path(__file__).resolve().parent.parent

MARKETS_URL = gamma.BASE_URL + "/markets"
EVENTS_URL = gamma.BASE_URL + "/events"

MADURO_SLUG = "nicolas-maduro-released-from-custody-by-january-31-2026"
MADURO_CONDITION_ID = (
    "0xd1e4e03a0129aad7b23e835bfb5c0166d7342fb98e91aa7dd0f3e6cb423d9c21"
)


# ===========================================================================
# A fake Gamma API
# ===========================================================================

class GammaSession:
    """
    Answers /markets and /events from the recorded fixtures, honouring the
    filters and paging parameters the collector actually sends.

    A dumber fake - one that returns the whole fixture whatever it was asked -
    would let a collector that ignored `offset` entirely pass every test here.
    """

    def __init__(self, markets=None, events=None):
        self.markets = (
            markets if markets is not None
            else load_fixture("gamma_markets.json")
        )
        self.events = (
            events if events is not None
            else load_fixture("gamma_events.json")
        )
        self.calls = []

    def get(self, url, params=None, timeout=None):
        pairs = list(params or [])
        self.calls.append((url, pairs))
        sent = dict(pairs)

        endpoint = "/" + url.rstrip("/").rsplit("/", 1)[-1]
        rows = {"/markets": self.markets, "/events": self.events}.get(
            endpoint, []
        )

        if "slug" in sent:
            rows = [row for row in rows if row.get("slug") == sent["slug"]]

        if "condition_ids" in sent:
            wanted = {
                value.strip().lower()
                for value in sent["condition_ids"].split(",")
            }
            rows = [
                row for row in rows
                if str(row.get("conditionId") or "").lower() in wanted
            ]

        if sent.get("closed") in ("true", "false"):
            wanted_closed = sent["closed"] == "true"
            rows = [
                row for row in rows
                if bool(row.get("closed")) is wanted_closed
            ]

        if sent.get("order") == "id":
            rows = sorted(
                rows,
                key=lambda row: int(row["id"]),
                reverse=sent.get("ascending") == "false",
            )

        offset = int(sent.get("offset", 0))
        limit = int(sent.get("limit", gamma.PAGE_LIMIT))

        return FakeResponse(
            json.dumps(rows[offset:offset + limit]).encode(), url=url
        )

    @property
    def params_sent(self):
        return dict(self.calls[-1][1]) if self.calls else {}


class ScriptedGammaSession:
    """
    Hands back the pages you give it, in order, and repeats the last one.

    For the pagination tests, where the point is to feed the collector pages
    that overlap or repeat - which is what a result set shifting mid-walk
    looks like from the client's side.
    """

    def __init__(self, *pages):
        self.pages = [list(page) for page in pages] or [[]]
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, list(params or [])))

        index = min(len(self.calls) - 1, len(self.pages) - 1)

        return FakeResponse(
            json.dumps(self.pages[index]).encode(), url=url
        )


@pytest.fixture
def gamma_api(cache_dir):
    """Build a Gamma client with the fake session of your choosing."""

    def build(session=None, **kwargs):
        return CachedClient(
            gamma.BASE_URL,
            cache=ResponseCache(cache_dir),
            session=session,
            **kwargs
        )

    return build


@pytest.fixture
def api(gamma_api):
    """The common case: a client answering from the recorded fixtures."""

    return gamma_api(GammaSession())


def markets_fixture():
    return load_fixture("gamma_markets.json")


# ===========================================================================
# 1. The by-name lookups - the story's first acceptance criterion
# ===========================================================================

def test_a_market_is_retrieved_by_slug(api):
    market = gamma.fetch_market_by_slug(MADURO_SLUG, client=api)

    assert market["slug"] == MADURO_SLUG
    assert market["condition_id"] == MADURO_CONDITION_ID
    assert market["question"].startswith("Nicol")


def test_a_market_is_retrieved_by_condition_id(api):
    market = gamma.fetch_market_by_condition_id(
        MADURO_CONDITION_ID, client=api
    )

    assert market["condition_id"] == MADURO_CONDITION_ID
    assert market["slug"] == MADURO_SLUG


def test_a_condition_id_matches_whatever_case_it_is_written_in(api):
    """seeds.json, the API and a block explorer do not always agree on case."""

    market = gamma.fetch_market_by_condition_id(
        MADURO_CONDITION_ID.upper().replace("0X", "0x"), client=api
    )

    assert market["condition_id"] == MADURO_CONDITION_ID


def test_the_lookups_go_to_the_gamma_host_not_the_data_api(api):
    gamma.fetch_market_by_slug(MADURO_SLUG, client=api)

    assert api.session.calls[0][0] == MARKETS_URL


def test_every_seed_market_can_be_found_by_its_condition_id(api):
    """The three seed cases are the reason this collector exists."""

    seeds = json.loads(
        (REPO_ROOT / "config" / "seeds.json").read_text(encoding="utf-8")
    )

    for seed in seeds["markets"]:
        market = gamma.fetch_market_by_condition_id(
            seed["condition_id"], client=api
        )

        assert market["condition_id"] == seed["condition_id"]
        assert market["end_date_ts"] is not None


def test_an_unknown_slug_raises_rather_than_returning_nothing(api):
    with pytest.raises(gamma.MarketNotFound):
        gamma.fetch_market_by_slug("a-market-that-does-not-exist", client=api)


def test_an_unknown_condition_id_raises(api):
    with pytest.raises(gamma.MarketNotFound):
        gamma.fetch_market_by_condition_id("0xdeadbeef", client=api)


def test_two_markets_sharing_a_slug_raise_rather_than_one_being_picked(
    gamma_api,
):
    """
    Returning rows[0] out of several would silently carry an arbitrary market
    into the case studies. Refusing is the whole point.
    """

    twins = markets_fixture()[:2]
    for row in twins:
        row["slug"] = "duplicated-slug"

    api = gamma_api(GammaSession(markets=twins))

    with pytest.raises(gamma.AmbiguousResultError):
        gamma.fetch_market_by_slug("duplicated-slug", client=api)


def test_an_empty_slug_is_rejected_before_a_request_is_made(api):
    with pytest.raises(ValueError):
        gamma.fetch_market_by_slug("   ", client=api)

    assert api.session.calls == []


def test_an_event_is_retrieved_by_slug(api):
    event = gamma.fetch_event_by_slug("nobel-peace-prize-2025", client=api)

    assert event["slug"] == "nobel-peace-prize-2025"
    assert event["title"] == "Nobel Peace Prize 2025"
    assert api.session.calls[0][0] == EVENTS_URL


# ===========================================================================
# 2. The schema and its documentation agree
# ===========================================================================

def documented_fields(heading):
    """
    The field names in the markdown table under a heading in
    docs/data_dictionary.md.

    Reading the documentation rather than duplicating it here is deliberate:
    a copy of the schema in the test would drift alongside the code and the
    test would keep passing while the documentation went stale.
    """

    text = (REPO_ROOT / "docs" / "data_dictionary.md").read_text(
        encoding="utf-8"
    )

    body = text[text.index(heading) + len(heading):]

    fields = []
    inside_table = False

    for line in body.splitlines():
        line = line.strip()

        if line.startswith("## "):
            break

        if not line.startswith("|"):
            continue

        first = [cell.strip() for cell in line.strip("|").split("|")][0]

        if first.lower() == "field" or set(first) <= set("-: "):
            inside_table = True
            continue

        if inside_table:
            fields.append(first.strip("`"))

    return fields


def test_the_market_record_matches_the_data_dictionary(api):
    documented = documented_fields(
        "## Gamma collector output — market record"
    )

    assert documented, "the market table is missing from the data dictionary"
    assert documented == list(gamma.MARKET_FIELDS)

    market = gamma.fetch_market_by_slug(MADURO_SLUG, client=api)

    assert list(market) == documented


def test_the_event_record_matches_the_data_dictionary(api):
    documented = documented_fields(
        "## Gamma collector output — event record"
    )

    assert documented, "the event table is missing from the data dictionary"
    assert documented == list(gamma.EVENT_FIELDS)

    event = gamma.fetch_event_by_slug("nobel-peace-prize-2025", client=api)

    assert list(event) == documented


def test_every_collected_market_carries_the_whole_schema(api):
    markets, _ = gamma.collect_markets(
        gamma.MarketQuery(limit=2), client=api
    )

    assert markets
    for market in markets:
        assert list(market) == list(gamma.MARKET_FIELDS)


# ===========================================================================
# 3. The keyset walk
# ===========================================================================

def test_the_walk_returns_every_market_exactly_once_across_pages(api):
    markets, metadata = gamma.collect_markets(
        gamma.MarketQuery(limit=2), client=api
    )

    expected = [row["id"] for row in markets_fixture()]

    assert [market["market_id"] for market in markets] == expected
    assert metadata["request_count"] == 3      # 2 + 2 + 1
    assert metadata["duplicates_dropped"] == 0
    assert metadata["stopped_because"] == "short page"


def test_the_walk_pins_the_ordering_on_every_request(api):
    """
    Offset pagination over an unordered result set is not pagination, it is a
    sampling method. Every request must carry the ordering.
    """

    gamma.collect_markets(gamma.MarketQuery(limit=2), client=api)

    for _, pairs in api.session.calls:
        sent = dict(pairs)
        assert sent["order"] == gamma.KEYSET_FIELD
        assert sent["ascending"] == "true"


def test_a_record_already_returned_is_dropped_when_a_page_shifts(gamma_api):
    """
    A market created above the cursor shifts everything down and the next page
    repeats a row. Without the key check that row would be collected twice and
    every count derived from the catalogue would be wrong.
    """

    rows = markets_fixture()
    session = ScriptedGammaSession(rows[0:2], rows[1:3], [])
    api = gamma_api(session)

    markets, metadata = gamma.collect_markets(
        gamma.MarketQuery(limit=2), client=api
    )

    assert [market["market_id"] for market in markets] == [
        rows[0]["id"], rows[1]["id"], rows[2]["id"]
    ]
    assert metadata["duplicates_dropped"] == 1
    assert metadata["final_record_count"] == 3


def test_the_walk_stops_when_a_page_contains_nothing_new(gamma_api):
    """An API that ignores offset would otherwise loop until MAX_PAGES."""

    rows = markets_fixture()
    api = gamma_api(ScriptedGammaSession(rows[0:2]))

    markets, metadata = gamma.collect_markets(
        gamma.MarketQuery(limit=2), client=api
    )

    assert len(markets) == 2
    assert metadata["stopped_because"] == "page contained no new keys"
    assert metadata["duplicates_dropped"] == 2


def test_max_records_stops_the_walk_and_says_so_in_the_metadata(api):
    markets, metadata = gamma.collect_markets(
        gamma.MarketQuery(limit=2, max_records=3), client=api
    )

    assert len(markets) == 3
    assert metadata["truncated_by_max_records"] is True
    assert metadata["stopped_because"] == "max_records reached"


def test_a_filter_is_sent_and_recorded_in_the_metadata(api):
    markets, metadata = gamma.collect_markets(
        gamma.MarketQuery(closed=False, limit=10), client=api
    )

    assert metadata["filters"] == {"closed": False}
    assert [market["slug"] for market in markets] == [
        "strait-of-hormuz-traffic-returns-to-normal-by-may-15"
    ]


def test_the_metadata_records_the_pagination_method_and_its_limitation(api):
    _, metadata = gamma.collect_markets(gamma.MarketQuery(limit=2), client=api)

    assert metadata["source"] == "Polymarket Gamma API"
    assert metadata["base_url"] == gamma.BASE_URL
    assert metadata["keyset_field"] == gamma.KEYSET_FIELD
    assert "offset advanced by rows received" in metadata["pagination_method"]

    # The honest bit. If somebody deletes this the report loses the caveat.
    assert "removed from the result set" in metadata["known_limitation"]


def test_a_zero_page_limit_is_rejected(api):
    with pytest.raises(ValueError):
        list(gamma.fetch_markets(gamma.MarketQuery(limit=0), client=api))


# ===========================================================================
# 4. Coercion - Gamma is loose about types
# ===========================================================================

def by_slug(markets, slug):
    return next(market for market in markets if market["slug"] == slug)


def test_numbers_are_floats_whether_the_api_sent_a_string_or_a_number(api):
    markets, _ = gamma.collect_markets(gamma.MarketQuery(), client=api)

    maduro = by_slug(markets, MADURO_SLUG)
    nobel = by_slug(
        markets, "will-mara-corina-machado-win-the-nobel-peace-prize-in-2025"
    )

    assert maduro["volume_num"] == pytest.approx(9884120.77)   # sent as string
    assert nobel["volume_num"] == pytest.approx(1420331.5)     # sent as number
    assert isinstance(maduro["liquidity_num"], float)


def test_liquidity_and_volume_fall_back_to_the_unsuffixed_key_names(api):
    """One observed record carries `liquidity`/`volume`, not the Num variants."""

    markets, _ = gamma.collect_markets(gamma.MarketQuery(), client=api)
    iran = by_slug(markets, "us-x-iran-ceasefire-by-april-7")

    assert iran["liquidity_num"] == pytest.approx(77450.20)
    assert iran["volume_num"] == pytest.approx(2210884.03)


def test_json_encoded_lists_are_decoded(api):
    markets, _ = gamma.collect_markets(gamma.MarketQuery(), client=api)

    maduro = by_slug(markets, MADURO_SLUG)          # '["Yes", "No"]'
    nobel = by_slug(
        markets, "will-mara-corina-machado-win-the-nobel-peace-prize-in-2025"
    )                                               # a real list

    assert maduro["outcomes"] == ["Yes", "No"]
    assert nobel["outcomes"] == ["Yes", "No"]
    assert len(maduro["clob_token_ids"]) == 2
    assert all(isinstance(item, str) for item in maduro["clob_token_ids"])


def test_dates_are_normalised_to_utc_and_carried_as_unix_seconds(api):
    market = gamma.fetch_market_by_slug(MADURO_SLUG, client=api)

    assert market["end_date"] == "2026-01-31T00:00:00+00:00"
    assert market["end_date_ts"] == 1769817600
    assert market["created_at_ts"] < market["end_date_ts"]


def test_a_missing_date_becomes_none_rather_than_breaking_the_record(api):
    """The Iran market has a null createdAt. That is a fact, not a failure."""

    market = gamma.fetch_market_by_slug(
        "us-x-iran-ceasefire-by-april-7", client=api
    )

    assert market["created_at"] is None
    assert market["created_at_ts"] is None
    assert market["end_date_ts"] is not None


def test_an_unparsable_date_is_carried_through_rather_than_dropped():
    """Losing a date we could not parse is worse than showing it to someone."""

    record = gamma.normalise_market({"endDate": "next Tuesday"})

    assert record["end_date"] == "next Tuesday"
    assert record["end_date_ts"] is None


def test_tags_come_from_the_market_and_from_its_parent_event(api):
    nobel = gamma.fetch_market_by_slug(
        "will-mara-corina-machado-win-the-nobel-peace-prize-in-2025",
        client=api,
    )

    # nobel-prize and politics on the market; politics and awards on the event.
    assert nobel["tags"] == ["nobel-prize", "politics", "awards"]


def test_bare_string_tags_are_handled_as_well_as_tag_objects(api):
    event = gamma.fetch_event_by_slug("strait-of-hormuz", client=api)

    assert event["tags"] == ["geopolitics", "shipping"]


def test_an_event_slug_is_taken_from_the_parent_event_when_not_given(api):
    trump = gamma.fetch_market_by_slug(
        "will-donald-trump-win-the-2024-us-presidential-election", client=api
    )
    maduro = gamma.fetch_market_by_slug(MADURO_SLUG, client=api)

    assert trump["event_slug"] == "presidential-election-winner-2024"
    assert maduro["event_slug"] == "maduro-custody-2026"   # given directly


# ===========================================================================
# 5. Events, and the join back to the trade data
# ===========================================================================

def test_an_event_carries_the_condition_ids_of_its_markets(api):
    events, metadata = gamma.collect_events(
        gamma.EventQuery(limit=2), client=api
    )

    election = next(
        event for event in events
        if event["slug"] == "presidential-election-winner-2024"
    )

    assert election["market_count"] == 2
    assert MADURO_CONDITION_ID not in election["market_condition_ids"]
    assert all(
        condition_id.startswith("0x")
        for condition_id in election["market_condition_ids"]
    )
    assert metadata["endpoint"] == "/events"


# ===========================================================================
# 6. Failure, caching and the shared cache directory
# ===========================================================================

def test_a_response_that_is_not_a_list_fails_loudly(gamma_api):
    """
    "The response changed shape" and "there are no markets" must never look
    the same to a collector.
    """

    api = gamma_api(ReplaySession(b'{"error": "something changed"}'))

    with pytest.raises(gamma.GammaError):
        gamma.fetch_market_by_slug(MADURO_SLUG, client=api)


def test_an_enveloped_response_is_still_read(gamma_api):
    rows = markets_fixture()[:1]
    api = gamma_api(ReplaySession(json.dumps({"data": rows}).encode()))

    market = gamma.fetch_market_by_slug(rows[0]["slug"], client=api)

    assert market["market_id"] == rows[0]["id"]


def test_collecting_the_same_markets_twice_makes_no_network_calls(api):
    first, _ = gamma.collect_markets(gamma.MarketQuery(limit=2), client=api)
    after_first = api.network_calls

    second, _ = gamma.collect_markets(gamma.MarketQuery(limit=2), client=api)

    assert after_first == 3
    assert api.network_calls == after_first
    assert first == second


def test_gamma_and_the_data_api_cannot_collide_in_the_shared_cache():
    """
    ResponseCache keys on endpoint and parameters, not on host. Two hosts
    serving the same endpoint path would share cache entries and one would be
    served the other's data - silently, and with a metadata file that says the
    right thing.

    If this ever fails, do not delete it. Give Gamma its own cache directory,
    or add the host to the cache key.
    """

    assert not (gamma.GAMMA_ENDPOINTS & gamma.DATA_API_ENDPOINTS)

    gamma_folders = {
        endpoint_folder(endpoint) for endpoint in gamma.GAMMA_ENDPOINTS
    }
    data_folders = {
        endpoint_folder(endpoint) for endpoint in gamma.DATA_API_ENDPOINTS
    }

    assert not (gamma_folders & data_folders)


def test_gamma_is_not_subject_to_the_scope_trap(api):
    """
    The unscoped-request guard exists for /trades and /activity, where a
    missing scope returns the wrong data silently (WS4 test 8). Gamma's list
    endpoints have no such trap, and inventing one here would stop the
    catalogue walk working at all.
    """

    from collectors.cache import SCOPE_REQUIRED_ENDPOINTS

    assert not (gamma.GAMMA_ENDPOINTS & set(SCOPE_REQUIRED_ENDPOINTS))

    markets, _ = gamma.collect_markets(gamma.MarketQuery(), client=api)
    assert markets


def test_saving_a_collection_writes_records_and_metadata(api, tmp_path):
    markets, metadata = gamma.collect_markets(
        gamma.MarketQuery(limit=2), client=api
    )

    records_path, metadata_path = gamma.save_collection(
        markets, metadata, output_dir=tmp_path / "gamma", name="markets"
    )

    assert json.loads(records_path.read_text()) == markets
    assert json.loads(metadata_path.read_text())["final_record_count"] == 5
