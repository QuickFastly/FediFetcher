#!/usr/bin/env python3

import itertools
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from typing import NoReturn

from dateutil import parser

from fedifetcher import VERSION
from fedifetcher.config import Config, ConfigError
from fedifetcher.http import HttpClient, build_callback_url
from fedifetcher.servers import ApiFlavour, get_server_info
from fedifetcher.state import ServerCache, TimestampedSet
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

def add_user_posts(server, access_token, followings, known_followings, all_known_users, seen_urls, seen_hosts, *, http, config):
    for user in followings:
        if user['acct'] not in all_known_users and not user['url'].startswith(f"https://{server}/"):
            posts = get_user_posts(user, known_followings, server, seen_hosts, http=http)

            if(posts is not None):
                count = 0
                failed = 0
                for post in posts:
                    if post.get('reblog') is None and post.get('renoteId') is None and post.get('url') is not None and post.get('url') not in seen_urls:
                        added = add_post_with_context(post, server, access_token, seen_urls, seen_hosts, http=http, config=config)
                        if added is True:
                            seen_urls.add(post['url'])
                            count += 1
                        else:
                            failed += 1
                logger.info(f"Added {count} posts for user {user['acct']} with {failed} errors")
                if failed == 0:
                    known_followings.add(user['acct'])
                    all_known_users.add(user['acct'])

def add_post_with_context(post, server, access_token, seen_urls, seen_hosts, *, http, config):
    added = add_context_url(post['url'], server, access_token, http=http)
    if added is True:
        seen_urls.add(post['url'])
        if ('replies_count' in post or 'in_reply_to_id' in post) and config.backfill_with_context:
            parsed_urls = {}
            parsed = parse_url(post['url'], parsed_urls, http)
            if parsed is None:
                return True
            known_context_urls = get_all_known_context_urls(server, [post],parsed_urls, seen_hosts, http=http)
            add_context_urls(server, access_token, known_context_urls, seen_urls, http=http)
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


def get_user_posts(user, known_followings, server, seen_hosts, *, http):
    if user_has_opted_out(user):
        logger.debug(f"User {user['acct']} has opted out of backfilling")
        return None
    parsed_url = parse_user_url(user['url'])

    if parsed_url is None:
        # We are adding it as 'known' anyway, because we won't be able to fix this.
        known_followings.add(user['acct'])
        return None

    if(parsed_url[0] == server):
        logger.debug(f"{user['acct']} is a local user. Skip")
        known_followings.add(user['acct'])
        return None

    post_server = get_server_info(parsed_url[0], seen_hosts, http=http)
    if post_server is None:
        logger.error(f'server {parsed_url[0]} not found for post')
        return None

    if post_server.supports(ApiFlavour.MASTODON):
        return get_user_posts_mastodon(parsed_url[1], post_server.webserver, http=http)

    if post_server.supports(ApiFlavour.LEMMY):
        return get_user_posts_lemmy(parsed_url[1], user['url'], post_server.webserver, http=http)

    if post_server.supports(ApiFlavour.MISSKEY):
        return get_user_posts_misskey(parsed_url[1], post_server.webserver, http=http)

    if post_server.supports(ApiFlavour.PEERTUBE):
        return get_user_posts_peertube(parsed_url[1], post_server.webserver, http=http)

    logger.error(f'server api unknown for {post_server.webserver}, cannot fetch user posts')
    return None

def get_user_posts_mastodon(userName, webserver, *, http):
    try:
        user_id = get_user_id(webserver, userName, http=http)
    except Exception as ex:
        logger.error(f"Error getting user ID for user {userName}: {ex}")
        return None

    try:
        url = f"https://{webserver}/api/v1/accounts/{user_id}/statuses?limit=40"
        response = http.get(url)

        if(response.status_code == 200):
            return response.json()
        elif response.status_code == 404:
            raise Exception(
                f"User {userName} was not found on server {webserver}"
            )
        else:
            raise Exception(
                f"Error getting URL {url}. Status code: {response.status_code}"
            )
    except Exception as ex:
        logger.error(f"Error getting posts for user {userName}: {ex}")
        return None

def get_user_posts_lemmy(userName, userUrl, webserver, *, http):
    # community
    if re.match(r"^https:\/\/[^\/]+\/c\/", userUrl):
        try:
            url = f"https://{webserver}/api/v3/post/list?community_name={userName}&sort=New&limit=50"
            response = http.get(url)

            if(response.status_code == 200):
                posts = [post['post'] for post in response.json()['posts']]
                for post in posts:
                    post['url'] = post['ap_id']
                return posts

        except Exception as ex:
            logger.error(f"Error getting community posts for community {userName}: {ex}")
        return None

    # user
    if re.match(r"^https:\/\/[^\/]+\/u\/", userUrl):
        try:
            url = f"https://{webserver}/api/v3/user?username={userName}&sort=New&limit=50"
            response = http.get(url)

            if(response.status_code == 200):
                comments = [post['post'] for post in response.json()['comments']]
                posts = [post['post'] for post in response.json()['posts']]
                all_posts = comments + posts
                for post in all_posts:
                    post['url'] = post['ap_id']
                return all_posts

        except Exception as ex:
            logger.error(f"Error getting user posts for user {userName}: {ex}")
        return None

    logger.error(f"Unknown Lemmy profile URL type {userUrl}")
    return None

def get_user_posts_peertube(userName, webserver, *, http):
    try:
        url = f'https://{webserver}/api/v1/accounts/{userName}/videos'
        response = http.get(url)
        if response.status_code == 200:
            return response.json()['data']
        else:
            logger.error(f"Error getting posts by user {userName} from {webserver}. Status Code: {response.status_code}")
            return None
    except Exception as ex:
        logger.error(f"Error getting posts by user {userName} from {webserver}. Exception: {ex}")
        return None

def get_user_posts_misskey(userName, webserver, *, http):
    # query user info via search api
    # we could filter by host but there's no way to limit that to just the main host on firefish currently
    # on misskey it works if you supply '.' as the host but firefish does not
    userId = None
    try:
        url = f'https://{webserver}/api/users/search-by-username-and-host'
        resp = http.post(url, { 'username': userName })

        if resp.status_code == 200:
            res = resp.json()
            for user in res:
                if user['host'] is None:
                    userId = user['id']
                    break
        else:
            logger.error(f"Error finding user {userName} from {webserver}. Status Code: {resp.status_code}")
            return None
    except Exception as ex:
        logger.error(f"Error finding user {userName} from {webserver}. Exception: {ex}")
        return None

    if userId is None:
        logger.error(f'Error finding user {userName} from {webserver}: user not found on server in search')
        return None

    try:
        url = f'https://{webserver}/api/users/notes'
        resp = http.post(url, { 'userId': userId, 'limit': 40 })

        if resp.status_code == 200:
            notes = resp.json()
            for note in notes:
                if note.get('url') is None:
                    # add this to make it look like Mastodon status objects
                    note.update({ 'url': f"https://{webserver}/notes/{note['id']}" })
            return notes
        else:
            logger.error(f"Error getting posts by user {userName} from {webserver}. Status Code: {resp.status_code}")
            return None
    except Exception as ex:
        logger.error(f"Error getting posts by user {userName} from {webserver}. Exception: {ex}")
        return None


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


def get_user_id(server, user = None, access_token = None, *, http):
    """Get the user id from the server, using a username"""

    headers = {}

    if user is not None and user != '':
        url = f"https://{server}/api/v1/accounts/lookup?acct={user}"
    elif access_token is not None:
        url = f"https://{server}/api/v1/accounts/verify_credentials"
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
    else:
        raise Exception('You must supply either a user name or an access token, to get an user ID')

    response = http.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()['id']
    elif response.status_code == 404:
        raise Exception(
            f"User {user} was not found on server {server}."
        )
    else:
        raise Exception(
            f"Error getting URL {url}. Status code: {response.status_code}"
        )

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


def get_all_reply_toots(
    server, user_ids, access_token, seen_urls, reply_interval_hours, *, http
):
    """get all replies to other users by the given users in the last day"""
    replies_since = datetime.now() - timedelta(hours=reply_interval_hours)
    reply_toots = list(
        itertools.chain.from_iterable(
            get_reply_toots(
                user_id, server, access_token, seen_urls, replies_since,
        http=http)
            for user_id in user_ids
        )
    )
    logger.info(f"Found {len(reply_toots)} reply toots")
    return reply_toots


def get_reply_toots(user_id, server, access_token, seen_urls, reply_since, *, http):
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
        and toot["url"] not in seen_urls
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


def toot_context_should_be_fetched(toot):
    if toot['uri'] not in recently_checked_context:
        recently_checked_context[toot['uri']] = toot
        return True
    else:
        lastSeen = recently_checked_context[toot['uri']]['lastSeen']
        createdAt = recently_checked_context[toot['uri']]['created_at']

        # convert to date time, if needed
        if isinstance(createdAt, str):
            createdAt = parser.parse(createdAt)

        lastSeenInSeconds = (datetime.now(lastSeen.tzinfo) - lastSeen).total_seconds()
        ageInSeconds = (datetime.now(createdAt.tzinfo) - createdAt).total_seconds()
        if(ageInSeconds <= 60 * 60 and lastSeenInSeconds >= 60):
            # For the first hour: allow refetching once per minute
            return True
        if(ageInSeconds <= 24 * 60 * 60 and lastSeenInSeconds >= 10 * 60):
            # For the rest of the first day: once every 10 minutes
            return True
        if(lastSeenInSeconds >= 60 * 60):
            # After that: hourly
            return True
    return False

def get_all_known_context_urls(server, reply_toots, parsed_urls, seen_hosts, *, http):
    """get the context toots of the given toots from their original server"""
    known_context_urls = set()

    for toot in reply_toots:
        if toot_has_parseable_url(toot, parsed_urls, http=http):
            url = toot["url"] if toot["reblog"] is None else toot["reblog"]["url"]
            parsed_url = parse_url(url, parsed_urls, http)
            if toot_context_can_be_fetched(toot) and toot_context_should_be_fetched(toot):
                recently_checked_context[toot['uri']]['lastSeen'] = datetime.now(datetime.now().astimezone().tzinfo)
                context = get_toot_context(parsed_url[0], parsed_url[1], url, seen_hosts, http=http)
                if context is not None:
                    for item in context:
                        known_context_urls.add(item)
                else:
                    logger.error(f"Error getting context for toot {url}")

    known_context_urls = set(filter(lambda url: not url.startswith(f"https://{server}/"), known_context_urls))
    logger.info(f"Found {len(known_context_urls)} known context toots")

    return known_context_urls


def toot_has_parseable_url(toot, parsed_urls, *, http):
    parsed = parse_url(toot["url"] if toot["reblog"] is None else toot["reblog"]["url"], parsed_urls, http)
    if(parsed is None) :
        return False
    return True


def get_all_replied_toot_server_ids(
    server, reply_toots, replied_toot_server_ids, parsed_urls, *, http
):
    """get the server and ID of the toots the given toots replied to"""
    return filter(
        lambda x: x is not None,
        (
            get_replied_toot_server_id(server, toot, replied_toot_server_ids, parsed_urls, http=http)
            for toot in reply_toots
        ),
    )


def get_replied_toot_server_id(server, toot, replied_toot_server_ids, parsed_urls, *, http):
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
    if o_url in replied_toot_server_ids:
        return replied_toot_server_ids[o_url]

    url = http.get_redirect_url(o_url)

    if url is None:
        return None

    match = parse_url(url, parsed_urls, http)
    if match is not None:
        replied_toot_server_ids[o_url] = (url, match)
        return (url, match)

    logger.error(f"Error parsing toot URL {url}")
    replied_toot_server_ids[o_url] = None
    return None

def get_all_context_urls(server, replied_toot_ids, seen_hosts, *, http):
    """get the URLs of the context toots of the given toots"""
    return filter(
        lambda url: not url.startswith(f"https://{server}/"),
        itertools.chain.from_iterable(
            get_toot_context(server, toot_id, url, seen_hosts, http=http)
            for (url, (server, toot_id)) in replied_toot_ids
        ),
    )


def get_toot_context(server, toot_id, toot_url, seen_hosts, *, http):
    """get the URLs of the context toots of the given toot"""

    post_server = get_server_info(server, seen_hosts, http=http)
    if post_server is None:
        logger.error(f'server {server} not found for post')
        return []

    if post_server.supports(ApiFlavour.MASTODON):
        return get_mastodon_urls(post_server.webserver, toot_id, toot_url, http=http)
    if post_server.supports(ApiFlavour.LEMMY):
        return get_lemmy_urls(post_server.webserver, toot_id, toot_url, http=http)
    if post_server.supports(ApiFlavour.MISSKEY):
        return get_misskey_urls(post_server.webserver, toot_id, toot_url, http=http)
    if post_server.supports(ApiFlavour.PEERTUBE):
        return get_peertube_urls(post_server.webserver, toot_id, toot_url, http=http)

    logger.error(f'unknown server api for {server}')
    return []

def get_mastodon_urls(webserver, toot_id, toot_url, *, http):
    url = f"https://{webserver}/api/v1/statuses/{toot_id}/context"
    try:
        resp = http.get(url)
    except Exception as ex:
        logger.error(f"Error getting context for toot {toot_url}. Exception: {ex}")
        return []

    if resp.status_code == 200:
        try:
            res = resp.json()
            logger.debug(f"Got context for toot {toot_url}")
            return (toot["url"] for toot in (res["ancestors"] + res["descendants"]))
        except Exception as ex:
            logger.error(f"Error parsing context for toot {toot_url}. Exception: {ex}")
        return []

    logger.error(
        f"Error getting context for toot {toot_url}. Status code: {resp.status_code}"
    )
    return []

def get_lemmy_urls(webserver, toot_id, toot_url, *, http):
    if toot_url.find("/comment/") != -1:
        return get_lemmy_comment_context(webserver, toot_id, toot_url, http=http)
    if toot_url.find("/post/") != -1:
        return get_lemmy_comments_urls(webserver, toot_id, toot_url, http=http)
    else:
        logger.error(f'unknown lemmy url type {toot_url}')
        return []

def get_lemmy_comment_context(webserver, toot_id, toot_url, *, http):
    """get the URLs of the context toots of the given toot"""
    comment = f"https://{webserver}/api/v3/comment?id={toot_id}"
    try:
        resp = http.get(comment)
    except Exception as ex:
        logger.error(f"Error getting comment {toot_id} from {toot_url}. Exception: {ex}")
        return []

    if resp.status_code == 200:
        try:
            res = resp.json()
            post_id = res['comment_view']['comment']['post_id']
            return get_lemmy_comments_urls(webserver, post_id, toot_url, http=http)
        except Exception as ex:
            logger.error(f"Error parsing context for comment {toot_url}. Exception: {ex}")
        return []

    logger.error(f"Error getting comment {toot_id} from {toot_url}. Status code: {resp.status_code}")
    return []

def get_lemmy_comments_urls(webserver, post_id, toot_url, *, http):
    """get the URLs of the comments of the given post"""
    urls = []
    url = f"https://{webserver}/api/v3/post?id={post_id}"
    try:
        resp = http.get(url)
    except Exception as ex:
        logger.error(f"Error getting post {post_id} from {toot_url}. Exception: {ex}")
        return []

    if resp.status_code == 200:
        try:
            res = resp.json()
            if res['post_view']['counts']['comments'] == 0:
                return []
            urls.append(res['post_view']['post']['ap_id'])
        except Exception as ex:
            logger.error(f"Error parsing post {post_id} from {toot_url}. Exception: {ex}")

    url = f"https://{webserver}/api/v3/comment/list?post_id={post_id}&sort=New&limit=50"
    try:
        resp = http.get(url)
    except Exception as ex:
        logger.error(f"Error getting comments for post {post_id} from {toot_url}. Exception: {ex}")
        return []

    if resp.status_code == 200:
        try:
            res = resp.json()
            list_of_urls = [comment_info['comment']['ap_id'] for comment_info in res['comments']]
            logger.debug(f"Got {len(list_of_urls)} comments for post {toot_url}")
            urls.extend(list_of_urls)
            return urls
        except Exception as ex:
            logger.error(f"Error parsing comments for post {toot_url}. Exception: {ex}")

    logger.error(f"Error getting comments for post {toot_url}. Status code: {resp.status_code}")
    return []

def get_peertube_urls(webserver, post_id, toot_url, *, http):
    """get the URLs of the comments of a given peertube video"""
    comments = f"https://{webserver}/api/v1/videos/{post_id}/comment-threads"
    try:
        resp = http.get(comments)
    except Exception as ex:
        logger.error(f"Error getting comments on video {post_id} from {toot_url}. Exception: {ex}")
        return []

    if resp.status_code == 200:
        return [comment['url'] for comment in resp.json()['data']]

    logger.error(f"Error getting comments on video {post_id} from {toot_url}. Status code: {resp.status_code}")
    return []

def get_misskey_urls(webserver, post_id, toot_url, *, http):
    """get the URLs of the comments of a given misskey post"""

    urls = []
    url = f"https://{webserver}/api/notes/children"
    try:
        resp = http.post(url, { 'noteId': post_id, 'limit': 100, 'depth': 12 })
    except Exception as ex:
        logger.error(f"Error getting post {post_id} from {toot_url}. Exception: {ex}")
        return []

    if resp.status_code == 200:
        try:
            res = resp.json()
            logger.debug(f"Got children for misskey post {toot_url}")
            list_of_urls = [f'https://{webserver}/notes/{comment_info["id"]}' for comment_info in res]
            urls.extend(list_of_urls)
        except Exception as ex:
            logger.error(f"Error parsing post {post_id} from {toot_url}. Exception: {ex}")
    else:
        logger.error(f"Error getting post {post_id} from {toot_url}. Status Code: {resp.status_code}")

    url = f"https://{webserver}/api/notes/conversation"
    try:
        resp = http.post(url, { 'noteId': post_id, 'limit': 100 })
    except Exception as ex:
        logger.error(f"Error getting post {post_id} from {toot_url}. Exception: {ex}")
        return []

    if resp.status_code == 200:
        try:
            res = resp.json()
            logger.debug(f"Got conversation for misskey post {toot_url}")
            list_of_urls = [f'https://{webserver}/notes/{comment_info["id"]}' for comment_info in res]
            urls.extend(list_of_urls)
        except Exception as ex:
            logger.error(f"Error parsing post {post_id} from {toot_url}. Exception: {ex}")
    else:
        logger.error(f"Error getting post {post_id} from {toot_url}. Status Code: {resp.status_code}")

    return urls

def add_context_urls(server, access_token, context_urls, seen_urls, *, http):
    """add the given toot URLs to the server"""
    count = 0
    failed = 0
    for url in context_urls:
        if url not in seen_urls:
            added = add_context_url(url, server, access_token, http=http)
            if added is True:
                seen_urls.add(url)
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

def fetch_timeline_context(timeline_posts, token, parsed_urls, seen_hosts, seen_urls, all_known_users, recently_checked_users, *, http, config):
    known_context_urls = get_all_known_context_urls(config.server, timeline_posts,parsed_urls, seen_hosts, http=http)
    add_context_urls(config.server, token, known_context_urls, seen_urls, http=http)

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
                if user not in mentioned_users and user['acct'] not in all_known_users:
                    mentioned_users.append(user)

        add_user_posts(config.server, token, filter_known_users(mentioned_users, all_known_users), recently_checked_users, all_known_users, seen_urls, seen_hosts, http=http, config=config)

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

    runId = uuid.uuid4()

    if(config.on_start is not None and config.on_start != ''):
        try:
            http.get(build_callback_url(config.on_start, {"rid": runId}), ignore_robots_txt = True)
        except Exception as ex:
            logger.error(f"Error getting callback url: {ex}")

    LOCK_FILE = config.lock_path

    if( os.path.exists(LOCK_FILE)):
        logger.debug(f"Lock file exists at {LOCK_FILE}")

        try:
            with open(LOCK_FILE, encoding="utf-8") as f:
                lock_time = parser.parse(f.read())

            if (datetime.now() - lock_time).total_seconds() >= config.lock_hours * 60 * 60:
                os.remove(LOCK_FILE)
                logger.debug("Lock file has expired. Removed lock file.")
            else:
                failure_message = f"Lock file age is {datetime.now() - lock_time} - below --lock-hours={config.lock_hours} provided."
                logger.critical(failure_message)
                if(config.on_fail is not None and config.on_fail != ''):
                    try:
                        http.get(build_callback_url(config.on_fail, {"rid": runId, "ping": int((datetime.now() - start).total_seconds() * 1000), "msg": failure_message}), ignore_robots_txt = True)
                    except Exception as ex:
                        logger.error(f"Error getting callback url: {ex}")
                sys.exit(1)

        except Exception:
            failure_message = "Cannot read logfile age - aborting."
            logger.critical(failure_message)
            if(config.on_fail is not None and config.on_fail != ''):
                try:
                    http.get(build_callback_url(config.on_fail, {"rid": runId, "ping": int((datetime.now() - start).total_seconds() * 1000), "msg": failure_message}), ignore_robots_txt = True)
                except Exception as ex:
                    logger.error(f"Error getting callback url: {ex}")
            sys.exit(1)

    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(f"{datetime.now()}")

    try:

        SEEN_URLS_FILE = config.seen_urls_file
        REPLIED_TOOT_SERVER_IDS_FILE = config.replied_toot_server_ids_file
        KNOWN_FOLLOWINGS_FILE = config.known_followings_file
        RECENTLY_CHECKED_USERS_FILE = config.recently_checked_users_file
        SEEN_HOSTS_FILE = config.seen_hosts_file
        RECENTLY_CHECKED_CONTEXTS_FILE = config.recently_checked_contexts_file

        INSTANCE_BLOCKLIST = config.instance_blocklist
        # A value of True or False is a verdict reached without a usable robots.txt:
        # True when it could not be fetched, False when access was denied outright.
        ROBOTS_TXT: dict[str, str | bool] = {}

        seen_urls = TimestampedSet([])
        if os.path.exists(SEEN_URLS_FILE):
            with open(SEEN_URLS_FILE, encoding="utf-8") as f:
                seen_urls = TimestampedSet(f.read().splitlines())

        replied_toot_server_ids = {}
        if os.path.exists(REPLIED_TOOT_SERVER_IDS_FILE):
            with open(REPLIED_TOOT_SERVER_IDS_FILE, encoding="utf-8") as f:
                replied_toot_server_ids = json.load(f)

        known_followings = TimestampedSet([])
        if os.path.exists(KNOWN_FOLLOWINGS_FILE):
            with open(KNOWN_FOLLOWINGS_FILE, encoding="utf-8") as f:
                known_followings = TimestampedSet(f.read().splitlines())

        recently_checked_users = TimestampedSet({})
        if os.path.exists(RECENTLY_CHECKED_USERS_FILE):
            with open(RECENTLY_CHECKED_USERS_FILE, encoding="utf-8") as f:
                recently_checked_users = TimestampedSet(json.load(f))

        recently_checked_users.expire_older_than(
            timedelta(hours=config.remember_users_for_hours)
        )

        recently_checked_context = {}
        if(os.path.exists(RECENTLY_CHECKED_CONTEXTS_FILE)):
            with open(RECENTLY_CHECKED_CONTEXTS_FILE, encoding="utf-8") as f:
                recently_checked_context = json.load(f)

        # Remove any toots that we haven't seen in a while, to ensure this doesn't grow indefinitely
        for tootUrl in list(recently_checked_context):
            recently_checked_context[tootUrl]['lastSeen'] = parser.parse(recently_checked_context[tootUrl]['lastSeen'])
            recently_checked_context[tootUrl]['created_at'] = parser.parse(recently_checked_context[tootUrl]['created_at'])
            lastSeen = recently_checked_context[tootUrl]['lastSeen']
            userAge = datetime.now(lastSeen.tzinfo) - lastSeen
            # dont really need to keep track for more than 7 days: if we haven't seen it in 7 days we can refetch content anyway
            if(userAge.total_seconds() > 7 * 24 * 60 * 60):
                recently_checked_context.pop(tootUrl)

        parsed_urls: dict[str, tuple[str, str] | None] = {}

        all_known_users = TimestampedSet(list(known_followings) + list(recently_checked_users))

        if os.path.exists(SEEN_HOSTS_FILE):
            with open(SEEN_HOSTS_FILE, encoding="utf-8") as f:
                seen_hosts = ServerCache(json.load(f))

            seen_hosts.expire(
                max_age=timedelta(days=config.remember_hosts_for_days),
                failure_max_age=timedelta(hours=1),
            )
        else:
            seen_hosts = ServerCache({})

        # Delete any old robots.txt files so we can re-download them
        http.robots.discard_stale_files(timedelta(days=1))

        for token in config.access_tokens:

            if config.from_lists:
                """Pull replies from lists"""
                lists = get_user_lists(config.server, token, http=http)
                logger.info(f"Getting context for {len(lists)} lists")
                for user_list in lists:
                    # Fill context from list
                    if config.max_list_length > 0:
                        timeline_toots = get_list_timeline(config.server, user_list, token, config.max_list_length, http=http)
                        fetch_timeline_context(timeline_toots, token, parsed_urls, seen_hosts, seen_urls, all_known_users, recently_checked_users, http=http, config=config)

                    # Backfill profiles from list
                    if config.max_list_accounts:
                        accounts = get_list_users(config.server, user_list, token, config.max_list_accounts, http=http)
                        add_user_posts(config.server, token, accounts, recently_checked_users, all_known_users, seen_urls, seen_hosts, http=http, config=config)

            if config.reply_interval_in_hours > 0:
                """pull the context toots of toots user replied to, from their
                original server, and add them to the local server."""
                user_ids = get_active_user_ids(config.server, token, config.reply_interval_in_hours, http=http)
                reply_toots = get_all_reply_toots(
                    config.server, user_ids, token, seen_urls, config.reply_interval_in_hours,
        http=http)
                known_context_urls = get_all_known_context_urls(config.server, reply_toots,parsed_urls, seen_hosts, http=http)
                seen_urls.update(known_context_urls)
                replied_toot_ids = get_all_replied_toot_server_ids(
                    config.server, reply_toots, replied_toot_server_ids, parsed_urls,
                    http=http,
                )
                context_urls = get_all_context_urls(config.server, replied_toot_ids, seen_hosts, http=http)
                add_context_urls(config.server, token, context_urls, seen_urls, http=http)


            if config.home_timeline_length > 0:
                """Do the same with any toots on the key owner's home timeline """
                logger.info("Getting context for home timeline")
                timeline_toots = get_timeline(config.server, token, config.home_timeline_length, http=http)
                fetch_timeline_context(timeline_toots, token, parsed_urls, seen_hosts, seen_urls, all_known_users, recently_checked_users, http=http, config=config)

            if config.max_followings > 0:
                logger.info(f"Getting posts from last {config.max_followings} followings")
                user_id = get_user_id(config.server, config.user, token, http=http)
                followings = get_new_followings(config.server, user_id, token, config.max_followings, all_known_users, http=http)
                add_user_posts(config.server, token, followings, known_followings, all_known_users, seen_urls, seen_hosts, http=http, config=config)

            if config.max_followers > 0:
                logger.info(f"Getting posts from last {config.max_followers} followers")
                user_id = get_user_id(config.server, config.user, token, http=http)
                followers = get_new_followers(config.server, user_id, token, config.max_followers, all_known_users, http=http)
                add_user_posts(config.server, token, followers, recently_checked_users, all_known_users, seen_urls, seen_hosts, http=http, config=config)

            if config.max_follow_requests > 0:
                logger.info(f"Getting posts from last {config.max_follow_requests} follow requests")
                follow_requests = get_new_follow_requests(config.server, token, config.max_follow_requests, all_known_users, http=http)
                add_user_posts(config.server, token, follow_requests, recently_checked_users, all_known_users, seen_urls, seen_hosts, http=http, config=config)

            if config.from_notifications > 0:
                logger.info(f"Getting notifications for last {config.from_notifications} hours")
                notification_users = get_notification_users(config.server, token, all_known_users, config.from_notifications, http=http)
                add_user_posts(config.server, token, notification_users, recently_checked_users, all_known_users, seen_urls, seen_hosts, http=http, config=config)

            if config.max_bookmarks > 0:
                logger.info(f"Pulling replies to the last {config.max_bookmarks} bookmarks")
                bookmarks = get_bookmarks(config.server, token, config.max_bookmarks, http=http)
                known_context_urls = get_all_known_context_urls(config.server, bookmarks,parsed_urls, seen_hosts, http=http)
                add_context_urls(config.server, token, known_context_urls, seen_urls, http=http)

            if config.max_favourites > 0:
                logger.info(f"Pulling replies to the last {config.max_favourites} favourites")
                favourites = get_favourites(config.server, token, config.max_favourites, http=http)
                known_context_urls = get_all_known_context_urls(config.server, favourites,parsed_urls, seen_hosts, http=http)
                add_context_urls(config.server, token, known_context_urls, seen_urls, http=http)

        with open(KNOWN_FOLLOWINGS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(list(known_followings)[-100000:]))

        with open(SEEN_URLS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(list(seen_urls)[-100000:]))

        with open(REPLIED_TOOT_SERVER_IDS_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(list(replied_toot_server_ids.items())[-100000:]), f)

        with open(RECENTLY_CHECKED_USERS_FILE, "w", encoding="utf-8") as f:
            f.write(recently_checked_users.toJSON())

        with open(SEEN_HOSTS_FILE, "w", encoding="utf-8") as f:
            f.write(seen_hosts.toJSON())

        with open(RECENTLY_CHECKED_CONTEXTS_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(recently_checked_context, default=str))

        os.remove(LOCK_FILE)

        duration = datetime.now() - start
        success_message = f"Processing finished in {duration}."

        if(config.on_done is not None and config.on_done != ''):
            try:
                http.get(build_callback_url(config.on_done, {"rid": runId, "ping": int(duration.total_seconds() * 1000), "msg": success_message}), ignore_robots_txt = True)
            except Exception as ex:
                logger.error(f"Error getting callback url: {ex}")

        logger.info(success_message)

    except Exception as ex:
        os.remove(LOCK_FILE)
        duration = datetime.now() - start
        logger.error(f"Job failed after {duration}.")
        if(config.on_fail is not None and config.on_fail != ''):
            try:
                http.get(build_callback_url(config.on_fail, {"rid": runId, "ping": int(duration.total_seconds() * 1000), "msg": str(ex)}), ignore_robots_txt = True)
            except Exception as ex:
                logger.error(f"Error getting callback url: {ex}")
        raise
