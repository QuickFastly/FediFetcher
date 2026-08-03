from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from fedifetcher import tasks


@patch("fedifetcher.tasks.get_all_known_context_urls")
@patch("fedifetcher.tasks.add_context_urls")
@patch("fedifetcher.tasks.add_user_posts")
@patch("fedifetcher.tasks.filter_known_users")
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

    tasks.fetch_timeline_context([], home, http=http, config=config, state=state)

    mock_get_all_known_context_urls.assert_called_once_with(
        config.server, [], http=http, state=state
    )
    mock_add_context_urls.assert_called_once_with(
        home, mock_get_all_known_context_urls.return_value, state=state
    )
    assert not mock_filter_known_users.called
    assert not mock_add_user_posts.called


def config_with(**settings):
    defaults = dict(
        server="example.social",
        from_lists=False, reply_interval_in_hours=0, home_timeline_length=0,
        max_followings=0, max_followers=0, max_follow_requests=0,
        from_notifications=0, max_bookmarks=0, max_favourites=0,
    )
    defaults.update(settings)
    return SimpleNamespace(**defaults)


def context_for(**settings):
    return tasks.Context(
        config=config_with(**settings), state=Mock(), http=Mock(), home=Mock()
    )


def test_nothing_runs_when_nothing_is_enabled():
    ran = []
    patched = [
        (is_enabled, (lambda name: lambda ctx: ran.append(name))(task.__name__))
        for is_enabled, task in tasks.ENABLED_BY
    ]
    with patch.object(tasks, "ENABLED_BY", patched):
        tasks.run_enabled_tasks(context_for())
    assert ran == []


@pytest.mark.parametrize(
    "setting,expected",
    [
        ({"from_lists": True}, "fetch_from_lists"),
        ({"reply_interval_in_hours": 1}, "fetch_reply_context"),
        ({"home_timeline_length": 10}, "fetch_home_timeline"),
        ({"max_followings": 10}, "backfill_followings"),
        ({"max_followers": 10}, "backfill_followers"),
        ({"max_follow_requests": 10}, "backfill_follow_requests"),
        ({"from_notifications": 10}, "backfill_from_notifications"),
        ({"max_bookmarks": 10}, "fetch_bookmark_context"),
        ({"max_favourites": 10}, "fetch_favourite_context"),
    ],
)
def test_each_setting_enables_its_own_task(setting, expected):
    ran = []
    patched = [
        (is_enabled, (lambda name: lambda ctx: ran.append(name))(task.__name__))
        for is_enabled, task in tasks.ENABLED_BY
    ]
    with patch.object(tasks, "ENABLED_BY", patched):
        tasks.run_enabled_tasks(context_for(**setting))
    assert ran == [expected]


def test_tasks_run_in_the_documented_order():
    ran = []
    patched = [
        (lambda c: True, (lambda name: lambda ctx: ran.append(name))(task.__name__))
        for _, task in tasks.ENABLED_BY
    ]
    with patch.object(tasks, "ENABLED_BY", patched):
        tasks.run_enabled_tasks(context_for())

    assert ran == [
        "fetch_from_lists", "fetch_reply_context", "fetch_home_timeline",
        "backfill_followings", "backfill_followers", "backfill_follow_requests",
        "backfill_from_notifications", "fetch_bookmark_context",
        "fetch_favourite_context",
    ]


def test_bookmarks_pull_context_for_what_they_find():
    ctx = context_for(max_bookmarks=5)
    ctx.home.bookmarks.return_value = ["a post"]

    with patch.object(tasks, "get_all_known_context_urls", return_value=["url"]) as gather, \
         patch.object(tasks, "add_context_urls") as add:
        tasks.fetch_bookmark_context(ctx)

    ctx.home.bookmarks.assert_called_once_with(5)
    gather.assert_called_once_with(ctx.config.server, ["a post"], http=ctx.http, state=ctx.state)
    add.assert_called_once_with(ctx.home, ["url"], state=ctx.state)
