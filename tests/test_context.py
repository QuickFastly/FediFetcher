from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from fedifetcher import context
from fedifetcher.context import get_toot_context


@pytest.fixture
def webserver():
    return "server.com"


@pytest.fixture
def userName():
    return "test_user"


@patch("fedifetcher.context.logger")
def test_toot_context_can_be_fetched_public(mock_logger):
    toot = {"visibility": "public", "uri": "sample_uri"}
    result = context.toot_context_can_be_fetched(toot)
    assert result is True
    mock_logger.debug.assert_not_called()


@patch("fedifetcher.context.logger")
def test_toot_context_can_be_fetched_unlisted(mock_logger):
    toot = {"visibility": "unlisted", "uri": "sample_uri"}
    result = context.toot_context_can_be_fetched(toot)
    assert result is True
    mock_logger.debug.assert_not_called()


@patch("fedifetcher.context.logger")
def test_toot_context_can_be_fetched_private(mock_logger):
    toot = {"visibility": "private", "uri": "sample_uri"}
    result = context.toot_context_can_be_fetched(toot)
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


@patch("fedifetcher.context.get_toot_context")
@patch("fedifetcher.context.parse_url")
@patch("fedifetcher.context.toot_has_parseable_url")
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

    urls = context.get_all_known_context_urls(
        "test_server", reply_toots, http=http, state=state
    )

    assert urls == {"context_item_1", "context_item_2"}
    assert toot_has_parseable_url.call_count == 2
    assert get_toot_context.call_count == 2
    # both posts are now remembered, so a second pass would not refetch them
    assert "test_uri_1" in state.recently_checked_context
    assert not context.get_all_known_context_urls(
        "test_server", reply_toots, http=http, state=state
    )


def test_toot_has_parseable_url_with_parseable_url(state):
    http = Mock()
    toot = {"url": "http://test.com", "reblog": None}
    with patch("fedifetcher.context.parse_url", return_value="something") as mock_parse_url:
        assert context.toot_has_parseable_url(toot, http=http, state=state)
        mock_parse_url.assert_called_once_with("http://test.com", state.parsed_urls, http)


def test_toot_has_parseable_url_with_unparseable_url(state):
    http = Mock()
    toot = {"url": "http://test.com", "reblog": None}
    with patch("fedifetcher.context.parse_url", return_value=None) as mock_parse_url:
        assert not context.toot_has_parseable_url(toot, http=http, state=state)
        mock_parse_url.assert_called_once_with("http://test.com", state.parsed_urls, http)


def test_get_replied_toot_server_id_no_mentions(state):
    http = Mock()
    toot = {"in_reply_to_id": "1", "in_reply_to_account_id": "1", "mentions": []}
    assert context.get_replied_toot_server_id("server", toot, http=http, state=state) is None


def test_get_replied_toot_server_id_no_url_redirect(state):
    http = Mock()
    http.get_redirect_url.return_value = None
    toot = {
        "in_reply_to_id": "1",
        "in_reply_to_account_id": "1",
        "mentions": [{"id": "1", "acct": "account"}],
    }
    assert context.get_replied_toot_server_id("server", toot, http=http, state=state) is None


def test_get_replied_toot_server_id_with_url_redirect(state):
    http = Mock()
    http.get_redirect_url.return_value = "redirect_url"
    toot = {
        "in_reply_to_id": "1",
        "in_reply_to_account_id": "1",
        "mentions": [{"id": "1", "acct": "account"}],
    }
    with patch("fedifetcher.context.parse_url", return_value="match") as mock_parse:
        assert context.get_replied_toot_server_id(
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
    assert context.get_replied_toot_server_id(
        "server", toot, http=http, state=state
    ) == ("url", "match")


@patch("fedifetcher.context.get_server_info")
@patch("fedifetcher.context.logger")
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
