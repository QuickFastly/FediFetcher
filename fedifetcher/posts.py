from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dateutil import parser

logger = logging.getLogger("FediFetcher")


@dataclass(frozen=True, slots=True)
class Post:
    """A post from any fediverse server, in the one shape FediFetcher uses.

    Servers disagree about almost everything here: what a post is called, how
    it says who may see it, and whether it admits to having replies. Each
    client translates its own server's posts into this shape as they arrive,
    so that nothing downstream has to ask who it is talking to.
    """

    url: str
    uri: str
    created_at: datetime
    is_public: bool
    reblog: Post | None = None
    in_reply_to_id: str | None = None
    reply_count: int | None = None

    @property
    def original(self) -> Post:
        """The post itself, or the one it boosts"""
        return self.reblog or self

    @property
    def is_boost(self) -> bool:
        return self.reblog is not None

    @property
    def may_have_context(self) -> bool:
        """Whether the server said anything suggesting this post has replies"""
        return self.in_reply_to_id is not None or self.reply_count is not None


def usable(posts: Iterable[Post | None]) -> list[Post]:
    """Keep the posts we could make sense of, and forget the rest"""
    return [post for post in posts if post is not None]


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
    """A post we cannot address or date is one we can do nothing with"""
    logger.debug(f"Skipping a {flavour} post without a URL or a date: {identifier}")
