from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, cast

from fedifetcher.servers import ApiFlavour

if TYPE_CHECKING:
    from fedifetcher.http import HttpClient

logger = logging.getLogger("FediFetcher")


class MisskeyApi:
    """Misskey and its forks: Calckey, Firefish, Foundkey, Sharkey"""

    flavour: ClassVar[ApiFlavour] = ApiFlavour.MISSKEY

    def __init__(self, webserver: str, http: HttpClient) -> None:
        self.webserver = webserver
        self._http = http

    def fetch_user_posts(
        self, username: str, profile_url: str
    ) -> list[dict[str, Any]] | None:
        user_id = self._find_user_id(username)
        if user_id is None:
            return None

        try:
            url = f'https://{self.webserver}/api/users/notes'
            resp = self._http.post(url, { 'userId': user_id, 'limit': 40 })

            if resp.status_code == 200:
                notes: list[dict[str, Any]] = resp.json()
                for note in notes:
                    if note.get('url') is None:
                        # add this to make it look like Mastodon status objects
                        note.update({ 'url': f"https://{self.webserver}/notes/{note['id']}" })
                return notes

            logger.error(f"Error getting posts by user {username} from {self.webserver}. Status Code: {resp.status_code}")
            return None
        except Exception as ex:
            logger.error(f"Error getting posts by user {username} from {self.webserver}. Exception: {ex}")
            return None

    def _find_user_id(self, username: str) -> str | None:
        # query user info via search api
        # we could filter by host but there's no way to limit that to just the main host on firefish currently
        # on misskey it works if you supply '.' as the host but firefish does not
        try:
            url = f'https://{self.webserver}/api/users/search-by-username-and-host'
            resp = self._http.post(url, { 'username': username })

            if resp.status_code != 200:
                logger.error(f"Error finding user {username} from {self.webserver}. Status Code: {resp.status_code}")
                return None

            for user in resp.json():
                if user['host'] is None:
                    return cast("str", user['id'])
        except Exception as ex:
            logger.error(f"Error finding user {username} from {self.webserver}. Exception: {ex}")
            return None

        logger.error(f'Error finding user {username} from {self.webserver}: user not found on server in search')
        return None

    def fetch_context_urls(self, post_id: str, post_url: str) -> list[str]:
        """get the URLs of the comments of a given misskey post"""
        urls: list[str] = []
        for endpoint, params in (
            ('children', { 'noteId': post_id, 'limit': 100, 'depth': 12 }),
            ('conversation', { 'noteId': post_id, 'limit': 100 }),
        ):
            url = f"https://{self.webserver}/api/notes/{endpoint}"
            try:
                resp = self._http.post(url, params)
            except Exception as ex:
                logger.error(f"Error getting post {post_id} from {post_url}. Exception: {ex}")
                return []

            if resp.status_code != 200:
                logger.error(f"Error getting post {post_id} from {post_url}. Status Code: {resp.status_code}")
                continue

            try:
                res = resp.json()
                logger.debug(f"Got {endpoint} for misskey post {post_url}")
                urls.extend(
                    f'https://{self.webserver}/notes/{note["id"]}' for note in res
                )
            except Exception as ex:
                logger.error(f"Error parsing post {post_id} from {post_url}. Exception: {ex}")

        return urls
