from datetime import datetime

import pytest

from fedifetcher.api import CLIENTS, FediverseApi, LemmyApi, MastodonApi, client_for
from fedifetcher.servers import ApiFlavour, ServerInfo


def server(software):
    return ServerInfo.from_nodeinfo(
        "example.social",
        {"protocols": ["activitypub"], "software": {"name": software, "version": "1"}},
    )


@pytest.mark.parametrize(
    "software,expected",
    [
        ("mastodon", MastodonApi),
        ("lemmy", LemmyApi),
    ],
)
def test_a_client_is_chosen_by_what_the_server_speaks(software, expected, http):
    assert isinstance(client_for(server(software), http), expected)


def test_a_server_we_cannot_talk_to_gets_no_client(http):
    assert client_for(server("something-new"), http) is None


def test_the_chosen_client_is_bound_to_the_web_domain(http):
    client = client_for(server("mastodon"), http)
    assert isinstance(client, MastodonApi)
    assert client.webserver == "example.social"


def test_mastodon_wins_when_a_server_claims_more_than_one_api(http):
    info = ServerInfo(
        webserver="example.social",
        software="hybrid",
        version="1",
        apis=frozenset({ApiFlavour.MISSKEY, ApiFlavour.MASTODON}),
        last_checked=datetime.now(),
    )
    assert isinstance(client_for(info, http), MastodonApi)


def test_every_client_satisfies_the_protocol(http):
    for client in CLIENTS:
        assert isinstance(client("example.social", http), FediverseApi)  # type: ignore[call-arg]


def test_every_flavour_has_a_client():
    assert {client.flavour for client in CLIENTS} == set(ApiFlavour)
