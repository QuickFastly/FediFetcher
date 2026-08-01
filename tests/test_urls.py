from unittest.mock import patch

import pytest

from fedifetcher.urls import (
    PostRef,
    UserRef,
    parse_lemmy_profile_url,
    parse_lemmy_url,
    parse_mastodon_profile_url,
    parse_mastodon_uri,
    parse_mastodon_url,
    parse_misskey_url,
    parse_peertube_profile_url,
    parse_peertube_url,
    parse_pixelfed_profile_url,
    parse_pixelfed_url,
    parse_pleroma_profile_url,
    parse_pleroma_uri,
    parse_pleroma_url,
    parse_url,
    parse_user_url,
)


def test_parse_user_url_dispatches_by_shape():
    assert parse_user_url("https://mstdn.thms.uk/@nanos") == UserRef(
        "mstdn.thms.uk", "nanos"
    )
    assert parse_user_url("https://pleroma.server/users/username") == UserRef(
        "pleroma.server", "username"
    )
    assert parse_user_url("https://lemmy.world/u/someone") == UserRef(
        "lemmy.world", "someone"
    )
    assert parse_user_url("https://video.example/accounts/channel") == UserRef(
        "video.example", "channel"
    )
    # Pixelfed profiles have no subdirectory, so this matcher runs last and
    # catches anything the others rejected.
    assert parse_user_url("https://pixelfed.social/username") == UserRef(
        "pixelfed.social", "username"
    )


def test_parse_user_url_logs_and_returns_none_when_unparseable(caplog):
    assert parse_user_url("not a url") is None
    assert "Error parsing Profile URL not a url" in caplog.text


def test_refs_are_tuples():
    """Call sites still index these positionally, so the tuple shape has to hold."""
    ref = parse_mastodon_url("https://mstdn.thms.uk/@nanos/12345")
    assert ref == ("mstdn.thms.uk", "12345")
    assert ref[0] == ref.server
    assert ref[1] == ref.post_id
    assert isinstance(ref, PostRef)


def test_parse_mastodon_profile_url_success():
    url = "https://mastodon.social/@username"
    result = parse_mastodon_profile_url(url)
    assert result == ("mastodon.social", "username")


def test_parse_mastodon_profile_url_not_match():
    url = "https://mastodon.social/username"
    result = parse_mastodon_profile_url(url)
    assert result is None


def test_parse_mastodon_url():
    valid_url = "https://mastodon.social/@user/1234"
    invalid_url = "https://twitter.com/user/status/1234"
    null_url = None

    # Testing valid mastodon URL
    server, toot_id = parse_mastodon_url(valid_url)
    assert server == "mastodon.social"
    assert toot_id == "1234"

    # Testing invalid URL
    assert parse_mastodon_url(invalid_url) is None

    # Testing null URL
    with pytest.raises(TypeError):
        parse_mastodon_url(null_url)


def test_parse_mastodon_uri():
    # Test that a valid URI is correctly parsed
    uri = "https://my.server.com/users/testuser/statuses/123456"
    assert parse_mastodon_uri(uri) == ("my.server.com", "123456")

    # Test that an invalid URI returns None
    uri = "http://invalid.uri.com"
    assert parse_mastodon_uri(uri) is None

    # Test that a URI missing elements returns None
    uri = "https://missing.elements.com/users/testuser/"
    assert parse_mastodon_uri(uri) is None

    # Test that a URI with extra elements returns the correct server and ID
    uri = "https://extra.elements.com/users/testuser/statuses/123456/7890"
    assert parse_mastodon_uri(uri) == ("extra.elements.com", "123456")

    # Test that a URI with different protocol still works
    uri = "http://still.works.com/users/testuser/statuses/123456"
    assert parse_mastodon_uri(uri) is None

    # Test that a URI without protocol doesn't work
    uri = "nowork/users/testuser/statuses/123456"
    assert parse_mastodon_uri(uri) is None

    # Test that a URI without slashes after https:// doesn't work
    uri = "https://noworkusers/testuser/statuses/123456"
    assert parse_mastodon_uri(uri) is None

    # Test the boundary case of an empty string
    uri = ""
    assert parse_mastodon_uri(uri) is None


@patch("fedifetcher.urls.get_redirect_url")
def test_parse_pleroma_url(mock_get_redirect_url):
    mock_get_redirect_url.return_value = "/notice/123"

    result = parse_pleroma_url("https://example.com/objects/567")
    assert result == ("example.com", "123")

    mock_get_redirect_url.return_value = None
    result = parse_pleroma_url("https://example.com/objects/567")
    assert result is None

    result = parse_pleroma_url("not a url")
    assert result is None

    mock_get_redirect_url.return_value = "/different_pattern/123"
    result = parse_pleroma_url("https://example.com/objects/567")
    assert result is None

    mock_get_redirect_url.return_value = "/notice/789"
    result = parse_pleroma_url("https://different.example.com/objects/111")
    assert result == ("different.example.com", "789")

def test_parse_pleroma_uri():
    # Test that a valid URI is correctly parsed
    uri = "https://friedcheese.us/notice/Arv4zBVnAR84mmkVay"
    assert parse_pleroma_uri(uri) == ("friedcheese.us", "Arv4zBVnAR84mmkVay")


def test_parse_pleroma_profile_url():
    # successful parsing
    result = parse_pleroma_profile_url("https://pleroma.server/users/username")
    assert result == ("pleroma.server", "username")

    # unsuccessful parsing
    result = parse_pleroma_profile_url("http://notvalid/url")
    assert result is None

    # url with extra path and query string
    result = parse_pleroma_profile_url(
        "https://pleroma.server/users/username/extra/path?arg=value"
    )
    assert result == ("pleroma.server", "username")

    # url with www
    result = parse_pleroma_profile_url("https://www.pleroma.server/users/username")
    assert result == ("www.pleroma.server", "username")

    # url without https
    result = parse_pleroma_profile_url("http://pleroma.server/users/username")
    assert result is None


def test_parse_pixelfed_url():
    url = "https://server.com/p/username/post123"
    assert parse_pixelfed_url(url) == ("server.com", "post123")


def test_parse_pixelfed_url_no_match():
    url = "https://notaurl.com/abc/123"
    assert parse_pixelfed_url(url) is None


def test_parse_pixelfed_url_malformed():
    url = "malformed url"
    assert parse_pixelfed_url(url) is None


def test_parse_misskey_url():
    url = "https://misskey.io/notes/837jfe8372"
    server, toot_id = parse_misskey_url(url)
    assert server == "misskey.io"
    assert toot_id == "837jfe8372"


def test_parse_misskey_url_no_match():
    url = "https://notamisskeyurl.com"
    result = parse_misskey_url(url)
    assert result is None


def test_parse_misskey_url_incorrect_path():
    url = "https://misskey.io/notnotes/837jfe8372"
    result = parse_misskey_url(url)
    assert result is None


def test_parse_peertube_url_valid():
    # define a valid url
    url = "https://example.com/videos/watch/123456789"

    # the expected server and id from the url
    expected = ("example.com", "123456789")

    # call the function with the valid url
    result = parse_peertube_url(url)

    # assert that the result is as expected
    assert result == expected

def test_parse_url():
    tests = [
        (
            "https://video.infosec.exchange/videos/watch/56f1d0b5-d98f-4bad-b1e7-648ae074ab9d",
            ("video.infosec.exchange", "56f1d0b5-d98f-4bad-b1e7-648ae074ab9d")
        ),
        (
            "https://veedeo.org/videos/watch/a51bb77c-e1bd-4d6a-b119-95af176f6d66",
            ("veedeo.org", "a51bb77c-e1bd-4d6a-b119-95af176f6d66")
        ),
        (
            'https://foo.bar/nothing',
            None
        )
    ]
    for (url,expected) in tests:
        result = parse_url(url, {})
        assert result == expected


def test_parse_peertube_url_invalid():
    # define an invalid url
    url = "https://bad.example.com/watch/123456789"

    # call the function with the invalid url
    result = parse_peertube_url(url)

    # assert that the result is None
    assert result is None


def test_parse_peertube_url_no_match():
    # define a url without a match
    url = "https://example.com/videos/123456789"

    # call the function with the url without a match
    result = parse_peertube_url(url)

    # assert that the result is None
    assert result is None


def test_parse_pixelfed_profile_url_success():
    url = "https://pixelfed.server/user.name"
    server, username = parse_pixelfed_profile_url(url)
    assert server == "pixelfed.server"
    assert username == "user.name"


def test_parse_pixelfed_profile_url_invalid_url():
    url = "pixelfed.server/user.name"
    result = parse_pixelfed_profile_url(url)
    assert result is None


def test_parse_pixelfed_profile_url_empty_url():
    url = ""
    result = parse_pixelfed_profile_url(url)
    assert result is None


def test_parse_lemmy_url_success():
    url = "https://testserver/post/1234"

    result = parse_lemmy_url(url)

    assert result == ("testserver", "1234")


def test_parse_lemmy_url_fail_invalid_url():
    url = "http://testserver/post/1234"

    result = parse_lemmy_url(url)

    assert result is None


def test_parse_lemmy_url_fail_no_id():
    url = "https://testserver/post/"

    result = parse_lemmy_url(url)

    assert result is None


def test_parse_lemmy_url_fail_no_protocol():
    url = "testserver/post/1234"

    result = parse_lemmy_url(url)

    assert result is None


def test_parse_lemmy_profile_url():
    url = "https://my.lemmy.server/u/username"
    result = parse_lemmy_profile_url(url)
    assert result == ("my.lemmy.server", "username")


def test_parse_lemmy_profile_url_no_match():
    url = "http://my.lemmy.server/u/username"
    result = parse_lemmy_profile_url(url)
    assert result is None


def test_parse_lemmy_profile_url_with_community():
    url = "https://my.lemmy.server/c/username"
    result = parse_lemmy_profile_url(url)
    assert result == ("my.lemmy.server", "username")


def test_parse_peertube_profile_url_valid():
    server, username = parse_peertube_profile_url(
        "https://myserver.com/accounts/TestUser"
    )
    assert server == "myserver.com"
    assert username == "TestUser"


def test_parse_peertube_profile_url_invalid():
    assert parse_peertube_profile_url("https://invalidurl.com/TestUser") is None


def test_parse_peertube_profile_url_none():
    with pytest.raises(TypeError):
        parse_peertube_profile_url(None)
