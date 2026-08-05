from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class User:
    """An account, in the one shape FediFetcher uses.

    Accounts reach us two ways: our own server lists them, or a post names
    them as its author or in its mentions. A mention is the thinner of the
    two and says nothing about how the account wants to be treated, so the
    three opt-out fields default to the answer an account that never asked
    would give.
    """

    acct: str
    url: str
    note: str = ""
    indexable: bool = True
    discoverable: bool = True
