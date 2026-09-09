"""
The ethics protocol, as code (processing/anonymise.py).

This module is what stands between a raw API response and a public
repository. It was the least-tested thing in the project, which is the wrong
module to be casual about: if it silently stops removing a field, nothing
fails - data just quietly gets published.
"""

import pytest

from processing.anonymise import (
    PROFILE_FIELDS,
    anonymise_record,
    anonymise_records,
    find_identifying_fields,
    hash_wallet,
)

# A trade as the API actually returns it, profile fields and all.
RAW_TRADE = {
    "proxyWallet": "0xcbec73f262653060e44402cbb5cecfc44eeeacb3",
    "side": "BUY",
    "size": 6.12,
    "price": 0.49,
    "timestamp": 1787241322,
    "conditionId": "0xffacbf53",
    "transactionHash": "0x619b5c5d",
    "name": "Elias.Thornwell",
    "pseudonym": "Arctic-Kickoff",
    "bio": "Mission failed successfully",
    "profileImage": "https://polymarket-upload.s3.amazonaws.com/profile.png",
    "profileImageOptimized": "",
}


# ===========================================================================
# What must not survive
# ===========================================================================

@pytest.mark.parametrize("field", PROFILE_FIELDS)
def test_every_profile_field_is_removed(field):
    assert field not in anonymise_record(RAW_TRADE)


def test_the_wallet_is_replaced_not_removed():
    """Traders still need telling apart - we just stop naming them."""

    clean = anonymise_record(RAW_TRADE)

    assert "proxyWallet" in clean
    assert clean["proxyWallet"] != RAW_TRADE["proxyWallet"]


def test_the_trade_itself_is_untouched():
    """Anonymising must not cost us the data the analysis runs on."""

    clean = anonymise_record(RAW_TRADE)

    for field in ("side", "size", "price", "timestamp", "conditionId",
                  "transactionHash"):
        assert clean[field] == RAW_TRADE[field]


def test_the_original_record_is_not_modified():
    """The caller still holds the raw response afterwards - it is evidence."""

    before = dict(RAW_TRADE)
    anonymise_record(RAW_TRADE)

    assert RAW_TRADE == before


# ===========================================================================
# The hash
# ===========================================================================

def test_the_same_wallet_always_gets_the_same_fake_address():
    """Without this a trader could not be followed between markets or files."""

    assert hash_wallet("0xABC") == hash_wallet("0xABC")


def test_case_does_not_change_the_answer():
    """0xABC and 0xabc are one address, and must not become two traders."""

    assert hash_wallet("0xABC123") == hash_wallet("0xabc123")


def test_different_wallets_get_different_addresses():
    assert hash_wallet("0xaaa") != hash_wallet("0xbbb")


def test_the_fake_address_looks_like_an_address():
    """So nothing downstream has to care which kind it is holding."""

    fake = hash_wallet("0xcbec73f262653060e44402cbb5cecfc44eeeacb3")

    assert fake.startswith("0x")
    assert len(fake) == 42
    assert all(c in "0123456789abcdef" for c in fake[2:])


def test_the_real_address_cannot_be_read_back_out():
    real = "0xcbec73f262653060e44402cbb5cecfc44eeeacb3"

    assert real[2:] not in hash_wallet(real)


def test_an_empty_wallet_stays_empty_rather_than_hashing_to_something():
    """A missing address must not become a plausible-looking fake trader."""

    assert hash_wallet("") == ""
    assert hash_wallet(None) is None


# ===========================================================================
# The check that guards the repository
# ===========================================================================

def test_identifying_fields_are_counted_before_anonymising():
    found = find_identifying_fields([RAW_TRADE, RAW_TRADE])

    assert found == {"name": 2, "pseudonym": 2, "bio": 2, "profileImage": 2}


def test_nothing_is_found_after_anonymising():
    assert find_identifying_fields(anonymise_records([RAW_TRADE])) == {}


def test_an_empty_string_does_not_count_as_identifying():
    """The API sends "" for traders with no display name. That is not a name."""

    blank = dict(RAW_TRADE, name="", pseudonym="", bio="", profileImage="")

    assert find_identifying_fields([blank]) == {}


def test_a_list_of_records_is_handled_as_one():
    clean = anonymise_records([RAW_TRADE, dict(RAW_TRADE, name="Someone Else")])

    assert len(clean) == 2
    assert all("name" not in row for row in clean)
    # Same wallet in both, so the same fake address in both.
    assert clean[0]["proxyWallet"] == clean[1]["proxyWallet"]


def test_anonymising_twice_changes_the_answer():
    """Documented, and tested so nobody 'fixes' it by accident.

    Re-hashing an already-hashed address gives a different value, which would
    break joins against a file anonymised once. Anonymise at one point only.
    """

    once = anonymise_record(RAW_TRADE)
    twice = anonymise_record(once)

    assert twice["proxyWallet"] != once["proxyWallet"]
