from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from fedifetcher.servers import ApiFlavour

if TYPE_CHECKING:
    from fedifetcher.http import HttpClient

logger = logging.getLogger("FediFetcher")


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
            return response.json()['id']
        elif response.status_code == 404:
            raise Exception(
                f"User {user} was not found on server {self.webserver}."
            )
        else:
            raise Exception(
                f"Error getting URL {url}. Status code: {response.status_code}"
            )

    def fetch_user_posts(
        self, username: str, profile_url: str
    ) -> list[dict[str, Any]] | None:
        try:
            user_id = self.user_id(username)
        except Exception as ex:
            logger.error(f"Error getting user ID for user {username}: {ex}")
            return None

        try:
            url = f"https://{self.webserver}/api/v1/accounts/{user_id}/statuses?limit=40"
            response = self._http.get(url)

            if(response.status_code == 200):
                return response.json()
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
