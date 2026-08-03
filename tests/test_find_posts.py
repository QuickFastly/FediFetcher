from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

import find_posts
from fedifetcher.state import TimestampedSet
from find_posts import (
    add_user_posts,
    filter_known_users,
    get_toot_context,
)


@patch("find_posts.get_user_posts")
@patch("find_posts.add_post_with_context")
@patch("find_posts.logger")
def test_add_user_posts(mock_logger, mock_add_post, mock_get_posts, state, home):
    config = Mock()
    http = Mock()
    followings = [
        {"acct": "user1", "url": "https://user1.com"},
        {"acct": "user2", "url": "https://test_server/user2"},
    ]
    known_followings = TimestampedSet()

    mock_get_posts.return_value = [
        {"url": "https://user1.com/post1"},
        {"url": "https://user1.com/post2"},
    ]
    mock_add_post.return_value = True

    add_user_posts(
        home, followings, known_followings, http=http, config=config, state=state
    )

    mock_get_posts.assert_called_once_with(
        followings[0], known_followings, home.server, http=http, state=state
    )
    assert mock_add_post.call_count == 2
    assert len(state.seen_urls) == 2
    assert "user1" in known_followings
    assert "user1" in state.all_known_users
    mock_logger.info.assert_called_with("Added 2 posts for user user1 with 0 errors")


@patch("find_posts.get_user_posts")
@patch("find_posts.add_post_with_context")
@patch("find_posts.logger")
def test_add_user_posts_with_no_new_posts(mock_logger, mock_add_post, mock_get_posts, state, home):
    config = Mock()
    http = Mock()
    followings = [{"acct": "user1", "url": "https://user1.com"}]
    known_followings = TimestampedSet()
    state.seen_urls.update(["https://user1.com/post1", "https://user1.com/post2"])

    mock_get_posts.return_value = [
        {"url": "https://user1.com/post1"},
        {"url": "https://user1.com/post2"},
    ]
    mock_add_post.return_value = True

    add_user_posts(
        home, followings, known_followings, http=http, config=config, state=state
    )

    mock_get_posts.assert_called_once_with(
        followings[0], known_followings, home.server, http=http, state=state
    )
    mock_add_post.assert_not_called()
    assert len(state.seen_urls) == 2
    assert "user1" in known_followings
    assert "user1" in state.all_known_users


def test_add_post_with_context_post_not_added(state, home, http):
    home.resolve.return_value = False
    config = Mock()

    post = {"url": "http://example.com"}
    result = find_posts.add_post_with_context(
        post, home, http=http, config=config, state=state
    )

    home.resolve.assert_called_once_with(post["url"])
    assert result is False


@pytest.fixture
def webserver():
    return "server.com"


@pytest.fixture
def userName():
    return "test_user"


















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


@patch("find_posts.get_toot_context")
@patch("find_posts.parse_url")
@patch("find_posts.toot_has_parseable_url")
def test_get_all_known_context_urls(
    toot_has_parseable_url, parse_url, get_toot_context, state, http
):
    reply_toots = [
        {"url": "test_url_1", "reblog": None, "uri": "test_uri_1",
         "visibility": "public", "created_at": "2026-01-01T00:00:00+00:00"},
        {"url": "test_url_2", "reblog": {"url": "reblog_url_2"}, "uri": "test_uri_2",
         "visibility": "public", "created_at": "2026-01-01T00:00:00+00:00"},
    ]
    toot_has_parseable_url.return_value = True
    parse_url.return_value = ("parsed_host", "parsed_id")
    get_toot_context.return_value = ["context_item_1", "context_item_2"]

    urls = find_posts.get_all_known_context_urls(
        "test_server", reply_toots, http=http, state=state
    )

    assert urls == {"context_item_1", "context_item_2"}
    assert toot_has_parseable_url.call_count == 2
    assert get_toot_context.call_count == 2
    # both posts are now remembered, so a second pass would not refetch them
    assert "test_uri_1" in state.recently_checked_context
    assert not find_posts.get_all_known_context_urls(
        "test_server", reply_toots, http=http, state=state
    )


def test_toot_has_parseable_url_with_parseable_url(state):
    http = Mock()
    toot = {"url": "http://test.com", "reblog": None}
    with patch("find_posts.parse_url", return_value="something") as mock_parse_url:
        assert find_posts.toot_has_parseable_url(toot, http=http, state=state)
        mock_parse_url.assert_called_once_with("http://test.com", state.parsed_urls, http)


def test_toot_has_parseable_url_with_unparseable_url(state):
    http = Mock()
    toot = {"url": "http://test.com", "reblog": None}
    with patch("find_posts.parse_url", return_value=None) as mock_parse_url:
        assert not find_posts.toot_has_parseable_url(toot, http=http, state=state)
        mock_parse_url.assert_called_once_with("http://test.com", state.parsed_urls, http)


def test_get_replied_toot_server_id_no_mentions(state):
    http = Mock()
    toot = {"in_reply_to_id": "1", "in_reply_to_account_id": "1", "mentions": []}
    assert find_posts.get_replied_toot_server_id("server", toot, http=http, state=state) is None


def test_get_replied_toot_server_id_no_url_redirect(state):
    http = Mock()
    http.get_redirect_url.return_value = None
    toot = {
        "in_reply_to_id": "1",
        "in_reply_to_account_id": "1",
        "mentions": [{"id": "1", "acct": "account"}],
    }
    assert find_posts.get_replied_toot_server_id("server", toot, http=http, state=state) is None


def test_get_replied_toot_server_id_with_url_redirect(state):
    http = Mock()
    http.get_redirect_url.return_value = "redirect_url"
    toot = {
        "in_reply_to_id": "1",
        "in_reply_to_account_id": "1",
        "mentions": [{"id": "1", "acct": "account"}],
    }
    with patch("find_posts.parse_url", return_value="match") as mock_parse:
        assert find_posts.get_replied_toot_server_id(
            "server", toot, http=http, state=state
        ) == ("redirect_url", "match")
        mock_parse.assert_called_once_with("redirect_url", state.parsed_urls, http)


def test_get_replied_toot_server_id_with_existing_replied_toot_server_ids(state):
    http = Mock()
    toot = {
        "in_reply_to_id": "1",
        "in_reply_to_account_id": "1",
        "mentions": [{"id": "1", "acct": "account"}],
    }
    replied_toot_server_ids = {"https://server/@account/1": ("url", "match")}

    state.replied_toot_server_ids = replied_toot_server_ids
    assert find_posts.get_replied_toot_server_id(
        "server", toot, http=http, state=state
    ) == ("url", "match")


@patch("find_posts.get_server_info")
@patch("find_posts.logger")
def test_get_toot_context_no_server_info(mock_logger, mock_server_info, state, http):
    mock_server_info.return_value = None
    assert get_toot_context("server1", "toot1", "url1", http=http, state=state) == []
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
































class MockResponse:
    def __init__(self, status_code, links=None, json_data=None):
        self.status_code = status_code
        self.links = links
        self.json_data = json_data

    def json(self):
        return self.json_data












@patch("find_posts.get_all_known_context_urls")
@patch("find_posts.add_context_urls")
@patch("find_posts.add_user_posts")
@patch("find_posts.filter_known_users")
def test_fetch_timeline_context_with_empty_posts(
    mock_filter_known_users,
    mock_add_user_posts,
    mock_add_context_urls,
    mock_get_all_known_context_urls,
    state,
    http,
    home,
):
    config = SimpleNamespace(server="server_test", backfill_mentioned_users=False)

    find_posts.fetch_timeline_context([], home, http=http, config=config, state=state)

    mock_get_all_known_context_urls.assert_called_once_with(
        config.server, [], http=http, state=state
    )
    mock_add_context_urls.assert_called_once_with(
        home, mock_get_all_known_context_urls.return_value, state=state
    )
    assert not mock_filter_known_users.called
    assert not mock_add_user_posts.called
