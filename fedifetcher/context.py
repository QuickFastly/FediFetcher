from __future__ import annotations

import itertools
import logging

from fedifetcher.api import client_for
from fedifetcher.servers import get_server_info
from fedifetcher.urls import parse_url

logger = logging.getLogger("FediFetcher")


def toot_context_can_be_fetched(toot):
    fetchable = toot["visibility"] in ["public", "unlisted"]
    if not fetchable:
        logger.debug(f"Cannot fetch context of private toot {toot['uri']}")
    return fetchable


def get_all_known_context_urls(server, reply_toots, *, http, state):
    """get the context toots of the given toots from their original server"""
    known_context_urls = set()

    for toot in reply_toots:
        if toot_has_parseable_url(toot, http=http, state=state):
            url = toot["url"] if toot["reblog"] is None else toot["reblog"]["url"]
            parsed_url = parse_url(url, state.parsed_urls, http)
            if toot_context_can_be_fetched(toot) and state.recently_checked_context.should_fetch(toot['uri'], toot['created_at']):
                state.recently_checked_context.mark_fetched(toot['uri'], toot['created_at'])
                context = get_toot_context(parsed_url[0], parsed_url[1], url, http=http, state=state)
                if context is not None:
                    for item in context:
                        known_context_urls.add(item)
                else:
                    logger.error(f"Error getting context for toot {url}")

    known_context_urls = set(filter(lambda url: not url.startswith(f"https://{server}/"), known_context_urls))
    logger.info(f"Found {len(known_context_urls)} known context toots")

    return known_context_urls


def toot_has_parseable_url(toot, *, http, state):
    parsed = parse_url(toot["url"] if toot["reblog"] is None else toot["reblog"]["url"], state.parsed_urls, http)
    if(parsed is None) :
        return False
    return True


def get_all_replied_toot_server_ids(server, reply_toots, *, http, state):
    """get the server and ID of the toots the given toots replied to"""
    return filter(
        lambda x: x is not None,
        (
            get_replied_toot_server_id(server, toot, http=http, state=state)
            for toot in reply_toots
        ),
    )


def get_replied_toot_server_id(server, toot, *, http, state):
    """get the server and ID of the toot the given toot replied to"""
    in_reply_to_id = toot["in_reply_to_id"]
    in_reply_to_account_id = toot["in_reply_to_account_id"]
    mentions = [
        mention
        for mention in toot["mentions"]
        if mention["id"] == in_reply_to_account_id
    ]
    if len(mentions) == 0:
        return None

    mention = mentions[0]

    o_url = f"https://{server}/@{mention['acct']}/{in_reply_to_id}"
    if o_url in state.replied_toot_server_ids:
        return state.replied_toot_server_ids[o_url]

    url = http.get_redirect_url(o_url)

    if url is None:
        return None

    match = parse_url(url, state.parsed_urls, http)
    if match is not None:
        state.replied_toot_server_ids[o_url] = (url, match)
        return (url, match)

    logger.error(f"Error parsing toot URL {url}")
    state.replied_toot_server_ids[o_url] = None
    return None

def get_all_context_urls(server, replied_toot_ids, *, http, state):
    """get the URLs of the context toots of the given toots"""
    return filter(
        lambda url: not url.startswith(f"https://{server}/"),
        itertools.chain.from_iterable(
            get_toot_context(server, toot_id, url, http=http, state=state)
            for (url, (server, toot_id)) in replied_toot_ids
        ),
    )


def get_toot_context(server, toot_id, toot_url, *, http, state):
    """get the URLs of the context toots of the given toot"""

    post_server = get_server_info(server, state.seen_hosts, http=http)
    if post_server is None:
        logger.error(f'server {server} not found for post')
        return []

    client = client_for(post_server, http)
    if client is None:
        return []

    return client.fetch_context_urls(toot_id, toot_url)

def add_context_urls(home, context_urls, *, state):
    """add the given toot URLs to the server"""
    count = 0
    failed = 0
    for url in context_urls:
        if url not in state.seen_urls:
            added = home.resolve(url)
            if added is True:
                state.seen_urls.add(url)
                count += 1
            else:
                failed += 1

    logger.info(f"Added {count} new context toots (with {failed} failures)")
