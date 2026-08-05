from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, cast

from fedifetcher.servers import ApiFlavour

if TYPE_CHECKING:
    from fedifetcher.http import HttpClient

logger = logging.getLogger("FediFetcher")


class PeerTubeApi:
    """PeerTube, where posts are videos and replies are comment threads"""

    flavour: ClassVar[ApiFlavour] = ApiFlavour.PEERTUBE

    def __init__(self, webserver: str, http: HttpClient) -> None:
        self.webserver = webserver
        self._http = http

    def fetch_user_posts(
        self, username: str, profile_url: str
    ) -> list[dict[str, Any]] | None:
        try:
            url = f'https://{self.webserver}/api/v1/accounts/{username}/videos'
            response = self._http.get(url)
            if response.status_code == 200:
                return cast("list[dict[str, Any]]", response.json()['data'])

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
