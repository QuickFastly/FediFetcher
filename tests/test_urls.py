from unittest.mock import Mock

import pytest

from fedifetcher.urls import (
    PostRef,
    host_of,
    parse_lemmy_url,
    parse_mastodon_uri,
    parse_mastodon_url,
    parse_misskey_url,
    parse_peertube_url,
    parse_pixelfed_url,
    parse_pleroma_uri,
    parse_pleroma_url,
    parse_url,
)


def test_refs_are_tuples():
    """Call sites still index these positionally, so the tuple shape has to hold."""
    ref = parse_mastodon_url("https://mstdn.thms.uk/@nanos/12345")
    assert ref == ("mstdn.thms.uk", "12345")
    assert ref[0] == ref.server
    assert ref[1] == ref.post_id
    assert isinstance(ref, PostRef)


def test_parse_mastodon_url():
    valid_url = "https://mastodon.social/@user/1234"
    invalid_url = "https://twitter.com/user/status/1234"
    null_url = None

    # Testing valid mastodon URL
    parsed = parse_mastodon_url(valid_url)
    assert parsed is not None
    server, toot_id = parsed
    assert server == "mastodon.social"
    assert toot_id == "1234"

    # Testing invalid URL
    assert parse_mastodon_url(invalid_url) is None

    # Testing null URL
    with pytest.raises(TypeError):
        parse_mastodon_url(null_url)  # type: ignore[arg-type]


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


def test_parse_pleroma_url():
    http = Mock()
    http.get_redirect_url.return_value = "/notice/123"

    result = parse_pleroma_url("https://example.com/objects/567", http)
    assert result == ("example.com", "123")

    http.get_redirect_url.return_value = None
    result = parse_pleroma_url("https://example.com/objects/567", http)
    assert result is None

    result = parse_pleroma_url("not a url", http)
    assert result is None

    http.get_redirect_url.return_value = "/different_pattern/123"
    result = parse_pleroma_url("https://example.com/objects/567", http)
    assert result is None

    http.get_redirect_url.return_value = "/notice/789"
    result = parse_pleroma_url("https://different.example.com/objects/111", http)
    assert result == ("different.example.com", "789")

def test_parse_pleroma_uri():
    # Test that a valid URI is correctly parsed
    uri = "https://friedcheese.us/notice/Arv4zBVnAR84mmkVay"
    assert parse_pleroma_uri(uri) == ("friedcheese.us", "Arv4zBVnAR84mmkVay")


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
    parsed = parse_misskey_url(url)
    assert parsed is not None
    server, toot_id = parsed
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
    http = Mock()
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
        result = parse_url(url, {}, http)
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



@pytest.mark.parametrize(
    "url,host",
    [
        ("https://mstdn.example/@someone", "mstdn.example"),
        ("https://video.example/video-channels/a-channel", "video.example"),
        ("https://example.test", "example.test"),
        ("https://example.test:8443/@a", "example.test:8443"),
    ],
)
def test_the_host_is_read_without_knowing_the_software(url, host):
    assert host_of(url) == host


@pytest.mark.parametrize(
    "url",
    ["http://mstdn.example/@someone", "not a url", "", "ftp://example.test/x"],
)
def test_a_url_we_cannot_take_a_host_from(url):
    assert host_of(url) is None
