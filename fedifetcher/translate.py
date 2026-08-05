"""What every client needs to turn what a server sent into a shape we use.

The shapes themselves are in `posts` and `users`; the `to_post` and `to_user`
that build them live with the client that knows the dialect. These are the
three things all of those translations have in common.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any, TypeVar

from dateutil import parser

logger = logging.getLogger("FediFetcher")

T = TypeVar("T")


def first_name_in(patterns: Iterable[re.Pattern[str]], url: str) -> str | None:
    """The username the first of these patterns finds in a URL, if any"""
    for pattern in patterns:
        match = pattern.match(url)
        if match is not None:
            return match.group("username")
    return None


def usable(things: Iterable[T | None]) -> list[T]:
    """Keep what we could make sense of, and forget the rest"""
    return [thing for thing in things if thing is not None]


def parse_date(value: Any) -> datetime | None:
    """Read whatever a server calls a date, or admit we could not"""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return parser.parse(value)
    except (ValueError, OverflowError):
        return None


def unusable(flavour: str, identifier: Any) -> None:
    """Something we cannot address or date is something we can do nothing with"""
    logger.debug(f"Skipping a {flavour} post without a URL or a date: {identifier}")
