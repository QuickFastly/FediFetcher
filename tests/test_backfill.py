from unittest.mock import Mock, patch

from fedifetcher import backfill
from fedifetcher.backfill import (
    add_user_posts,
    filter_known_users,
)
from fedifetcher.state import TimestampedSet


@patch("fedifetcher.backfill.get_user_posts")
@patch("fedifetcher.backfill.add_post_with_context")
@patch("fedifetcher.backfill.logger")
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


@patch("fedifetcher.backfill.get_user_posts")
@patch("fedifetcher.backfill.add_post_with_context")
@patch("fedifetcher.backfill.logger")
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
    result = backfill.add_post_with_context(
        post, home, http=http, config=config, state=state
    )

    home.resolve.assert_called_once_with(post["url"])
    assert result is False


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
