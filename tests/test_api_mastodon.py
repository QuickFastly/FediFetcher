import pytest

from fedifetcher.api.mastodon import MastodonApi
from fedifetcher.servers import ApiFlavour


@pytest.fixture
def api(http):
    return MastodonApi("example.social", http)


def test_it_claims_the_mastodon_flavour():
    assert MastodonApi.flavour is ApiFlavour.MASTODON


def test_user_id_is_looked_up_by_name(api, http, reply):
    http.get.return_value = reply(200, {"id": "1234"})

    assert api.user_id("someone") == "1234"

    assert http.get.call_args[0][0] == (
        "https://example.social/api/v1/accounts/lookup?acct=someone"
    )


def test_user_id_falls_back_to_the_token_owner(api, http, reply):
    http.get.return_value = reply(200, {"id": "1234"})

    assert api.user_id(access_token="token") == "1234"

    assert http.get.call_args[0][0] == (
        "https://example.social/api/v1/accounts/verify_credentials"
    )
    assert http.get.call_args.kwargs["headers"]["Authorization"] == "Bearer token"


def test_user_id_needs_something_to_go_on(api):
    with pytest.raises(Exception, match="user name or an access token"):
        api.user_id()


def test_user_id_reports_an_unknown_user(api, http, reply):
    http.get.return_value = reply(404)
    with pytest.raises(Exception, match="was not found"):
        api.user_id("nobody")


def test_user_id_reports_other_failures(api, http, reply):
    http.get.return_value = reply(500)
    with pytest.raises(Exception, match="Status code: 500"):
        api.user_id("someone")


def test_user_posts_are_fetched_for_the_resolved_id(api, http, reply):
    http.get.side_effect = [
        reply(200, {"id": "1234"}),
        reply(200, [{"url": "https://example.social/@someone/1"}]),
    ]

    posts = api.fetch_user_posts("someone", "https://example.social/@someone")

    assert posts == [{"url": "https://example.social/@someone/1"}]
    assert http.get.call_args[0][0] == (
        "https://example.social/api/v1/accounts/1234/statuses?limit=40"
    )


def test_user_posts_give_up_when_the_id_cannot_be_found(api, http, reply):
    http.get.return_value = reply(404)
    assert api.fetch_user_posts("nobody", "https://example.social/@nobody") is None


def test_user_posts_give_up_on_an_error_status(api, http, reply):
    http.get.side_effect = [reply(200, {"id": "1234"}), reply(500)]
    assert api.fetch_user_posts("someone", "https://example.social/@someone") is None


def test_context_gathers_ancestors_and_descendants(api, http, reply):
    http.get.return_value = reply(200, {
        "ancestors": [{"url": "https://example.social/@a/1"}],
        "descendants": [{"url": "https://example.social/@b/2"}],
    })

    urls = api.fetch_context_urls("9", "https://example.social/@a/9")

    assert urls == ["https://example.social/@a/1", "https://example.social/@b/2"]
    assert http.get.call_args[0][0] == (
        "https://example.social/api/v1/statuses/9/context"
    )


def test_context_is_empty_on_an_error_status(api, http, reply):
    http.get.return_value = reply(500)
    assert api.fetch_context_urls("9", "https://example.social/@a/9") == []


def test_context_is_empty_when_the_request_fails(api, http):
    http.get.side_effect = Exception("no route to host")
    assert api.fetch_context_urls("9", "https://example.social/@a/9") == []


def test_context_is_empty_when_the_body_makes_no_sense(api, http, reply):
    http.get.return_value = reply(200, {"unexpected": True})
    assert api.fetch_context_urls("9", "https://example.social/@a/9") == []
