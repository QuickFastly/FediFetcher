import json
import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from requests.models import Response

import find_posts
from find_posts import (
    add_context_urls,
    add_user_posts,
    filter_known_users,
    get_bookmarks,
    get_favourites,
    get_lemmy_comment_context,
    get_lemmy_urls,
    get_list_timeline,
    get_list_users,
    get_misskey_urls,
    get_new_follow_requests,
    get_new_followings,
    get_peertube_urls,
    get_toot_context,
    get_user_id,
    get_user_posts_mastodon,
    get_user_posts_misskey,
    user_has_opted_out,
)


@patch("find_posts.get_paginated_mastodon")
def test_get_bookmarks(mock_get_paginated_mastodon):
    http = Mock()
    server = "test_server"
    access_token = "test_token"
    max = 5

    get_bookmarks(server, access_token, max, http=http)

    mock_get_paginated_mastodon.assert_called_once_with(
        f"https://{server}/api/v1/bookmarks",
        max,
        {
            "Authorization": f"Bearer {access_token}",
        },
        http=http)


@pytest.mark.parametrize(
    "server,access_token,max",
    [
        ("test_server1", "test_token1", 2),
        ("test_server2", "test_token2", 10),
    ],
)
def test_get_bookmarks_parameterized(server, access_token, max):
    http = Mock()
    with patch("find_posts.get_paginated_mastodon") as mock_get_paginated_mastodon:
        get_bookmarks(server, access_token, max, http=http)
        mock_get_paginated_mastodon.assert_called_once_with(
            f"https://{server}/api/v1/bookmarks",
            max,
            {
                "Authorization": f"Bearer {access_token}",
            },
        http=http)


@patch("find_posts.get_paginated_mastodon")
def test_get_favourites(mock_get_paginated_mastodon):
    http = Mock()
    server = "some.server"
    access_token = "token123"
    max = 5
    expected_result = "result"

    mock_get_paginated_mastodon.return_value = expected_result

    result = get_favourites(server, access_token, max, http=http)

    mock_get_paginated_mastodon.assert_called_once_with(
        f"https://{server}/api/v1/favourites",
        max,
        {
            "Authorization": f"Bearer {access_token}",
        },
        http=http)
    assert result == expected_result


@patch("find_posts.get_user_posts")
@patch("find_posts.add_post_with_context")
@patch("find_posts.logger")
def test_add_user_posts(mock_logger, mock_add_post, mock_get_posts):
    config = Mock()
    http = Mock()
    server = "test_server"
    access_token = "test_token"
    followings = [
        {"acct": "user1", "url": "https://user1.com"},
        {"acct": "user2", "url": "https://test_server/user2"},
    ]
    known_followings = set()
    all_known_users = set()
    seen_urls = set()
    seen_hosts = set()

    mock_get_posts.return_value = [
        {"url": "https://user1.com/post1"},
        {"url": "https://user1.com/post2"},
    ]
    mock_add_post.return_value = True

    add_user_posts(
        server,
        access_token,
        followings,
        known_followings,
        all_known_users,
        seen_urls,
        seen_hosts,
        http=http, config=config)

    mock_get_posts.assert_called_once_with(
        followings[0], known_followings, server, seen_hosts,
        http=http)
    assert mock_add_post.call_count == 2
    assert len(seen_urls) == 2
    assert "user1" in known_followings
    assert "user1" in all_known_users
    mock_logger.info.assert_called_with("Added 2 posts for user user1 with 0 errors")


@patch("find_posts.get_user_posts")
@patch("find_posts.add_post_with_context")
@patch("find_posts.logger")
def test_add_user_posts_with_no_new_posts(mock_logger, mock_add_post, mock_get_posts):
    config = Mock()
    http = Mock()
    server = "test_server"
    access_token = "test_token"
    followings = [{"acct": "user1", "url": "https://user1.com"}]
    known_followings = set()
    all_known_users = set()
    seen_urls = {"https://user1.com/post1", "https://user1.com/post2"}
    seen_hosts = set()

    mock_get_posts.return_value = [
        {"url": "https://user1.com/post1"},
        {"url": "https://user1.com/post2"},
    ]
    mock_add_post.return_value = True

    add_user_posts(
        server,
        access_token,
        followings,
        known_followings,
        all_known_users,
        seen_urls,
        seen_hosts,
        http=http, config=config)

    mock_get_posts.assert_called_once_with(
        followings[0], known_followings, server, seen_hosts,
        http=http)
    mock_add_post.assert_not_called()
    assert len(seen_urls) == 2
    assert "user1" in known_followings
    assert "user1" in all_known_users


@pytest.fixture
def mock_functions():
    with patch(
        "find_posts.add_context_url", return_value=True
    ) as add_context_url, patch(
        "find_posts.parse_url", return_value=None
    ) as parse_url, patch(
        "find_posts.get_all_known_context_urls", return_value=[]
    ) as get_all_known_context_urls, patch(
        "find_posts.add_context_urls"
    ) as add_context_urls:
        yield add_context_url, parse_url, get_all_known_context_urls, add_context_urls


def test_add_post_with_context_post_not_added(mock_functions):
    config = Mock()
    http = Mock()
    add_context_url, _, _, _ = mock_functions
    add_context_url.return_value = False

    post = {"url": "http://example.com"}
    server = "server"
    access_token = "access_token"
    seen_urls = set()
    seen_hosts = set()

    result = find_posts.add_post_with_context(
        post, server, access_token, seen_urls, seen_hosts,
        http=http, config=config)

    add_context_url.assert_called_once_with(post["url"], server, access_token, http=http)

    assert result is False


def test_user_has_opted_out():
    assert not user_has_opted_out({"note": "I love robots"})
    assert user_has_opted_out({"note": "I love robots, nobot"})
    assert user_has_opted_out({"note": "/tags/nobot"})
    assert user_has_opted_out({"indexable": False})
    assert user_has_opted_out({"discoverable": False})


@pytest.fixture
def webserver():
    return "server.com"


@pytest.fixture
def userName():
    return "test_user"


def test_get_user_posts_mastodon_success(userName, webserver):
    http = Mock()
    with patch("find_posts.get_user_id") as mock_get_user_id:

        # Mocking get_user_id
        mock_get_user_id.return_value = 1234

        # Mocking get function call
        mock_response = Response()
        mock_response.status_code = 200
        mock_response._content = b'{"data": "Test"}'
        http.get.return_value = mock_response

        result = get_user_posts_mastodon(userName, webserver, http=http)
        assert result == {"data": "Test"}


def test_get_user_posts_mastodon_user_not_found(userName, webserver):
    http = Mock()
    with patch("find_posts.get_user_id") as mock_get_user_id:

        # Mocking get_user_id
        mock_get_user_id.return_value = 1234

        # Mocking get function call
        mock_response = Response()
        mock_response.status_code = 404
        http.get.return_value = mock_response

        result = get_user_posts_mastodon(userName, webserver, http=http)
        assert result is None


def test_get_user_posts_mastodon_error_status_code(userName, webserver):
    http = Mock()
    with patch("find_posts.get_user_id") as mock_get_user_id:

        # Mocking get_user_id
        mock_get_user_id.return_value = 1234

        # Mocking get function call
        mock_response = Response()
        mock_response.status_code = 500
        http.get.return_value = mock_response

        result = get_user_posts_mastodon(userName, webserver, http=http)
        assert result is None


@patch("find_posts.logger")
def test_get_user_posts_lemmy_community(mock_logger):
    http = Mock()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"posts": [{"post": {"ap_id": "test_url"}}]}
    http.get.return_value = mock_response

    result = find_posts.get_user_posts_lemmy(
        "test_user", "https://test.com/c/test_user", "test.com",
        http=http)

    assert result == [{"ap_id": "test_url", "url": "test_url"}]
    http.get.assert_called_once_with(
        "https://test.com/api/v3/post/list?community_name=test_user&sort=New&limit=50"
    )
    mock_logger.error.assert_not_called()


@patch("find_posts.logger")
def test_get_user_posts_lemmy_user(mock_logger):
    http = Mock()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "posts": [{"post": {"ap_id": "post_url"}}],
        "comments": [{"post": {"ap_id": "comment_url"}}],
    }
    http.get.return_value = mock_response

    result = find_posts.get_user_posts_lemmy(
        "test_user", "https://test.com/u/test_user", "test.com",
        http=http)

    assert result == [
        {"ap_id": "comment_url", "url": "comment_url"},
        {"ap_id": "post_url", "url": "post_url"},
    ]
    http.get.assert_called_once_with(
        "https://test.com/api/v3/user?username=test_user&sort=New&limit=50"
    )
    mock_logger.error.assert_not_called()


@patch("find_posts.logger")
def test_get_user_posts_peertube(mock_logger):
    http = Mock()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": "test_data"}
    http.get.return_value = mock_response

    result = find_posts.get_user_posts_peertube("test_user", "test_webserver", http=http)

    assert result == "test_data"
    http.get.assert_called_once_with(
        "https://test_webserver/api/v1/accounts/test_user/videos"
    )
    mock_logger.error.assert_not_called()


@patch("find_posts.logger")
def test_get_user_posts_misskey(mock_logger):
    http = Mock()
    mock_response = http.post.return_value
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"host": None, "id": "id1"},
        {"host": "host1", "id": "id2"},
    ]

    result = get_user_posts_misskey("username", "webserver", http=http)

    http.post.assert_called_with(
        "https://webserver/api/users/notes", {"userId": "id1", "limit": 40}
    )
    mock_logger.error.assert_not_called()
    assert result is not None


@patch("find_posts.get_paginated_mastodon")
@patch("find_posts.filter_known_users")
@patch("find_posts.logger")
def test_get_new_follow_requests(
    mock_logger, mock_filter_known_users, mock_get_paginated_mastodon
):
    http = Mock()
    mock_get_paginated_mastodon.return_value = ["request1", "request2"]
    mock_filter_known_users.return_value = ["request1"]

    result = get_new_follow_requests("server", "access_token", 10, ["known_following"], http=http)

    mock_get_paginated_mastodon.assert_called_with(
        "https://server/api/v1/follow_requests",
        10,
        {
            "Authorization": "Bearer access_token",
        },
        http=http)
    mock_filter_known_users.assert_called_with(
        ["request1", "request2"], ["known_following"]
    )
    mock_logger.info.assert_called_with("Got 2 follow_requests, 1 of which are new")
    assert result == ["request1"]


def test_filter_known_users():
    users = [
        {"acct": "user1"},
        {"acct": "user2"},
        {"acct": "user3"},
    ]
    known_users = ["user1", "user3"]

    filtered_users = filter_known_users(users, known_users)

    assert filtered_users == [{"acct": "user2"}]


def test_filter_known_users_no_known_users():
    users = [
        {"acct": "user1"},
        {"acct": "user2"},
        {"acct": "user3"},
    ]
    known_users = []

    filtered_users = filter_known_users(users, known_users)

    assert filtered_users == users


def test_filter_known_users_all_users_known():
    users = [
        {"acct": "user1"},
        {"acct": "user2"},
        {"acct": "user3"},
    ]
    known_users = ["user1", "user2", "user3"]

    filtered_users = filter_known_users(users, known_users)

    assert filtered_users == []


def test_filter_known_users_no_users():
    users = []
    known_users = ["user1", "user2", "user3"]

    filtered_users = filter_known_users(users, known_users)

    assert filtered_users == []


@patch("find_posts.get_paginated_mastodon")
@patch("find_posts.filter_known_users")
@patch("find_posts.logger")
def test_get_new_followers(
    mock_logger, mock_filter_known_users, mock_get_paginated_mastodon
):
    http = Mock()
    mock_get_paginated_mastodon.return_value = ["follower1", "follower2", "follower3"]
    mock_filter_known_users.return_value = ["follower2", "follower3"]

    server = "server"
    user_id = 1
    access_token = "access_token"
    max = 50
    known_followers = ["follower1"]

    expected_result = ["follower2", "follower3"]
    result = find_posts.get_new_followers(server, user_id, access_token, max, known_followers, http=http)

    mock_get_paginated_mastodon.assert_called_once_with(
        f"https://{server}/api/v1/accounts/{user_id}/followers", max, {
            "Authorization": f"Bearer {access_token}",
        },
        http=http)
    mock_filter_known_users.assert_called_once_with(
        ["follower1", "follower2", "follower3"], known_followers
    )
    mock_logger.info.assert_called_once_with("Got 3 followers, 2 of which are new")

    assert result == expected_result


@patch("find_posts.get_paginated_mastodon")
@patch("find_posts.filter_known_users")
@patch("find_posts.logger")
def test_get_new_followings(
    mock_logger, mock_filter_known_users, mock_get_paginated_mastodon
):
    http = Mock()
    mock_get_paginated_mastodon.return_value = ["user1", "user2", "user3"]
    mock_filter_known_users.return_value = ["user1", "user2"]
    result = get_new_followings("server", "100", "access_token", 5, "known_users", http=http)
    mock_get_paginated_mastodon.assert_called_with(
        "https://server/api/v1/accounts/100/following", 5, {
            "Authorization": "Bearer access_token",
        },
        http=http)
    mock_filter_known_users.assert_called_with(
        ["user1", "user2", "user3"], "known_users"
    )
    assert result == ["user1", "user2"]
    mock_logger.info.assert_called_with("Got 3 followings, 2 of which are new")


def test_get_user_id_with_username():
    http = Mock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "123"}
    http.get.return_value = mock_response
    result = get_user_id("server", user="test_user", http=http)
    http.get.assert_called_with(
        "https://server/api/v1/accounts/lookup?acct=test_user", headers={}
    )
    assert result == "123"


def test_get_user_id_with_access_token():
    http = Mock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "456"}
    http.get.return_value = mock_response
    result = get_user_id("server", access_token="test_token", http=http)
    http.get.assert_called_with(
        "https://server/api/v1/accounts/verify_credentials",
        headers={
            "Authorization": "Bearer test_token",
        },
    )
    assert result == "456"


def test_get_user_id_with_no_user_or_token():
    http = Mock()
    with pytest.raises(
        Exception,
        match="You must supply either a user name or an access token, to get an user ID",
    ):
        get_user_id("server", http=http)


def test_get_user_id_with_404_status_code():
    http = Mock()
    mock_response = MagicMock()
    mock_response.status_code = 404
    http.get.return_value = mock_response
    with pytest.raises(
        Exception, match="User test_user was not found on server server."
    ):
        get_user_id("server", user="test_user", http=http)


def test_get_user_id_with_non_200_or_404_status_code():
    http = Mock()
    mock_response = MagicMock()
    mock_response.status_code = 500
    http.get.return_value = mock_response
    with pytest.raises(
        Exception,
        match=re.escape(
            "Error getting URL https://server/api/v1/accounts/lookup?acct=test_user. Status code: 500"
        ),
    ):
        get_user_id("server", user="test_user", http=http)


@patch("find_posts.get_toots")
def test_get_timeline(mock_get_toots):
    http = Mock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = ["toot1", "toot2", "toot3"]
    mock_response.links = {}
    mock_get_toots.return_value = mock_response

    timeline = find_posts.get_timeline("server", "token", 5, http=http)

    mock_get_toots.assert_any_call("https://server/api/v1/timelines/home", "token", http=http)
    assert len(timeline) == 3


def test_get_reply_toots_error_status_code():
    http = Mock()
    mock_resp = Mock()
    mock_resp.status_code = 403
    http.get.return_value = mock_resp
    with pytest.raises(Exception) as e_info:
        find_posts.get_reply_toots(
            "test_user",
            "test_server",
            "test_token",
            ["some_seen_url"],
            datetime(2020, 1, 1),
        http=http)
        assert (
            "Make sure you have the read:statuses scope enabled for your access token."
            in str(e_info.value)
        )


@patch("find_posts.logger")
def test_toot_context_can_be_fetched_public(mock_logger):
    toot = {"visibility": "public", "uri": "sample_uri"}
    result = find_posts.toot_context_can_be_fetched(toot)
    assert result is True
    mock_logger.debug.assert_not_called()


@patch("find_posts.logger")
def test_toot_context_can_be_fetched_unlisted(mock_logger):
    toot = {"visibility": "unlisted", "uri": "sample_uri"}
    result = find_posts.toot_context_can_be_fetched(toot)
    assert result is True
    mock_logger.debug.assert_not_called()


@patch("find_posts.logger")
def test_toot_context_can_be_fetched_private(mock_logger):
    toot = {"visibility": "private", "uri": "sample_uri"}
    result = find_posts.toot_context_can_be_fetched(toot)
    assert result is False
    mock_logger.debug.assert_called_once_with(
        "Cannot fetch context of private toot sample_uri"
    )


toot_with_existing_uri = {
    "uri": "existing_uri",
    "lastSeen": datetime.now(),
    "created_at": datetime.now(),
}

toot_with_new_uri = {
    "uri": "new_uri",
    "lastSeen": datetime.now(),
    "created_at": datetime.now(),
}

recently_checked_context = {"existing_uri": toot_with_existing_uri}


@patch("find_posts.toot_has_parseable_url")
@patch("find_posts.parse_url")
@patch("find_posts.toot_context_can_be_fetched")
@patch("find_posts.toot_context_should_be_fetched")
@patch("find_posts.get_toot_context")
@patch("find_posts.logger", new_callable=Mock())
def test_get_all_known_context_urls(
    mock_logger,
    get_toot_context,
    toot_context_should_be_fetched,
    toot_context_can_be_fetched,
    parse_url,
    toot_has_parseable_url,
    monkeypatch,
):
    http = Mock()
    server = "test_server"
    reply_toots = [
        {"url": "test_url_1", "reblog": None, "uri": "test_uri_1"},
        {"url": "test_url_2", "reblog": {"url": "reblog_url_2"}, "uri": "test_uri_2"},
    ]
    parsed_urls = ["parsed_url_1", "parsed_url_2"]
    seen_hosts = ["seen_host_1", "seen_host_2"]
    monkeypatch.setattr(
        find_posts,
        "recently_checked_context",
        {
            "test_uri_1": {"lastSeen": datetime.now()},
            "test_uri_2": {"lastSeen": datetime.now()},
        },
        raising=False,
    )

    toot_has_parseable_url.return_value = True
    parse_url.return_value = ["parsed_url", "parsed_url_host"]
    toot_context_can_be_fetched.return_value = True
    toot_context_should_be_fetched.return_value = True
    get_toot_context.return_value = ["context_item_1", "context_item_2"]

    result_urls = find_posts.get_all_known_context_urls(
        server, reply_toots, parsed_urls, seen_hosts,
        http=http)

    # check if parseable url method called twice and the arguments correct
    assert toot_has_parseable_url.call_count == 2
    toot_has_parseable_url.assert_any_call(reply_toots[0], parsed_urls, http=http)
    toot_has_parseable_url.assert_any_call(reply_toots[1], parsed_urls, http=http)

    # check if parse url method was first called with the first toot url then with its reblog url
    parse_url.assert_any_call("test_url_1", parsed_urls, http)
    parse_url.assert_any_call("reblog_url_2", parsed_urls, http)

    # check if format of logger.info message is correct
    mock_logger.info.assert_called_once_with("Found 2 known context toots")

    # check if the correct context urls are returned
    assert result_urls == {"context_item_1", "context_item_2"}


def test_toot_has_parseable_url_with_parseable_url():
    http = Mock()
    toot = {"url": "http://test.com", "reblog": None}
    parsed_urls = []
    with patch("find_posts.parse_url", return_value="something") as mock_parse_url:
        assert find_posts.toot_has_parseable_url(toot, parsed_urls, http=http)
        mock_parse_url.assert_called_once_with("http://test.com", parsed_urls, http)


def test_toot_has_parseable_url_with_unparseable_url():
    http = Mock()
    toot = {"url": "http://test.com", "reblog": None}
    parsed_urls = []
    with patch("find_posts.parse_url", return_value=None) as mock_parse_url:
        assert not find_posts.toot_has_parseable_url(toot, parsed_urls, http=http)
        mock_parse_url.assert_called_once_with("http://test.com", parsed_urls, http)


def test_get_replied_toot_server_id_no_mentions():
    http = Mock()
    toot = {"in_reply_to_id": "1", "in_reply_to_account_id": "1", "mentions": []}
    assert find_posts.get_replied_toot_server_id("server", toot, {}, {}, http=http) is None


def test_get_replied_toot_server_id_no_url_redirect():
    http = Mock()
    http.get_redirect_url.return_value = None
    toot = {
        "in_reply_to_id": "1",
        "in_reply_to_account_id": "1",
        "mentions": [{"id": "1", "acct": "account"}],
    }
    assert find_posts.get_replied_toot_server_id("server", toot, {}, {}, http=http) is None


def test_get_replied_toot_server_id_with_url_redirect():
    http = Mock()
    http.get_redirect_url.return_value = "redirect_url"
    toot = {
        "in_reply_to_id": "1",
        "in_reply_to_account_id": "1",
        "mentions": [{"id": "1", "acct": "account"}],
    }
    with patch("find_posts.parse_url", return_value="match") as mock_parse:
        assert find_posts.get_replied_toot_server_id(
            "server", toot, {}, {}, http=http
        ) == ("redirect_url", "match")
        mock_parse.assert_called_once_with("redirect_url", {}, http)


def test_get_replied_toot_server_id_with_existing_replied_toot_server_ids():
    http = Mock()
    toot = {
        "in_reply_to_id": "1",
        "in_reply_to_account_id": "1",
        "mentions": [{"id": "1", "acct": "account"}],
    }
    replied_toot_server_ids = {"https://server/@account/1": ("url", "match")}

    assert find_posts.get_replied_toot_server_id(
        "server", toot, replied_toot_server_ids, {}, http=http
    ) == ("url", "match")


@patch("find_posts.get_server_info")
@patch("find_posts.logger")
def test_get_toot_context_no_server_info(mock_logger, mock_server_info):
    http = Mock()
    mock_server_info.return_value = None
    assert get_toot_context("server1", "toot1", "url1", {}, http=http) == []
    mock_logger.error.assert_called_once_with("server server1 not found for post")


@pytest.fixture
def mock_response_success():
    return_value = MagicMock()
    return_value.status_code = 200
    return_value.json.return_value = {
        "ancestors": [{"url": "https://abc.com/statuses/123456"}],
        "descendants": [{"url": "https://abc.com/statuses/789012"}],
    }
    return return_value


@pytest.fixture
def mock_response_fail():
    return_value = MagicMock()
    return_value.status_code = 404
    return return_value


@patch("find_posts.logger")
def test_get_mastodon_urls_request_fail(mock_logger, mock_response_fail):
    http = Mock()
    http.get.return_value = mock_response_fail

    result = find_posts.get_mastodon_urls(
        "abc.com", "123456", "https://abc.com/statuses/123456",
        http=http)

    assert list(result) == []
    mock_logger.error.assert_called_once()


@patch("find_posts.logger")
def test_get_mastodon_urls_exception(mock_logger):
    http = Mock()
    http.get.side_effect = Exception("Test exception")

    result = find_posts.get_mastodon_urls(
        "abc.com", "123456", "https://abc.com/statuses/123456",
        http=http)

    assert list(result) == []
    mock_logger.error.assert_called_once()


@patch("find_posts.get_lemmy_comment_context")
@patch("find_posts.get_lemmy_comments_urls")
@patch("find_posts.logger")
def test_get_lemmy_urls_comment(
    mock_logger, mock_get_lemmy_comments_urls, mock_get_lemmy_comment_context
):
    http = Mock()
    webserver = "webserver"
    toot_id = "toot_id"
    toot_url = "/comment/"

    get_lemmy_urls(webserver, toot_id, toot_url, http=http)

    mock_get_lemmy_comment_context.assert_called_once_with(webserver, toot_id, toot_url, http=http)
    mock_logger.error.assert_not_called()


@patch("find_posts.get_lemmy_comment_context")
@patch("find_posts.get_lemmy_comments_urls")
@patch("find_posts.logger")
def test_get_lemmy_urls_post(
    mock_logger, mock_get_lemmy_comments_urls, mock_get_lemmy_comment_context
):
    http = Mock()
    webserver = "webserver"
    toot_id = "toot_id"
    toot_url = "/post/"

    get_lemmy_urls(webserver, toot_id, toot_url, http=http)

    mock_get_lemmy_comments_urls.assert_called_once_with(webserver, toot_id, toot_url, http=http)
    mock_logger.error.assert_not_called()


@patch("find_posts.get_lemmy_comment_context")
@patch("find_posts.get_lemmy_comments_urls")
@patch("find_posts.logger")
def test_get_lemmy_urls_else(
    mock_logger, mock_get_lemmy_comments_urls, mock_get_lemmy_comment_context
):
    http = Mock()
    webserver = "webserver"
    toot_id = "toot_id"
    toot_url = "/else/"

    result = get_lemmy_urls(webserver, toot_id, toot_url, http=http)

    assert result == []
    mock_get_lemmy_comments_urls.assert_not_called()
    mock_get_lemmy_comment_context.assert_not_called()
    mock_logger.error.assert_called_once_with(f"unknown lemmy url type {toot_url}")


@patch("find_posts.logger")
def test_get_lemmy_comment_context_get_fail(mock_logger):
    http = Mock()
    http.get.side_effect = Exception

    assert (
        get_lemmy_comment_context("webserver.com", "test_toot_id", "test_toot_url", http=http)
        == []
    )

    http.get.assert_called_once_with(
        "https://webserver.com/api/v3/comment?id=test_toot_id"
    )
    mock_logger.error.assert_called_once()


@patch("find_posts.logger")
def test_get_lemmy_comment_context_parse_fail(mock_logger):
    http = Mock()
    http.get.return_value.status_code = 200
    http.get.return_value.json.return_value = {"invalid_key": "invalid_value"}

    assert (
        get_lemmy_comment_context("webserver.com", "test_toot_id", "test_toot_url", http=http)
        == []
    )

    http.get.assert_called_once_with(
        "https://webserver.com/api/v3/comment?id=test_toot_id"
    )
    mock_logger.error.assert_called_once()


def test_get_peertube_urls_success():
    http = Mock()
    if True:
        mock_resp = Response()
        mock_resp.status_code = 200
        mock_resp._content = json.dumps(
            {"data": [{"url": "http://example.com/1"}, {"url": "http://example.com/2"}]}
        ).encode("utf-8")

        http.get.return_value = mock_resp

        urls = get_peertube_urls("example.com", "123", "http://toot_url.com", http=http)
        http.get.assert_called_once_with(
            "https://example.com/api/v1/videos/123/comment-threads"
        )
        assert urls == ["http://example.com/1", "http://example.com/2"]


@patch("find_posts.logger")
def test_get_peertube_urls_exception(mock_logger):
    http = Mock()
    if True:
        http.get.side_effect = Exception("Test exception")

        urls = get_peertube_urls("example.com", "123", "http://toot_url.com", http=http)
        http.get.assert_called_once_with(
            "https://example.com/api/v1/videos/123/comment-threads"
        )
        mock_logger.error.assert_called_once_with(
            "Error getting comments on video 123 from http://toot_url.com. Exception: Test exception"
        )
        assert urls == []


def test_get_misskey_urls_success():
    http = Mock()
    with patch(
        "find_posts.logger"
    ) as mock_logger:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "123"}, {"id": "456"}]
        http.post.return_value = mock_response
        result = get_misskey_urls("testserver", "1", "testurl", http=http)
        expected = [
            "https://testserver/notes/123",
            "https://testserver/notes/456",
            "https://testserver/notes/123",
            "https://testserver/notes/456",
        ]
        assert result == expected
        assert http.post.call_count == 2
        assert mock_logger.debug.call_count == 2


def test_get_misskey_urls_post_error():
    http = Mock()
    with patch(
        "find_posts.logger"
    ) as mock_logger:
        http.post.side_effect = Exception("Error")
        result = get_misskey_urls("testserver", "1", "testurl", http=http)
        expected = []
        assert result == expected
        assert http.post.call_count == 1
        assert mock_logger.error.call_count == 1


def test_get_misskey_urls_non_200_response():
    http = Mock()
    with patch(
        "find_posts.logger"
    ) as mock_logger:
        mock_response = MagicMock()
        mock_response.status_code = 404
        http.post.return_value = mock_response
        result = get_misskey_urls("testserver", "1", "testurl", http=http)
        expected = []
        assert result == expected
        assert mock_logger.error.called


def test_get_misskey_urls_json_error():
    http = Mock()
    with patch(
        "find_posts.logger"
    ) as mock_logger:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = Exception("JSON Error")
        http.post.return_value = mock_response
        result = get_misskey_urls("testserver", "1", "testurl", http=http)
        expected = []
        assert result == expected
        assert http.post.call_count == 2
        assert mock_logger.error.call_count == 2


@patch("find_posts.add_context_url", return_value=False)
@patch("find_posts.logger")
def test_add_context_urls_all_fail(mock_logger, mock_add_context_url):
    http = Mock()
    server = "test_server"
    access_token = "test_token"
    context_urls = ["url1", "url2", "url3", "url4"]
    seen_urls = set()

    add_context_urls(server, access_token, context_urls, seen_urls, http=http)

    assert mock_add_context_url.call_count == 4
    assert len(seen_urls) == 0
    assert (
        mock_logger.info.call_args[0][0]
        == "Added 0 new context toots (with 4 failures)"
    )


@patch("find_posts.add_context_url", return_value=True)
@patch("find_posts.logger")
def test_add_context_urls_all_success(mock_logger, mock_add_context_url):
    http = Mock()
    server = "test_server"
    access_token = "test_token"
    context_urls = ["url1", "url2", "url3", "url4"]
    seen_urls = set()

    add_context_urls(server, access_token, context_urls, seen_urls, http=http)

    assert mock_add_context_url.call_count == 4
    assert len(seen_urls) == 4
    assert "url1" in seen_urls
    assert "url2" in seen_urls
    assert "url3" in seen_urls
    assert "url4" in seen_urls
    assert (
        mock_logger.info.call_args[0][0]
        == "Added 4 new context toots (with 0 failures)"
    )


class MockResponse:
    def __init__(self, status_code, links=None, json_data=None):
        self.status_code = status_code
        self.links = links
        self.json_data = json_data

    def json(self):
        return self.json_data


def test_add_context_url():
    http = Mock()
    http.get.return_value = MockResponse(200)

    assert find_posts.add_context_url("test-url", "test-server", "test-token", http=http)

    http.get.assert_called_once()
    assert (
        http.get.call_args[0][0]
        == "https://test-server/api/v2/search?q=test-url&resolve=true&limit=1"
    )

    http.get.return_value = MockResponse(403)
    assert not find_posts.add_context_url("test-url", "test-server", "test-token", http=http)


def test_get_paginated_mastodon():
    http = Mock()
    json_data = [{"created_at": "2022-02-18T05:31:00.000Z"} for _ in range(10)]
    http.get.return_value = MockResponse(200, json_data=json_data)

    assert len(find_posts.get_paginated_mastodon("test-url", 10, http=http)) == 10
    http.get.assert_called_once()


@pytest.mark.parametrize("status", [401, 403, 500])
def test_get_paginated_mastodon_error_status(status):
    http = Mock()
    http.get.return_value = MockResponse(status)
    with pytest.raises(Exception):
        find_posts.get_paginated_mastodon("test-url", 10, http=http)
@patch("find_posts.get_paginated_mastodon")
def test_get_user_lists(mock_get_paginated_mastodon):
    http = Mock()
    mock_get_paginated_mastodon.return_value = "Test value"

    server = "test-server"
    token = "test-token"
    expected_url = f"https://{server}/api/v1/lists"
    expected_limit = 99
    expected_headers = {"Authorization": f"Bearer {token}"}

    result = find_posts.get_user_lists(server, token, http=http)

    mock_get_paginated_mastodon.assert_called_once_with(
        expected_url, expected_limit, expected_headers,
        http=http)

    assert result == "Test value"


@patch("find_posts.get_paginated_mastodon")
@patch("find_posts.logger")
def test_get_list_timeline(mock_logger, mock_get_paginated_mastodon):
    http = Mock()
    # Arrange
    server = "mastodon.social"
    list_info = {"id": 123, "title": "test_list"}
    token = "token12345"
    max = 100
    mock_get_paginated_mastodon.return_value = ["post1", "post2"]

    # Act
    result = get_list_timeline(server, list_info, token, max, http=http)

    # Assert
    mock_get_paginated_mastodon.assert_called_once_with(
        f"https://{server}/api/v1/timelines/list/{list_info['id']}",
        max,
        {
            "Authorization": f"Bearer {token}",
        },
        http=http)
    mock_logger.info.assert_called_once_with(
        f"Found {len(mock_get_paginated_mastodon.return_value)} toots in list {list_info['title']}"
    )
    assert len(result) == 2
    assert result == ["post1", "post2"]


@patch("find_posts.get_paginated_mastodon")
@patch("find_posts.logger")
def test_get_list_users(mock_logger, mock_get_paginated_mastodon):
    http = Mock()
    # define mock values
    mock_server = "mock_server"
    mock_list = {"id": "mock_id", "title": "mock_title"}
    mock_token = "mock_token"
    mock_max = 5
    mock_accounts = ["account1", "account2", "account3"]

    # setup expected url
    expected_url = f"https://{mock_server}/api/v1/lists/{mock_list['id']}/accounts"

    # Mock the return value of get_paginated_mastodon
    mock_get_paginated_mastodon.return_value = mock_accounts

    # Call the function with the mock values
    result = get_list_users(mock_server, mock_list, mock_token, mock_max, http=http)

    # Assert the function called get_paginated_mastodon with correct arguments
    mock_get_paginated_mastodon.assert_called_once_with(
        expected_url, mock_max, {"Authorization": f"Bearer {mock_token}"},
        http=http)

    # Assert the function called logger.info with correct arguments
    mock_logger.info.assert_called_once_with(
        f"Found {len(mock_accounts)} accounts in list {mock_list['title']}"
    )

    # Assert the function returned correct result
    assert result == mock_accounts


@patch("find_posts.get_all_known_context_urls")
@patch("find_posts.add_context_urls")
@patch("find_posts.add_user_posts")
@patch("find_posts.filter_known_users")
def test_fetch_timeline_context_with_empty_posts(
    mock_filter_known_users,
    mock_add_user_posts,
    mock_add_context_urls,
    mock_get_all_known_context_urls,
):
    # Arrange
    http = Mock()
    config = SimpleNamespace(server="server_test", backfill_mentioned_users=False)
    timeline_posts = []
    token, parsed_urls, seen_hosts = "", [], []
    seen_urls, all_known_users, recently_checked_users = [], [], []

    # Act
    find_posts.fetch_timeline_context(
        timeline_posts,
        token,
        parsed_urls,
        seen_hosts,
        seen_urls,
        all_known_users,
        recently_checked_users,
        http=http, config=config)

    # Assert
    mock_get_all_known_context_urls.assert_called_once_with(
        config.server, timeline_posts, parsed_urls, seen_hosts,
        http=http)
    mock_add_context_urls.assert_called_once_with(
        config.server, token, mock_get_all_known_context_urls.return_value, seen_urls,
        http=http)
    assert not mock_filter_known_users.called
    assert not mock_add_user_posts.called
