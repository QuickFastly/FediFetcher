from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import urlparse

if TYPE_CHECKING:
    from fedifetcher.http import HttpClient

logger = logging.getLogger("FediFetcher")


class PostRef(NamedTuple):
    """A post identified by the server hosting it and its ID on that server"""

    server: str
    post_id: str


def host_of(url: str) -> str | None:
    """The server a URL points at, whatever the rest of it looks like.

    Which server it is decides how to read the rest, so this is the one thing
    that can be worked out without knowing what software is answering.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return parsed.netloc



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


def parse_pleroma_url(url: str, http: HttpClient) -> PostRef | None:
    """parse a Pleroma URL and return the server and ID"""
    match = re.match(r"https://(?P<server>[^/]+)/objects/(?P<toot_id>[^/]+)", url)
    if match is not None:
        server = match.group("server")
        redirect = http.get_redirect_url(url)
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



def parse_lemmy_url(url: str) -> PostRef | None:
    """parse a Lemmy URL and return the server, and ID"""
    match = re.match(
        r"https://(?P<server>[^/]+)/(?:comment|post)/(?P<toot_id>[^/]+)", url
    )
    if match is not None:
        return PostRef(match.group("server"), match.group("toot_id"))
    return None





def parse_url(
    url: str, parsed_urls: dict[str, PostRef | None], http: HttpClient
) -> PostRef | None:
    """Work out which server and post a URL refers to, remembering the answer"""
    if url in parsed_urls:
        return parsed_urls[url]

    match = (
        parse_mastodon_url(url)
        or parse_mastodon_uri(url)
        or parse_pleroma_url(url, http)
        or parse_pleroma_uri(url)
        or parse_lemmy_url(url)
        or parse_pixelfed_url(url)
        or parse_misskey_url(url)
        or parse_peertube_url(url)
    )
    if match is None:
        logger.error(f"Error parsing toot URL {url}")

    parsed_urls[url] = match
    return match
