"""
Strip identifying data out of Polymarket records.

The API returns name, pseudonym, bio and profileImage alongside every trade.
Our ethics protocol says those are never published and wallet identifiers are
hashed, so anything leaving data/raw/ - a committed file, a figure, a table in
the report - comes through here first. Raw responses keep the original fields,
because that is the evidence; nothing downstream does.

    from processing.anonymise import anonymise_records
    safe = anonymise_records(trades)

Anonymise once. Running a record through twice re-hashes the hash and gives a
different answer, which would break joins against a file anonymised once.
"""

import hashlib

# Returned by the API, never published.
PROFILE_FIELDS = (
    "name",
    "pseudonym",
    "bio",
    "profileImage",
    "profileImageOptimized",
)

# Hashed rather than dropped: the analysis needs to tell traders apart, it just
# does not need to know who they are.
WALLET_FIELDS = ("proxyWallet", "user", "wallet")


def hash_wallet(address):
    """0xcbec73f2... -> 0x4f2a91c0...

    Deterministic, so one trader keeps one fake address across every file and
    every run and can still be followed between markets. The 0x-plus-40-hex
    shape is kept so downstream code cannot tell the difference.
    """

    if not address:
        return address

    digest = hashlib.sha256(str(address).lower().encode("utf-8")).hexdigest()
    return "0x" + digest[:40]


def anonymise_record(record):
    """One record, profile fields removed and wallets hashed. Copies, not edits."""

    clean = {k: v for k, v in record.items() if k not in PROFILE_FIELDS}

    for field in WALLET_FIELDS:
        if field in clean:
            clean[field] = hash_wallet(clean[field])

    return clean


def anonymise_records(records):
    return [anonymise_record(row) for row in records]


def find_identifying_fields(records):
    """Which profile fields are actually populated here.

        >>> find_identifying_fields(trades)
        {'name': 11098, 'pseudonym': 11041, 'bio': 968}

    Empty means safe to publish. Run this over anything heading into the
    repository, a figure or the report.
    """

    counts = {}

    for row in records:
        for field in PROFILE_FIELDS:
            if row.get(field):
                counts[field] = counts.get(field, 0) + 1

    return counts
