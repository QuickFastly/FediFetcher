from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fedifetcher.api import client_for
from fedifetcher.context import add_context_urls, get_all_known_context_urls
from fedifetcher.posts import Post
from fedifetcher.servers import get_server_info
from fedifetcher.urls import parse_url, parse_user_url

if TYPE_CHECKING:
    from collections.abc import Container, Iterable

    from fedifetcher.api.mastodon import HomeServer
    from fedifetcher.config import Config
    from fedifetcher.http import HttpClient
    from fedifetcher.state import TimestampedSet
    from fedifetcher.store import State

logger = logging.getLogger("FediFetcher")

User = dict[str, Any]
"""An account, as the server gave it to us.

We read acct, url, note, indexable and discoverable. The last three are
how an account opts out of being backfilled, and any of them may be absent.
"""



def filter_known_users(
    users: Iterable[User], known_users: Container[str]
) -> list[User]:
    return [user for user in users if user['acct'] not in known_users]

def user_has_opted_out(user: User) -> bool:
    if 'note' in user and isinstance(user['note'], str) and (' nobot' in user['note'].lower() or '/tags/nobot' in user['note'].lower()):
        return True
    if 'indexable' in user and not user['indexable']:
        return True
    if 'discoverable' in user and not user['discoverable']:
        return True
    return False


def get_user_posts(
    user: User,
    target: TimestampedSet,
    server: str,
    *,
    http: HttpClient,
    state: State,
) -> list[Post] | None:
    if user_has_opted_out(user):
        logger.debug(f"User {user['acct']} has opted out of backfilling")
        return None
    parsed_url = parse_user_url(user['url'])

    if parsed_url is None:
        # We are adding it as 'known' anyway, because we won't be able to fix this.
        target.add(user['acct'])
        return None

    if(parsed_url[0] == server):
        logger.debug(f"{user['acct']} is a local user. Skip")
        target.add(user['acct'])
        return None

    post_server = get_server_info(parsed_url[0], state.seen_hosts, http=http)
    if post_server is None:
        logger.error(f'server {parsed_url[0]} not found for post')
        return None

    client = client_for(post_server, http)
    if client is None:
        return None

    return client.fetch_user_posts(parsed_url[1], user['url'])

def add_post_with_context(
    post: Post, home: HomeServer, *, http: HttpClient, config: Config, state: State
) -> bool:
    added = home.resolve(post.url)
    if added is True:
        state.seen_urls.add(post.url)
        if post.may_have_context and config.backfill_with_context:
            parsed = parse_url(post.url, state.parsed_urls, http)
            if parsed is None:
                return True
            known_context_urls = get_all_known_context_urls(home.server, [post], http=http, state=state)
            add_context_urls(home, known_context_urls, state=state)
        return True

    return False

def add_user_posts(
    home: HomeServer,
    followings: Iterable[User],
    target: TimestampedSet,
    *,
    http: HttpClient,
    config: Config,
    state: State,
) -> None:
    for user in followings:
        if user['acct'] not in state.all_known_users and not user['url'].startswith(f"https://{home.server}/"):
            posts = get_user_posts(user, target, home.server, http=http, state=state)

            if(posts is not None):
                count = 0
                failed = 0
                for post in posts:
                    if not post.is_boost and post.url not in state.seen_urls:
                        added = add_post_with_context(post, home, http=http, config=config, state=state)
                        if added is True:
                            state.seen_urls.add(post.url)
                            count += 1
                        else:
                            failed += 1
                logger.info(f"Added {count} posts for user {user['acct']} with {failed} errors")
                if failed == 0:
                    target.add(user['acct'])
                    state.all_known_users.add(user['acct'])
