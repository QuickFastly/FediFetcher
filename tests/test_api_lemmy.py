import pytest

from fedifetcher.api.lemmy import LemmyApi
from fedifetcher.servers import ApiFlavour


@pytest.fixture
def api(http):
    return LemmyApi("lemmy.world", http)


def test_it_claims_the_lemmy_flavour():
    assert LemmyApi.flavour is ApiFlavour.LEMMY


def test_community_posts_are_read_from_the_community_endpoint(api, http, reply):
    http.get.return_value = reply(200, {"posts": [{"post": {"ap_id": "https://lemmy.world/post/1"}}]})

    posts = api.fetch_user_posts("news", "https://lemmy.world/c/news")

    assert posts == [{"ap_id": "https://lemmy.world/post/1", "url": "https://lemmy.world/post/1"}]
    assert "community_name=news" in http.get.call_args[0][0]


def test_account_posts_combine_posts_and_comments(api, http, reply):
    http.get.return_value = reply(200, {
        "comments": [{"post": {"ap_id": "https://lemmy.world/comment/1"}}],
        "posts": [{"post": {"ap_id": "https://lemmy.world/post/2"}}],
    })

    posts = api.fetch_user_posts("someone", "https://lemmy.world/u/someone")

    assert [p["url"] for p in posts] == [
        "https://lemmy.world/comment/1",
        "https://lemmy.world/post/2",
    ]


def test_an_unrecognised_profile_url_yields_nothing(api, http):
    assert api.fetch_user_posts("someone", "https://lemmy.world/x/someone") is None
    http.get.assert_not_called()


def test_user_posts_give_up_when_the_request_fails(api, http):
    http.get.side_effect = Exception("no route to host")
    assert api.fetch_user_posts("someone", "https://lemmy.world/u/someone") is None


def test_post_context_lists_the_post_and_its_comments(api, http, reply):
    http.get.side_effect = [
        reply(200, {"post_view": {"counts": {"comments": 2}, "post": {"ap_id": "https://lemmy.world/post/5"}}}),
        reply(200, {"comments": [
            {"comment": {"ap_id": "https://lemmy.world/comment/6"}},
            {"comment": {"ap_id": "https://lemmy.world/comment/7"}},
        ]}),
    ]

    urls = api.fetch_context_urls("5", "https://lemmy.world/post/5")

    assert urls == [
        "https://lemmy.world/post/5",
        "https://lemmy.world/comment/6",
        "https://lemmy.world/comment/7",
    ]


def test_a_post_without_comments_has_no_context(api, http, reply):
    http.get.return_value = reply(200, {"post_view": {"counts": {"comments": 0}, "post": {}}})
    assert api.fetch_context_urls("5", "https://lemmy.world/post/5") == []


def test_comment_context_resolves_to_its_post(api, http, reply):
    http.get.side_effect = [
        reply(200, {"comment_view": {"comment": {"post_id": "5"}}}),
        reply(200, {"post_view": {"counts": {"comments": 1}, "post": {"ap_id": "https://lemmy.world/post/5"}}}),
        reply(200, {"comments": [{"comment": {"ap_id": "https://lemmy.world/comment/6"}}]}),
    ]

    urls = api.fetch_context_urls("6", "https://lemmy.world/comment/6")

    assert urls == ["https://lemmy.world/post/5", "https://lemmy.world/comment/6"]


def test_comment_context_gives_up_on_an_error_status(api, http, reply):
    http.get.return_value = reply(500)
    assert api.fetch_context_urls("6", "https://lemmy.world/comment/6") == []


def test_comment_context_gives_up_when_the_body_makes_no_sense(api, http, reply):
    http.get.return_value = reply(200, {"unexpected": True})
    assert api.fetch_context_urls("6", "https://lemmy.world/comment/6") == []


def test_an_unrecognised_post_url_yields_no_context(api, http):
    assert api.fetch_context_urls("5", "https://lemmy.world/x/5") == []
    http.get.assert_not_called()
