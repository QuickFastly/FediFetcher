from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, ClassVar

from fedifetcher.posts import Post
from fedifetcher.servers import ApiFlavour
from fedifetcher.translate import parse_date, unusable, usable

if TYPE_CHECKING:
    from fedifetcher.http import HttpClient

logger = logging.getLogger("FediFetcher")

COMMUNITY_PATH = re.compile(r"^https://[^/]+/c/")
USER_PATH = re.compile(r"^https://[^/]+/u/")


def to_post(raw: dict[str, Any]) -> Post | None:
    """A Lemmy post or comment, which names itself by its ActivityPub id"""
    ap_id = raw.get("ap_id")
    created_at = parse_date(raw.get("published"))
    if ap_id is None or created_at is None:
        unusable("lemmy", raw.get("id"))
        return None

    # Lemmy has no visibility setting: a community is readable or it is not
    return Post(url=ap_id, uri=ap_id, created_at=created_at, is_public=True)


class LemmyApi:
    """Lemmy, whose URLs say whether they name a community, user, post or comment"""

    flavour: ClassVar[ApiFlavour] = ApiFlavour.LEMMY

    def __init__(self, webserver: str, http: HttpClient) -> None:
        self.webserver = webserver
        self._http = http

    def fetch_user_posts(self, username: str, profile_url: str) -> list[Post] | None:
        if COMMUNITY_PATH.match(profile_url):
            return self._fetch_community_posts(username)
        if USER_PATH.match(profile_url):
            return self._fetch_account_posts(username)

        logger.error(f"Unknown Lemmy profile URL type {profile_url}")
        return None

    def _fetch_community_posts(self, username: str) -> list[Post] | None:
        try:
            url = f"https://{self.webserver}/api/v3/post/list?community_name={username}&sort=New&limit=50"
            response = self._http.get(url)

            if(response.status_code == 200):
                return usable(
                    to_post(post['post']) for post in response.json()['posts']
                )
        except Exception as ex:
            logger.error(f"Error getting community posts for community {username}: {ex}")
        return None

    def _fetch_account_posts(self, username: str) -> list[Post] | None:
        try:
            url = f"https://{self.webserver}/api/v3/user?username={username}&sort=New&limit=50"
            response = self._http.get(url)

            if(response.status_code == 200):
                body = response.json()
                return usable(
                    to_post(entry['post'])
                    for entry in body['comments'] + body['posts']
                )
        except Exception as ex:
            logger.error(f"Error getting user posts for user {username}: {ex}")
        return None

    def fetch_context_urls(self, post_id: str, post_url: str) -> list[str]:
        if "/comment/" in post_url:
            return self._comment_context(post_id, post_url)
        if "/post/" in post_url:
            return self._post_comments(post_id, post_url)

        logger.error(f'unknown lemmy url type {post_url}')
        return []

    def _comment_context(self, comment_id: str, post_url: str) -> list[str]:
        """get the URLs of the context toots of the given toot"""
        url = f"https://{self.webserver}/api/v3/comment?id={comment_id}"
        try:
            resp = self._http.get(url)
        except Exception as ex:
            logger.error(f"Error getting comment {comment_id} from {post_url}. Exception: {ex}")
            return []

        if resp.status_code == 200:
            try:
                res = resp.json()
                post_id = res['comment_view']['comment']['post_id']
                return self._post_comments(post_id, post_url)
            except Exception as ex:
                logger.error(f"Error parsing context for comment {post_url}. Exception: {ex}")
            return []

        logger.error(f"Error getting comment {comment_id} from {post_url}. Status code: {resp.status_code}")
        return []

    def _post_comments(self, post_id: str, post_url: str) -> list[str]:
        """get the URLs of the comments of the given post"""
        urls: list[str] = []
        url = f"https://{self.webserver}/api/v3/post?id={post_id}"
        try:
            resp = self._http.get(url)
        except Exception as ex:
            logger.error(f"Error getting post {post_id} from {post_url}. Exception: {ex}")
            return []

        if resp.status_code == 200:
            try:
                res = resp.json()
                if res['post_view']['counts']['comments'] == 0:
                    return []
                urls.append(res['post_view']['post']['ap_id'])
            except Exception as ex:
                logger.error(f"Error parsing post {post_id} from {post_url}. Exception: {ex}")

        url = f"https://{self.webserver}/api/v3/comment/list?post_id={post_id}&sort=New&limit=50"
        try:
            resp = self._http.get(url)
        except Exception as ex:
            logger.error(f"Error getting comments for post {post_id} from {post_url}. Exception: {ex}")
            return []

        if resp.status_code == 200:
            try:
                res = resp.json()
                list_of_urls = [comment_info['comment']['ap_id'] for comment_info in res['comments']]
                logger.debug(f"Got {len(list_of_urls)} comments for post {post_url}")
                urls.extend(list_of_urls)
                return urls
            except Exception as ex:
                logger.error(f"Error parsing comments for post {post_url}. Exception: {ex}")

        logger.error(f"Error getting comments for post {post_url}. Status code: {resp.status_code}")
        return []
