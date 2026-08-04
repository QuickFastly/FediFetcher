from __future__ import annotations

import logging

from fedifetcher.api import client_for
from fedifetcher.context import add_context_urls, get_all_known_context_urls
from fedifetcher.servers import get_server_info
from fedifetcher.urls import parse_url, parse_user_url

logger = logging.getLogger("FediFetcher")


def filter_known_users(users, known_users):
    return list(filter(
        lambda user: user['acct'] not in known_users,
        users
    ))

def user_has_opted_out(user):
    if 'note' in user and isinstance(user['note'], str) and (' nobot' in user['note'].lower() or '/tags/nobot' in user['note'].lower()):
        return True
    if 'indexable' in user and not user['indexable']:
        return True
    if 'discoverable' in user and not user['discoverable']:
        return True
    return False


def get_user_posts(user, target, server, *, http, state):
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

def add_post_with_context(post, home, *, http, config, state):
    added = home.resolve(post['url'])
    if added is True:
        state.seen_urls.add(post['url'])
        if ('replies_count' in post or 'in_reply_to_id' in post) and config.backfill_with_context:
            parsed = parse_url(post['url'], state.parsed_urls, http)
            if parsed is None:
                return True
            known_context_urls = get_all_known_context_urls(home.server, [post], http=http, state=state)
            add_context_urls(home, known_context_urls, state=state)
        return True

    return False

def add_user_posts(home, followings, target, *, http, config, state):
    for user in followings:
        if user['acct'] not in state.all_known_users and not user['url'].startswith(f"https://{home.server}/"):
            posts = get_user_posts(user, target, home.server, http=http, state=state)

            if(posts is not None):
                count = 0
                failed = 0
                for post in posts:
                    if post.get('reblog') is None and post.get('renoteId') is None and post.get('url') is not None and post.get('url') not in state.seen_urls:
                        added = add_post_with_context(post, home, http=http, config=config, state=state)
                        if added is True:
                            state.seen_urls.add(post['url'])
                            count += 1
                        else:
                            failed += 1
                logger.info(f"Added {count} posts for user {user['acct']} with {failed} errors")
                if failed == 0:
                    target.add(user['acct'])
                else:
                    # Some posts could not be fetched, so the account isn't done: record
                    # it among the users we expire, so that we try again after a while
                    # rather than on every single run.
                    state.recently_checked_users.add(user['acct'])
                state.all_known_users.add(user['acct'])
