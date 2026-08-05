from datetime import UTC, datetime

import pytest

from fedifetcher.api.peertube import PeerTubeApi, to_post
from fedifetcher.posts import Post
from fedifetcher.servers import ApiFlavour


@pytest.fixture
def api(http):
    return PeerTubeApi("video.example", http)

WHEN = "2026-01-01T00:00:00.000Z"


def built(post: Post | None) -> Post:
    """The builder drops what it cannot use; these tests are about the rest"""
    assert post is not None
    return post


def test_it_claims_the_peertube_flavour():
    assert PeerTubeApi.flavour is ApiFlavour.PEERTUBE


def test_user_posts_are_the_accounts_videos(api, http, reply):
    http.get.return_value = reply(200, {"data": [
        {"url": "https://video.example/videos/watch/1", "publishedAt": "2026-01-01T00:00:00Z"},
    ]})

    videos = api.fetch_user_posts("channel", "https://video.example/accounts/channel")

    assert [video.url for video in videos] == ["https://video.example/videos/watch/1"]
    assert http.get.call_args[0][0] == (
        "https://video.example/api/v1/accounts/channel/videos"
    )


def test_user_posts_give_up_on_an_error_status(api, http, reply):
    http.get.return_value = reply(500)
    assert api.fetch_user_posts("channel", "https://video.example/accounts/channel") is None


def test_user_posts_give_up_when_the_request_fails(api, http):
    http.get.side_effect = Exception("no route to host")
    assert api.fetch_user_posts("channel", "https://video.example/accounts/channel") is None


def test_context_is_the_comment_threads(api, http, reply):
    http.get.return_value = reply(200, {"data": [
        {"url": "https://video.example/videos/watch/1/comment/2"},
    ]})

    urls = api.fetch_context_urls("1", "https://video.example/videos/watch/1")

    assert urls == ["https://video.example/videos/watch/1/comment/2"]
    assert http.get.call_args[0][0] == (
        "https://video.example/api/v1/videos/1/comment-threads"
    )


def test_context_is_empty_on_an_error_status(api, http, reply):
    http.get.return_value = reply(500)
    assert api.fetch_context_urls("1", "https://video.example/videos/watch/1") == []


def test_context_is_empty_when_the_request_fails(api, http):
    http.get.side_effect = Exception("no route to host")
    assert api.fetch_context_urls("1", "https://video.example/videos/watch/1") == []


@pytest.mark.parametrize("privacy,expected", [(1, True), (2, True), (3, False)])
def test_a_peertube_video_says_who_may_watch_it_with_a_number(privacy, expected):
    video = built(to_post(
        {"url": "https://video.example/w/1", "publishedAt": WHEN,
         "privacy": {"id": privacy}}
    ))
    assert video.is_public is expected


def test_a_peertube_video_that_says_nothing_is_taken_to_be_public():
    video = built(to_post({"url": "https://video.example/w/1", "publishedAt": WHEN}))
    assert video.is_public


def test_a_video_falls_back_to_when_it_was_created():
    video = built(to_post({"url": "https://video.example/w/1", "createdAt": WHEN}))
    assert video.created_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_a_peertube_video_without_a_url_is_dropped():
    assert to_post({"publishedAt": WHEN}) is None


@pytest.mark.parametrize(
    "profile_url,endpoint",
    [
        # a channel and the account that owns it are asked for separately
        ("https://video.example/video-channels/a-channel", "video-channels/a-channel"),
        ("https://video.example/c/a-channel", "video-channels/a-channel"),
        ("https://video.example/accounts/someone", "accounts/someone"),
        ("https://video.example/a/someone", "accounts/someone"),
        # anything unrecognised is tried as an account, as it always was
        ("https://video.example/someone", "accounts/someone"),
    ],
)
def test_videos_are_asked_for_from_the_right_collection(api, http, reply, profile_url, endpoint):
    http.get.return_value = reply(200, {"data": []})
    name = profile_url.rsplit("/", 1)[1]

    api.fetch_user_posts(name, profile_url)

    assert http.get.call_args[0][0] == f"https://video.example/api/v1/{endpoint}/videos"
