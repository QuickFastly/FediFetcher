#!/usr/bin/env python3

import itertools
import logging
import sys
import uuid
from datetime import datetime, timedelta
from typing import NoReturn

from dateutil import parser

from fedifetcher import VERSION
from fedifetcher.api import client_for
from fedifetcher.api.mastodon import MastodonApi
from fedifetcher.config import Config, ConfigError
from fedifetcher.http import HttpClient, build_callback_url
from fedifetcher.servers import get_server_info
from fedifetcher.store import ROBOTS_MAX_AGE, LockedError, StateStore, lock
from fedifetcher.urls import (
    parse_url,
    parse_user_url,
)

logger = logging.getLogger("FediFetcher")

def get_notification_users(server, access_token, known_users, max_age, *, http):
    since = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(hours=max_age)
    notifications = get_paginated_mastodon(f"https://{server}/api/v1/notifications", since, headers={
        "Authorization": f"Bearer {access_token}",
    },
        http=http)
    notification_users = []
    for notification in notifications:
        notificationDate = parser.parse(notification['created_at'])
        if(notificationDate >= since and notification['account'] not in notification_users):
            notification_users.append(notification['account'])

    new_notification_users = filter_known_users(notification_users, known_users)

    logger.info(f"Found {len(notification_users)} users in notifications, {len(new_notification_users)} of which are new")

    return new_notification_users

def get_bookmarks(server, access_token, max, *, http):
    return get_paginated_mastodon(f"https://{server}/api/v1/bookmarks", max, {
        "Authorization": f"Bearer {access_token}",
    },
        http=http)

def get_favourites(server, access_token, max, *, http):
    return get_paginated_mastodon(f"https://{server}/api/v1/favourites", max, {
        "Authorization": f"Bearer {access_token}",
    },
        http=http)

def add_user_posts(server, access_token, followings, target, *, http, config, state):
    for user in followings:
        if user['acct'] not in state.all_known_users and not user['url'].startswith(f"https://{server}/"):
            posts = get_user_posts(user, target, server, http=http, state=state)

            if(posts is not None):
                count = 0
                failed = 0
                for post in posts:
                    if post.get('reblog') is None and post.get('renoteId') is None and post.get('url') is not None and post.get('url') not in state.seen_urls:
                        added = add_post_with_context(post, server, access_token, http=http, config=config, state=state)
                        if added is True:
                            state.seen_urls.add(post['url'])
                            count += 1
                        else:
                            failed += 1
                logger.info(f"Added {count} posts for user {user['acct']} with {failed} errors")
                if failed == 0:
                    target.add(user['acct'])
                    state.all_known_users.add(user['acct'])

def add_post_with_context(post, server, access_token, *, http, config, state):
    added = add_context_url(post['url'], server, access_token, http=http)
    if added is True:
        state.seen_urls.add(post['url'])
        if ('replies_count' in post or 'in_reply_to_id' in post) and config.backfill_with_context:
            parsed = parse_url(post['url'], state.parsed_urls, http)
            if parsed is None:
                return True
            known_context_urls = get_all_known_context_urls(server, [post], http=http, state=state)
            add_context_urls(server, access_token, known_context_urls, http=http, state=state)
        return True

    return False

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

def get_new_follow_requests(server, access_token, max, known_followings, *, http):
    """Get any new follow requests for the specified user, up to the max number provided"""

    follow_requests = get_paginated_mastodon(f"https://{server}/api/v1/follow_requests", max, {
        "Authorization": f"Bearer {access_token}",
    },
        http=http)

    # Remove any we already know about
    new_follow_requests = filter_known_users(follow_requests, known_followings)

    logger.info(f"Got {len(follow_requests)} follow_requests, {len(new_follow_requests)} of which are new")

    return new_follow_requests

def filter_known_users(users, known_users):
    return list(filter(
        lambda user: user['acct'] not in known_users,
        users
    ))

def get_new_followers(server, user_id, access_token, max, known_followers, *, http):
    """Get any new followings for the specified user, up to the max number provided"""
    followers = get_paginated_mastodon(f"https://{server}/api/v1/accounts/{user_id}/followers", max, {
        "Authorization": f"Bearer {access_token}",
    },
        http=http)

    # Remove any we already know about
    new_followers = filter_known_users(followers, known_followers)

    logger.info(f"Got {len(followers)} followers, {len(new_followers)} of which are new")

    return new_followers

def get_new_followings(server, user_id, access_token, max, known_followings, *, http):
    """Get any new followings for the specified user, up to the max number provided"""
    following = get_paginated_mastodon(f"https://{server}/api/v1/accounts/{user_id}/following", max, {
        "Authorization": f"Bearer {access_token}",
    },
        http=http)

    # Remove any we already know about
    new_followings = filter_known_users(following, known_followings)

    logger.info(f"Got {len(following)} followings, {len(new_followings)} of which are new")

    return new_followings


def get_timeline(server, access_token, max, *, http):
    """Get all post in the user's home timeline"""

    url = f"https://{server}/api/v1/timelines/home"

    try:

        response = get_toots(url, access_token, http=http)

        if response.status_code == 200:
            toots = response.json()
        else:
            report_mastodon_error(
                f"Error getting URL {url}",
                response.status_code,
                access_token,
                "read:statuses"
            )

        # Paginate as needed
        while len(toots) < max and 'next' in response.links:
            response = get_toots(response.links['next']['url'], access_token, http=http)
            toots = toots + response.json()
    except Exception as ex:
        logger.error(f"Error getting timeline toots: {ex}")
        raise

    logger.info(f"Found {len(toots)} toots in timeline")

    return toots

def get_toots(url, access_token, *, http):
    response = http.get( url, headers={
        "Authorization": f"Bearer {access_token}",
    })

    if response.status_code != 200:
        report_mastodon_error(
            f"Error getting URL {url}",
            response.status_code,
            access_token,
            "read:statuses"
        )

    return response

def get_active_user_ids(server, access_token, reply_interval_hours, *, http):
    """get all user IDs on the server that have posted a toot in the given
       time interval"""
    since = datetime.now() - timedelta(days=reply_interval_hours / 24 + 1)
    url = f"https://{server}/api/v1/admin/accounts"
    resp = http.get(url, headers={
        "Authorization": f"Bearer {access_token}",
    })
    if resp.status_code == 200:
        for user in resp.json():
            last_status_at = user["account"]["last_status_at"]
            if last_status_at is not None:
                last_active = datetime.strptime(last_status_at, "%Y-%m-%d")
                if last_active > since:
                    logger.info(f"Found active user: {user['username']}")
                    yield user["id"]
    else:
        report_mastodon_error(
            f"Error getting user IDs on server {server}",
            resp.status_code,
            access_token,
            "admin:read:accounts"
        )


def get_all_reply_toots(server, user_ids, access_token, reply_interval_hours, *, http, state):
    """get all replies to other users by the given users in the last day"""
    replies_since = datetime.now() - timedelta(hours=reply_interval_hours)
    reply_toots = list(
        itertools.chain.from_iterable(
            get_reply_toots(
                user_id, server, access_token, replies_since, http=http, state=state
            )
            for user_id in user_ids
        )
    )
    logger.info(f"Found {len(reply_toots)} reply toots")
    return reply_toots


def get_reply_toots(user_id, server, access_token, reply_since, *, http, state):
    """get replies by the user to other users since the given date"""
    url = f"https://{server}/api/v1/accounts/{user_id}/statuses?exclude_replies=false&limit=40"

    try:
        resp = http.get(url, headers={
            "Authorization": f"Bearer {access_token}",
        })
    except Exception as ex:
        logger.error(
            f"Error getting replies for user {user_id} on server {server}: {ex}"
        )
        return []

    if resp.status_code != 200:
        report_mastodon_error(
            f"Error getting replies for user {user_id} on server {server}",
            resp.status_code,
            access_token,
            "read:statuses"
        )

    toots = [
        toot
        for toot in resp.json()
        if toot["in_reply_to_id"] is not None
        and toot["url"] not in state.seen_urls
        and datetime.strptime(toot["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        > reply_since
    ]
    for toot in toots:
        logger.debug(f"Found reply toot: {toot['url']}")
    return toots


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

def add_context_urls(server, access_token, context_urls, *, http, state):
    """add the given toot URLs to the server"""
    count = 0
    failed = 0
    for url in context_urls:
        if url not in state.seen_urls:
            added = add_context_url(url, server, access_token, http=http)
            if added is True:
                state.seen_urls.add(url)
                count += 1
            else:
                failed += 1

    logger.info(f"Added {count} new context toots (with {failed} failures)")


def add_context_url(url, server, access_token, *, http):
    """add the given toot URL to the server"""
    search_url = f"https://{server}/api/v2/search?q={url}&resolve=true&limit=1"

    try:
        resp = http.get(search_url, headers={
            "Authorization": f"Bearer {access_token}",
        })
    except Exception as ex:
        logger.error(
            f"Error adding url {search_url} to server {server}. Exception: {ex}"
        )
        return False

    if resp.status_code == 200:
        logger.debug(f"Added context url {url}")
        return True
    elif resp.status_code == 403:
        logger.error(
            f"Error adding url {search_url} to server {server}. Status code: {resp.status_code}. "
            "Make sure you have the read:search scope enabled for your access token."
        )
        return False
    else:
        logger.error(
            f"Error adding url {search_url} to server {server}. Status code: {resp.status_code}"
        )
        return False

def get_paginated_mastodon(url, max, headers = None, timeout = None, max_tries = 5, *, http):
    """Make a paginated request to mastodon"""
    headers = headers or {}
    if(isinstance(max, int)):
        furl = f"{url}?limit={max}"
    else:
        furl = url

    response = http.get(furl, headers, timeout, max_tries)

    if response.status_code != 200:
        report_mastodon_error(
            f"Error getting URL {url}",
            response.status_code,
            headers.get('Authorization', '').replace("Bearer ", ""),
        )

    result = response.json()

    if(isinstance(max, int)):
        while len(result) < max and 'next' in response.links:
            response = http.get(response.links['next']['url'], headers, timeout, max_tries)
            if response.status_code != 200:
                raise Exception(
                    f"Error getting URL {response.url}. \
                        Status code: {response.status_code}"
                )
            response_json = response.json()
            if isinstance(response_json, list):
                result += response_json
            else:
                break
    else:
        while result and parser.parse(result[-1]['created_at']) >= max \
            and 'next' in response.links:
            response = http.get(response.links['next']['url'], headers, timeout, max_tries)
            if response.status_code != 200:
                raise Exception(
                    f"Error getting URL {response.url}. \
                        Status code: {response.status_code}"
                )
            response_json = response.json()
            if isinstance(response_json, list):
                result += response_json
            else:
                break
    return result

def get_user_lists(server, token, *, http):
    return get_paginated_mastodon(f"https://{server}/api/v1/lists", 99, {
        "Authorization": f"Bearer {token}",
    },
        http=http)

def get_list_timeline(server, list, token, max, *, http):
    """Get all post in the user's home timeline"""

    url = f"https://{server}/api/v1/timelines/list/{list['id']}"

    posts = get_paginated_mastodon(url, max, {
        "Authorization": f"Bearer {token}",
    },
        http=http)

    logger.info(f"Found {len(posts)} toots in list {list['title']}")

    return posts

def get_list_users(server, list, token, max, *, http):
    url = f"https://{server}/api/v1/lists/{list['id']}/accounts"
    accounts = get_paginated_mastodon(url, max, {
        "Authorization": f"Bearer {token}",
    },
        http=http)
    logger.info(f"Found {len(accounts)} accounts in list {list['title']}")
    return accounts

def fetch_timeline_context(timeline_posts, token, *, http, config, state):
    known_context_urls = get_all_known_context_urls(config.server, timeline_posts, http=http, state=state)
    add_context_urls(config.server, token, known_context_urls, http=http, state=state)

    # Backfill any post authors, and any mentioned users
    if config.backfill_mentioned_users:
        mentioned_users = []
        cut_off = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(minutes=60)
        for toot in timeline_posts:
            these_users = []
            toot_created_at = parser.parse(toot['created_at'])
            if len(mentioned_users) < 10 or (toot_created_at > cut_off and len(mentioned_users) < 30):
                these_users.append(toot['account'])
                if(len(toot['mentions'])):
                    these_users += toot['mentions']
                if(toot['reblog'] is not None):
                    these_users.append(toot['reblog']['account'])
                    if(len(toot['reblog']['mentions'])):
                        these_users += toot['reblog']['mentions']
            for user in these_users:
                if user not in mentioned_users and user['acct'] not in state.all_known_users:
                    mentioned_users.append(user)

        add_user_posts(config.server, token, filter_known_users(mentioned_users, state.all_known_users), state.recently_checked_users, http=http, config=config, state=state)

def report_mastodon_error(error_message, error_code, access_token, required_scope = '') -> NoReturn:
    subline = ""
    match error_code:
        case 401:
            subline = "\nIt looks like your access token is incorrect. Consider generating a new access token, and/or ensure you have copy and pasted the whole token correctly."
        case 403:
            if(required_scope != ""):
                subline = f"\nAdd the {required_scope} scope to your access token, and regenerate the token."
            else:
                subline = "\nMake sure you have enabled the required scope(s) for your token."

    raise Exception(
        f"{error_message} with token {access_token[:+5]}{'*' * (len(access_token) - 10)}{access_token[-5:]}. Status code: {error_code} "
        f"{subline}"
    )

if __name__ == "__main__":
    start = datetime.now()

    try:
        config = Config.load()
    except ConfigError as ex:
        logging.basicConfig()
        logger.critical(str(ex))
        sys.exit(1)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.basicConfig(
        format=f"{config.log_format}",
        datefmt="%Y-%m-%d %H:%M:%S %Z",
        level=config.log_level.upper(),
    )
    logger.setLevel(config.log_level.upper())

    logger.info(f"Starting FediFetcher v{VERSION}")

    http = HttpClient(config)
    home_server = MastodonApi(config.server, http)
    store = StateStore(config)

    runId = uuid.uuid4()

    def ping(url, **params):
        if url is None or url == '':
            return
        try:
            http.get(build_callback_url(url, {"rid": runId, **params}), ignore_robots_txt = True)
        except Exception as ex:
            logger.error(f"Error getting callback url: {ex}")

    def elapsed_ms():
        return int((datetime.now() - start).total_seconds() * 1000)

    ping(config.on_start)

    try:
        with lock(config), store.session() as state:
            # Delete any old robots.txt files so we can re-download them
            http.robots.discard_stale_files(ROBOTS_MAX_AGE)

            for token in config.access_tokens:

                if config.from_lists:
                    """Pull replies from lists"""
                    lists = get_user_lists(config.server, token, http=http)
                    logger.info(f"Getting context for {len(lists)} lists")
                    for user_list in lists:
                        # Fill context from list
                        if config.max_list_length > 0:
                            timeline_toots = get_list_timeline(config.server, user_list, token, config.max_list_length, http=http)
                            fetch_timeline_context(timeline_toots, token, http=http, config=config, state=state)

                        # Backfill profiles from list
                        if config.max_list_accounts:
                            accounts = get_list_users(config.server, user_list, token, config.max_list_accounts, http=http)
                            add_user_posts(config.server, token, accounts, state.recently_checked_users, http=http, config=config, state=state)

                if config.reply_interval_in_hours > 0:
                    """pull the context toots of toots user replied to, from their
                    original server, and add them to the local server."""
                    user_ids = get_active_user_ids(config.server, token, config.reply_interval_in_hours, http=http)
                    reply_toots = get_all_reply_toots(
                        config.server, user_ids, token, config.reply_interval_in_hours,
                        http=http, state=state,
                    )
                    known_context_urls = get_all_known_context_urls(config.server, reply_toots, http=http, state=state)
                    state.seen_urls.update(known_context_urls)
                    replied_toot_ids = get_all_replied_toot_server_ids(
                        config.server, reply_toots, http=http, state=state
                    )
                    context_urls = get_all_context_urls(config.server, replied_toot_ids, http=http, state=state)
                    add_context_urls(config.server, token, context_urls, http=http, state=state)

                if config.home_timeline_length > 0:
                    """Do the same with any toots on the key owner's home timeline """
                    logger.info("Getting context for home timeline")
                    timeline_toots = get_timeline(config.server, token, config.home_timeline_length, http=http)
                    fetch_timeline_context(timeline_toots, token, http=http, config=config, state=state)

                if config.max_followings > 0:
                    logger.info(f"Getting posts from last {config.max_followings} followings")
                    user_id = home_server.user_id(config.user, token)
                    followings = get_new_followings(config.server, user_id, token, config.max_followings, state.all_known_users, http=http)
                    add_user_posts(config.server, token, followings, state.known_followings, http=http, config=config, state=state)

                if config.max_followers > 0:
                    logger.info(f"Getting posts from last {config.max_followers} followers")
                    user_id = home_server.user_id(config.user, token)
                    followers = get_new_followers(config.server, user_id, token, config.max_followers, state.all_known_users, http=http)
                    add_user_posts(config.server, token, followers, state.recently_checked_users, http=http, config=config, state=state)

                if config.max_follow_requests > 0:
                    logger.info(f"Getting posts from last {config.max_follow_requests} follow requests")
                    follow_requests = get_new_follow_requests(config.server, token, config.max_follow_requests, state.all_known_users, http=http)
                    add_user_posts(config.server, token, follow_requests, state.recently_checked_users, http=http, config=config, state=state)

                if config.from_notifications > 0:
                    logger.info(f"Getting notifications for last {config.from_notifications} hours")
                    notification_users = get_notification_users(config.server, token, state.all_known_users, config.from_notifications, http=http)
                    add_user_posts(config.server, token, notification_users, state.recently_checked_users, http=http, config=config, state=state)

                if config.max_bookmarks > 0:
                    logger.info(f"Pulling replies to the last {config.max_bookmarks} bookmarks")
                    bookmarks = get_bookmarks(config.server, token, config.max_bookmarks, http=http)
                    known_context_urls = get_all_known_context_urls(config.server, bookmarks, http=http, state=state)
                    add_context_urls(config.server, token, known_context_urls, http=http, state=state)

                if config.max_favourites > 0:
                    logger.info(f"Pulling replies to the last {config.max_favourites} favourites")
                    favourites = get_favourites(config.server, token, config.max_favourites, http=http)
                    known_context_urls = get_all_known_context_urls(config.server, favourites, http=http, state=state)
                    add_context_urls(config.server, token, known_context_urls, http=http, state=state)

    except LockedError as ex:
        logger.critical(str(ex))
        ping(config.on_fail, ping=elapsed_ms(), msg=str(ex))
        sys.exit(1)

    except Exception as ex:
        logger.error(f"Job failed after {datetime.now() - start}.")
        ping(config.on_fail, ping=elapsed_ms(), msg=str(ex))
        raise

    success_message = f"Processing finished in {datetime.now() - start}."
    ping(config.on_done, ping=elapsed_ms(), msg=success_message)
    logger.info(success_message)
