from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, ClassVar

from fedifetcher.posts import Post
from fedifetcher.servers import ApiFlavour
from fedifetcher.translate import first_name_in, parse_date, unusable, usable

if TYPE_CHECKING:
    from fedifetcher.http import HttpClient

logger = logging.getLogger("FediFetcher")

# PeerTube says who may watch with a number: the rest of its VideoPrivacy enum
# is 3 private, 4 internal and 5 password protected
PUBLIC = (1, 2)  # public, unlisted

CHANNEL_PATH = re.compile(r"^https://[^/]+/(?:video-channels|c)/")

PROFILE_PATHS = (
    re.compile(r"^https://[^/]+/(?:accounts|a|video-channels|c)/(?P<name>[^/]+)"),
)
POST_PATHS = (re.compile(r"^https://[^/]+/videos/watch/(?P<name>[^/]+)"),)


def to_post(raw: dict[str, Any]) -> Post | None:
    """A PeerTube video, whose comments are the replies to it"""
    url = raw.get("url")
    created_at = parse_date(raw.get("publishedAt") or raw.get("createdAt"))
    if url is None or created_at is None:
        unusable("peertube", raw.get("uuid"))
        return None

    privacy = raw.get("privacy") or {}
    return Post(
        url=url,
        uri=raw.get("uri") or url,
        created_at=created_at,
        is_public=privacy.get("id", 1) in PUBLIC,
    )


class PeerTubeApi:
    """PeerTube, where posts are videos and replies are comment threads"""

    flavour: ClassVar[ApiFlavour] = ApiFlavour.PEERTUBE

    def __init__(self, webserver: str, http: HttpClient) -> None:
        self.webserver = webserver
        self._http = http

    def username_from(self, profile_url: str) -> str | None:
        return first_name_in(PROFILE_PATHS, profile_url)

    def post_id_from(self, post_url: str) -> str | None:
        return first_name_in(POST_PATHS, post_url)

    def fetch_user_posts(self, username: str, profile_url: str) -> list[Post] | None:
        # a channel and the account that owns it are different things here, and
        # they are asked for separately. Anything we do not recognise is tried
        # as an account, which is what every URL used to be treated as.
        collection = "video-channels" if CHANNEL_PATH.match(profile_url) else "accounts"
        try:
            url = f'https://{self.webserver}/api/v1/{collection}/{username}/videos'
            response = self._http.get(url)
            if response.status_code == 200:
                return usable(
                    to_post(video) for video in response.json()['data']
                )

            logger.error(f"Error getting posts by user {username} from {self.webserver}. Status Code: {response.status_code}")
            return None
        except Exception as ex:
            logger.error(f"Error getting posts by user {username} from {self.webserver}. Exception: {ex}")
            return None

    def fetch_context_urls(self, post_id: str, post_url: str) -> list[str]:
        """get the URLs of the comments of a given peertube video"""
        url = f"https://{self.webserver}/api/v1/videos/{post_id}/comment-threads"
        try:
            resp = self._http.get(url)
        except Exception as ex:
            logger.error(f"Error getting comments on video {post_id} from {post_url}. Exception: {ex}")
            return []

        if resp.status_code == 200:
            return [comment['url'] for comment in resp.json()['data']]

        logger.error(f"Error getting comments on video {post_id} from {post_url}. Status code: {resp.status_code}")
        return []
