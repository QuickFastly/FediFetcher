from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn, cast

from dateutil import parser

from fedifetcher.posts import Post
from fedifetcher.servers import ApiFlavour
from fedifetcher.translate import parse_date, unusable, usable
from fedifetcher.users import User

if TYPE_CHECKING:
    from fedifetcher.http import HttpClient

logger = logging.getLogger("FediFetcher")

# a status anyone is allowed to read
PUBLIC = ("public", "unlisted")


def to_post(raw: dict[str, Any]) -> Post | None:
    """A status from the Mastodon API, which our own server also speaks"""
    url = raw.get("url")
    created_at = parse_date(raw.get("created_at"))
    if url is None or created_at is None:
        unusable("mastodon", raw.get("uri"))
        return None

    boosted = raw.get("reblog")
    return Post(
        url=url,
        uri=raw.get("uri") or url,
        created_at=created_at,
        is_public=raw.get("visibility") in PUBLIC,
        reblog=to_post(boosted) if boosted is not None else None,
        in_reply_to_id=raw.get("in_reply_to_id"),
        in_reply_to_account_id=raw.get("in_reply_to_account_id"),
        reply_count=raw.get("replies_count"),
        account=to_user(raw["account"]) if raw.get("account") else None,
        mentions=tuple(usable(to_user(m) for m in raw.get("mentions") or [])),
    )


def to_user(raw: dict[str, Any]) -> User | None:
    """An account, either listed by our server or named by one of its posts"""
    acct = raw.get("acct")
    url = raw.get("url")
    if acct is None or url is None:
        unusable("mastodon", raw.get("id"))
        return None

    note = raw.get("note")
    return User(
        acct=acct,
        url=url,
        id=raw.get("id"),
        note=note if isinstance(note, str) else "",
        # absent means the account never said, which is not the same as no
        indexable=raw.get("indexable", True),
        discoverable=raw.get("discoverable", True),
    )


class MastodonApi:
    """Servers implementing the Mastodon API: Mastodon, Pleroma, Pixelfed and friends"""

    flavour: ClassVar[ApiFlavour] = ApiFlavour.MASTODON

    def __init__(self, webserver: str, http: HttpClient) -> None:
        self.webserver = webserver
        self._http = http

    def user_id(self, user: str | None = None, access_token: str | None = None) -> str:
        """Look up the numeric id the API addresses an account by"""
        headers = {}

        if user is not None and user != '':
            url = f"https://{self.webserver}/api/v1/accounts/lookup?acct={user}"
        elif access_token is not None:
            url = f"https://{self.webserver}/api/v1/accounts/verify_credentials"
            headers = {
                "Authorization": f"Bearer {access_token}",
            }
        else:
            raise Exception('You must supply either a user name or an access token, to get an user ID')

        response = self._http.get(url, headers=headers)

        if response.status_code == 200:
            return cast("str", response.json()['id'])
        elif response.status_code == 404:
            raise Exception(
                f"User {user} was not found on server {self.webserver}."
            )
        else:
            raise Exception(
                f"Error getting URL {url}. Status code: {response.status_code}"
            )

    def fetch_user_posts(self, username: str, profile_url: str) -> list[Post] | None:
        try:
            user_id = self.user_id(username)
        except Exception as ex:
            logger.error(f"Error getting user ID for user {username}: {ex}")
            return None

        try:
            url = f"https://{self.webserver}/api/v1/accounts/{user_id}/statuses?limit=40"
            response = self._http.get(url)

            if(response.status_code == 200):
                return usable(to_post(raw) for raw in response.json())
            elif response.status_code == 404:
                raise Exception(
                    f"User {username} was not found on server {self.webserver}"
                )
            else:
                raise Exception(
                    f"Error getting URL {url}. Status code: {response.status_code}"
                )
        except Exception as ex:
            logger.error(f"Error getting posts for user {username}: {ex}")
            return None

    def fetch_context_urls(self, post_id: str, post_url: str) -> list[str]:
        url = f"https://{self.webserver}/api/v1/statuses/{post_id}/context"
        try:
            resp = self._http.get(url)
        except Exception as ex:
            logger.error(f"Error getting context for toot {post_url}. Exception: {ex}")
            return []

        if resp.status_code == 200:
            try:
                res = resp.json()
                logger.debug(f"Got context for toot {post_url}")
                return [toot["url"] for toot in (res["ancestors"] + res["descendants"])]
            except Exception as ex:
                logger.error(f"Error parsing context for toot {post_url}. Exception: {ex}")
            return []

        logger.error(
            f"Error getting context for toot {post_url}. Status code: {resp.status_code}"
        )
        return []


def report_mastodon_error(
    error_message: str, error_code: int, access_token: str, required_scope: str = ''
) -> NoReturn:
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


def get_paginated(
    url: str, stop_at: int | datetime, headers: Mapping[str, str] | None = None,
    timeout: int | None = None, max_tries: int = 5, *, http: HttpClient,
) -> list[Any]:
    """Follow a Mastodon collection across pages.

    `stop_at` is either how many entries are wanted, or the oldest creation
    date worth having.
    """
    headers = headers or {}
    furl = f"{url}?limit={stop_at}" if isinstance(stop_at, int) else url

    response = http.get(furl, headers, timeout, max_tries)

    if response.status_code != 200:
        report_mastodon_error(
            f"Error getting URL {url}",
            response.status_code,
            headers.get('Authorization', '').replace("Bearer ", ""),
        )

    result: list[Any] = response.json()

    while _wants_more(result, stop_at) and 'next' in response.links:
        response = http.get(response.links['next']['url'], headers, timeout, max_tries)
        if response.status_code != 200:
            raise Exception(
                f"Error getting URL {response.url}. \
                    Status code: {response.status_code}"
            )
        page = response.json()
        if not isinstance(page, list):
            break
        result += page

    return result


def _wants_more(result: list[Any], stop_at: int | datetime) -> bool:
    if isinstance(stop_at, int):
        return len(result) < stop_at
    return bool(result) and parser.parse(result[-1]['created_at']) >= stop_at


class HomeServer:
    """Our own instance, spoken to with one of the configured access tokens"""

    def __init__(self, server: str, token: str, http: HttpClient) -> None:
        self.server = server
        self._token = token
        self._http = http
        self._api = MastodonApi(server, http)

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _paginated(self, path: str, stop_at: int | datetime) -> list[Any]:
        return get_paginated(
            f"https://{self.server}{path}", stop_at, self._auth, http=self._http
        )

    def user_id(self, user: str | None = None) -> str:
        return self._api.user_id(user, self._token)

    def _posts(self, path: str, stop_at: int | datetime) -> list[Post]:
        return usable(to_post(raw) for raw in self._paginated(path, stop_at))

    def bookmarks(self, limit: int) -> list[Post]:
        return self._posts("/api/v1/bookmarks", limit)

    def favourites(self, limit: int) -> list[Post]:
        return self._posts("/api/v1/favourites", limit)

    def _accounts(self, path: str, stop_at: int | datetime) -> list[User]:
        return usable(to_user(raw) for raw in self._paginated(path, stop_at))

    def follow_requests(self, limit: int) -> list[User]:
        return self._accounts("/api/v1/follow_requests", limit)

    def followers(self, user_id: str, limit: int) -> list[User]:
        return self._accounts(f"/api/v1/accounts/{user_id}/followers", limit)

    def following(self, user_id: str, limit: int) -> list[User]:
        return self._accounts(f"/api/v1/accounts/{user_id}/following", limit)

    def lists(self) -> list[Any]:
        return self._paginated("/api/v1/lists", 99)

    def list_timeline(self, list_id: str, limit: int) -> list[Post]:
        return self._posts(f"/api/v1/timelines/list/{list_id}", limit)

    def list_accounts(self, list_id: str, limit: int) -> list[User]:
        return self._accounts(f"/api/v1/lists/{list_id}/accounts", limit)

    def notification_accounts(self, since: datetime) -> list[User]:
        """Accounts appearing in notifications since the given time"""
        notifications = self._paginated("/api/v1/notifications", since)
        accounts: list[User] = []
        for notification in notifications:
            when = parser.parse(notification['created_at'])
            account = to_user(notification['account'])
            if when >= since and account is not None and account not in accounts:
                accounts.append(account)
        return accounts

    def timeline(self, limit: int) -> list[Post]:
        """Get all post in the user's home timeline"""
        url = f"https://{self.server}/api/v1/timelines/home"
        try:
            response = self._toots(url)
            toots: list[Any] = response.json()

            # Paginate as needed
            while len(toots) < limit and 'next' in response.links:
                response = self._toots(response.links['next']['url'])
                toots = toots + response.json()
        except Exception as ex:
            logger.error(f"Error getting timeline toots: {ex}")
            raise

        logger.info(f"Found {len(toots)} toots in timeline")
        return usable(to_post(raw) for raw in toots)

    def _toots(self, url: str) -> Any:
        response = self._http.get(url, headers=self._auth)
        if response.status_code != 200:
            report_mastodon_error(
                f"Error getting URL {url}", response.status_code, self._token,
                "read:statuses",
            )
        return response

    def active_user_ids(self, reply_interval_hours: float) -> Iterator[str]:
        """user IDs on our server that have posted in the given time interval"""
        since = datetime.now() - timedelta(days=reply_interval_hours / 24 + 1)
        url = f"https://{self.server}/api/v1/admin/accounts"
        resp = self._http.get(url, headers=self._auth)
        if resp.status_code != 200:
            report_mastodon_error(
                f"Error getting user IDs on server {self.server}",
                resp.status_code, self._token, "admin:read:accounts",
            )

        for user in resp.json():
            last_status_at = user["account"]["last_status_at"]
            if last_status_at is not None:
                if datetime.strptime(last_status_at, "%Y-%m-%d") > since:
                    logger.info(f"Found active user: {user['username']}")
                    yield user["id"]

    def account_statuses(self, user_id: str) -> list[Post]:
        """Recent posts by one of our users, replies included"""
        url = f"https://{self.server}/api/v1/accounts/{user_id}/statuses?exclude_replies=false&limit=40"
        resp = self._http.get(url, headers=self._auth)

        if resp.status_code != 200:
            report_mastodon_error(
                f"Error getting replies for user {user_id} on server {self.server}",
                resp.status_code, self._token, "read:statuses",
            )
        return usable(to_post(raw) for raw in resp.json())

    def resolve(self, url: str) -> bool:
        """Ask our server to fetch a remote post, so it appears locally"""
        search_url = f"https://{self.server}/api/v2/search?q={url}&resolve=true&limit=1"

        try:
            resp = self._http.get(search_url, headers=self._auth)
        except Exception as ex:
            logger.error(
                f"Error adding url {search_url} to server {self.server}. Exception: {ex}"
            )
            return False

        if resp.status_code == 200:
            logger.debug(f"Added context url {url}")
            return True
        elif resp.status_code == 403:
            logger.error(
                f"Error adding url {search_url} to server {self.server}. Status code: {resp.status_code}. "
                "Make sure you have the read:search scope enabled for your access token."
            )
            return False
        else:
            logger.error(
                f"Error adding url {search_url} to server {self.server}. Status code: {resp.status_code}"
            )
            return False
