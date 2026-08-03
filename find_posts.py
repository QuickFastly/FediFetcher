#!/usr/bin/env python3

import itertools
import logging
import sys
import uuid
from datetime import datetime, timedelta

from dateutil import parser

from fedifetcher import VERSION
from fedifetcher.api import client_for
from fedifetcher.api.mastodon import HomeServer
from fedifetcher.config import Config, ConfigError
from fedifetcher.http import HttpClient, build_callback_url
from fedifetcher.servers import get_server_info
from fedifetcher.store import ROBOTS_MAX_AGE, LockedError, StateStore, lock
from fedifetcher.urls import (
    parse_url,
    parse_user_url,
)

logger = logging.getLogger("FediFetcher")

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
                    state.all_known_users.add(user['acct'])

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

def filter_known_users(users, known_users):
    return list(filter(
        lambda user: user['acct'] not in known_users,
        users
    ))

def get_all_reply_toots(home, user_ids, reply_interval_hours, *, state):
    """get all replies to other users by the given users in the last day"""
    replies_since = datetime.now() - timedelta(hours=reply_interval_hours)
    reply_toots = list(
        itertools.chain.from_iterable(
            get_reply_toots(user_id, home, replies_since, state=state)
            for user_id in user_ids
        )
    )
    logger.info(f"Found {len(reply_toots)} reply toots")
    return reply_toots


def get_reply_toots(user_id, home, reply_since, *, state):
    """get replies by the user to other users since the given date"""
    try:
        statuses = home.account_statuses(user_id)
    except Exception as ex:
        logger.error(
            f"Error getting replies for user {user_id} on server {home.server}: {ex}"
        )
        return []

    toots = [
        toot
        for toot in statuses
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


def fetch_timeline_context(timeline_posts, home, *, http, config, state):
    known_context_urls = get_all_known_context_urls(config.server, timeline_posts, http=http, state=state)
    add_context_urls(home, known_context_urls, state=state)

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

        add_user_posts(home, filter_known_users(mentioned_users, state.all_known_users), state.recently_checked_users, http=http, config=config, state=state)

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
                home = HomeServer(config.server, token, http)

                if config.from_lists:
                    """Pull replies from lists"""
                    lists = home.lists()
                    logger.info(f"Getting context for {len(lists)} lists")
                    for user_list in lists:
                        # Fill context from list
                        if config.max_list_length > 0:
                            timeline_toots = home.list_timeline(user_list['id'], config.max_list_length)
                            logger.info(f"Found {len(timeline_toots)} toots in list {user_list['title']}")
                            fetch_timeline_context(timeline_toots, home, http=http, config=config, state=state)

                        # Backfill profiles from list
                        if config.max_list_accounts:
                            accounts = home.list_accounts(user_list['id'], config.max_list_accounts)
                            logger.info(f"Found {len(accounts)} accounts in list {user_list['title']}")
                            add_user_posts(home, accounts, state.recently_checked_users, http=http, config=config, state=state)

                if config.reply_interval_in_hours > 0:
                    """pull the context toots of toots user replied to, from their
                    original server, and add them to the local server."""
                    user_ids = home.active_user_ids(config.reply_interval_in_hours)
                    reply_toots = get_all_reply_toots(
                        home, user_ids, config.reply_interval_in_hours, state=state
                    )
                    known_context_urls = get_all_known_context_urls(config.server, reply_toots, http=http, state=state)
                    state.seen_urls.update(known_context_urls)
                    replied_toot_ids = get_all_replied_toot_server_ids(
                        config.server, reply_toots, http=http, state=state
                    )
                    context_urls = get_all_context_urls(config.server, replied_toot_ids, http=http, state=state)
                    add_context_urls(home, context_urls, state=state)

                if config.home_timeline_length > 0:
                    """Do the same with any toots on the key owner's home timeline """
                    logger.info("Getting context for home timeline")
                    timeline_toots = home.timeline(config.home_timeline_length)
                    fetch_timeline_context(timeline_toots, home, http=http, config=config, state=state)

                if config.max_followings > 0:
                    logger.info(f"Getting posts from last {config.max_followings} followings")
                    followings = home.following(home.user_id(config.user), config.max_followings)
                    new_followings = filter_known_users(followings, state.all_known_users)
                    logger.info(f"Got {len(followings)} followings, {len(new_followings)} of which are new")
                    add_user_posts(home, new_followings, state.known_followings, http=http, config=config, state=state)

                if config.max_followers > 0:
                    logger.info(f"Getting posts from last {config.max_followers} followers")
                    followers = home.followers(home.user_id(config.user), config.max_followers)
                    new_followers = filter_known_users(followers, state.all_known_users)
                    logger.info(f"Got {len(followers)} followers, {len(new_followers)} of which are new")
                    add_user_posts(home, new_followers, state.recently_checked_users, http=http, config=config, state=state)

                if config.max_follow_requests > 0:
                    logger.info(f"Getting posts from last {config.max_follow_requests} follow requests")
                    follow_requests = home.follow_requests(config.max_follow_requests)
                    new_requests = filter_known_users(follow_requests, state.all_known_users)
                    logger.info(f"Got {len(follow_requests)} follow_requests, {len(new_requests)} of which are new")
                    add_user_posts(home, new_requests, state.recently_checked_users, http=http, config=config, state=state)

                if config.from_notifications > 0:
                    logger.info(f"Getting notifications for last {config.from_notifications} hours")
                    since = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(hours=config.from_notifications)
                    accounts = home.notification_accounts(since)
                    new_accounts = filter_known_users(accounts, state.all_known_users)
                    logger.info(f"Found {len(accounts)} users in notifications, {len(new_accounts)} of which are new")
                    add_user_posts(home, new_accounts, state.recently_checked_users, http=http, config=config, state=state)

                if config.max_bookmarks > 0:
                    logger.info(f"Pulling replies to the last {config.max_bookmarks} bookmarks")
                    bookmarks = home.bookmarks(config.max_bookmarks)
                    known_context_urls = get_all_known_context_urls(config.server, bookmarks, http=http, state=state)
                    add_context_urls(home, known_context_urls, state=state)

                if config.max_favourites > 0:
                    logger.info(f"Pulling replies to the last {config.max_favourites} favourites")
                    favourites = home.favourites(config.max_favourites)
                    known_context_urls = get_all_known_context_urls(config.server, favourites, http=http, state=state)
                    add_context_urls(home, known_context_urls, state=state)

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
