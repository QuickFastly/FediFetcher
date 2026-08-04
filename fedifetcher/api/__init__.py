from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from fedifetcher.api.lemmy import LemmyApi
from fedifetcher.api.mastodon import MastodonApi
from fedifetcher.api.misskey import MisskeyApi
from fedifetcher.api.peertube import PeerTubeApi
from fedifetcher.servers import ApiFlavour, ServerInfo

if TYPE_CHECKING:
    from fedifetcher.http import HttpClient

logger = logging.getLogger("FediFetcher")


@runtime_checkable
class FediverseApi(Protocol):
    """What FediFetcher needs from a server, however that server speaks"""

    flavour: ClassVar[ApiFlavour]

    def fetch_user_posts(
        self, username: str, profile_url: str
    ) -> list[dict[str, Any]] | None:
        """Recent posts by an account, or None if they could not be read"""
        ...

    def fetch_context_urls(self, post_id: str, post_url: str) -> list[str]:
        """URLs of the posts around a post: its ancestors and replies"""
        ...


# tried in order, so a server claiming several APIs gets the best supported one
CLIENTS: tuple[type[FediverseApi], ...] = (
    MastodonApi,
    LemmyApi,
    MisskeyApi,
    PeerTubeApi,
)


def client_for(server: ServerInfo, http: HttpClient) -> FediverseApi | None:
    """Pick a client that can talk to this server, if we know how"""
    for client in CLIENTS:
        if server.supports(client.flavour):
            return client(server.webserver, http)  # type: ignore[call-arg]

    logger.error(f'server api unknown for {server.webserver}')
    return None


__all__ = [
    "CLIENTS",
    "FediverseApi",
    "LemmyApi",
    "MastodonApi",
    "MisskeyApi",
    "PeerTubeApi",
    "client_for",
]
