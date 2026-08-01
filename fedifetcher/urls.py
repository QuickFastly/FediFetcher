from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Final, NamedTuple

from fedifetcher.http import get_redirect_url

logger = logging.getLogger("FediFetcher")


class PostRef(NamedTuple):
    """A post identified by the server hosting it and its ID on that server"""

    server: str
    post_id: str


class UserRef(NamedTuple):
    """An account identified by the server hosting it and its name on that server"""

    server: str
    username: str


def parse_mastodon_profile_url(url: str) -> UserRef | None:
    """parse a Mastodon Profile URL and return the server and username"""
    match = re.match(
        r"https://(?P<server>[^/]+)/@(?P<username>[^/]+)", url
    )
    if match is not None:
        return UserRef(match.group("server"), match.group("username"))
    return None


def parse_mastodon_url(url: str) -> PostRef | None:
    """parse a Mastodon URL and return the server and ID"""
    match = re.match(
        r"https://(?P<server>[^/]+)/@(?P<username>[^/]+)/(?P<toot_id>[^/]+)", url
    )
    if match is not None:
        return PostRef(match.group("server"), match.group("toot_id"))
    return None


def parse_mastodon_uri(uri: str) -> PostRef | None:
    """parse a Mastodon URI and return the server and ID"""
    match = re.match(
        r"https://(?P<server>[^/]+)/users/(?P<username>[^/]+)/statuses/(?P<toot_id>[^/]+)", uri
    )
    if match is not None:
        return PostRef(match.group("server"), match.group("toot_id"))
    return None


def parse_pleroma_url(url: str) -> PostRef | None:
    """parse a Pleroma URL and return the server and ID"""
    match = re.match(r"https://(?P<server>[^/]+)/objects/(?P<toot_id>[^/]+)", url)
    if match is not None:
        server = match.group("server")
        redirect = get_redirect_url(url)
        if redirect is None:
            return None

        match = re.match(r"/notice/(?P<toot_id>[^/]+)", redirect)
        if match is not None:
            return PostRef(server, match.group("toot_id"))
        return None
    return None


def parse_pleroma_uri(uri: str) -> PostRef | None:
    """parse a Pleroma URL and return the server and ID"""
    match = re.match(r"https://(?P<server>[^/]+)/notice/(?P<toot_id>[^/]+)", uri)
    if match is not None:
        return PostRef(match.group("server"), match.group("toot_id"))
    return None


def parse_pleroma_profile_url(url: str) -> UserRef | None:
    """parse a Pleroma Profile URL and return the server and username"""
    match = re.match(r"https://(?P<server>[^/]+)/users/(?P<username>[^/]+)", url)
    if match is not None:
        return UserRef(match.group("server"), match.group("username"))
    return None


def parse_pixelfed_url(url: str) -> PostRef | None:
    """parse a Pixelfed URL and return the server and ID"""
    match = re.match(
        r"https://(?P<server>[^/]+)/p/(?P<username>[^/]+)/(?P<toot_id>[^/]+)", url
    )
    if match is not None:
        return PostRef(match.group("server"), match.group("toot_id"))
    return None


def parse_misskey_url(url: str) -> PostRef | None:
    """parse a Misskey URL and return the server and ID"""
    match = re.match(
        r"https://(?P<server>[^/]+)/notes/(?P<toot_id>[^/]+)", url
    )
    if match is not None:
        return PostRef(match.group("server"), match.group("toot_id"))
    return None


def parse_peertube_url(url: str) -> PostRef | None:
    """parse a PeerTube URL and return the server and ID"""
    match = re.match(
        r"https://(?P<server>[^/]+)/videos/watch/(?P<toot_id>[^/]+)", url
    )
    if match is not None:
        return PostRef(match.group("server"), match.group("toot_id"))
    return None


def parse_pixelfed_profile_url(url: str) -> UserRef | None:
    """parse a Pixelfed Profile URL and return the server and username"""
    match = re.match(r"https://(?P<server>[^/]+)/(?P<username>[^/]+)", url)
    if match is not None:
        return UserRef(match.group("server"), match.group("username"))
    return None


def parse_lemmy_url(url: str) -> PostRef | None:
    """parse a Lemmy URL and return the server, and ID"""
    match = re.match(
        r"https://(?P<server>[^/]+)/(?:comment|post)/(?P<toot_id>[^/]+)", url
    )
    if match is not None:
        return PostRef(match.group("server"), match.group("toot_id"))
    return None


def parse_lemmy_profile_url(url: str) -> UserRef | None:
    """parse a Lemmy Profile URL and return the server and username"""
    match = re.match(r"https://(?P<server>[^/]+)/(?:u|c)/(?P<username>[^/]+)", url)
    if match is not None:
        return UserRef(match.group("server"), match.group("username"))
    return None


def parse_peertube_profile_url(url: str) -> UserRef | None:
    match = re.match(r"https://(?P<server>[^/]+)/accounts/(?P<username>[^/]+)", url)
    if match is not None:
        return UserRef(match.group("server"), match.group("username"))
    return None


_POST_PARSERS: Final[tuple[Callable[[str], PostRef | None], ...]] = (
    parse_mastodon_url,
    parse_mastodon_uri,
    parse_pleroma_url,
    parse_pleroma_uri,
    parse_lemmy_url,
    parse_pixelfed_url,
    parse_misskey_url,
    parse_peertube_url,
)

# Pixelfed profile paths do not use a subdirectory, so its matcher accepts any
# https://host/segment and has to stay last.
_PROFILE_PARSERS: Final[tuple[Callable[[str], UserRef | None], ...]] = (
    parse_mastodon_profile_url,
    parse_pleroma_profile_url,
    parse_lemmy_profile_url,
    parse_peertube_profile_url,
    parse_pixelfed_profile_url,
)


def parse_user_url(url: str) -> UserRef | None:
    for parser in _PROFILE_PARSERS:
        match = parser(url)
        if match is not None:
            return match

    logger.error(f"Error parsing Profile URL {url}")

    return None


def parse_url(url: str, parsed_urls: dict[str, PostRef | None]) -> PostRef | None:
    if url not in parsed_urls:
        for parser in _POST_PARSERS:
            match = parser(url)
            if match is not None:
                parsed_urls[url] = match
                break

    if url not in parsed_urls:
        logger.error(f"Error parsing toot URL {url}")
        parsed_urls[url] = None

    return parsed_urls[url]
