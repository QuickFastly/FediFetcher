from datetime import UTC, datetime

import pytest

from fedifetcher.posts import Post, parse_date, unusable, usable

WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def post(**overrides):
    fields = {"url": "https://remote.example/@a/1", "uri": "https://remote.example/@a/1",
              "created_at": WHEN, "is_public": True}
    return Post(**{**fields, **overrides})


def test_a_post_that_is_not_a_boost_is_its_own_original():
    plain = post()

    assert not plain.is_boost
    assert plain.original is plain


def test_a_boost_points_at_the_post_it_boosts():
    original = post(url="https://remote.example/@b/9")
    boost = post(reblog=original)

    assert boost.is_boost
    assert boost.original is original


def test_a_post_the_server_said_nothing_about_may_have_no_context():
    assert not post().may_have_context


@pytest.mark.parametrize(
    "said", [{"in_reply_to_id": "7"}, {"reply_count": 2}, {"reply_count": 0}]
)
def test_a_post_the_server_said_anything_about_may_have_context(said):
    assert post(**said).may_have_context


def test_a_post_cannot_be_changed_once_it_has_been_read():
    with pytest.raises(AttributeError):
        post().url = "https://somewhere.else/1"


def test_the_posts_we_could_use_are_the_ones_we_keep():
    kept = post()

    assert usable([kept, None, kept]) == [kept, kept]


def test_nothing_usable_is_an_empty_list_rather_than_nothing():
    assert usable([None, None]) == []


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-01-01T00:00:00.000Z", datetime(2026, 1, 1, tzinfo=UTC)),
        ("2026-01-01T00:00:00+00:00", datetime(2026, 1, 1, tzinfo=UTC)),
        (WHEN, WHEN),
    ],
)
def test_a_date_is_read_however_the_server_spelled_it(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize("value", ["not a date", "", None, 17, {"when": "now"}])
def test_a_date_we_cannot_read_is_admitted_to_rather_than_guessed(value):
    assert parse_date(value) is None


def test_dropping_a_post_is_worth_saying_out_loud(caplog):
    with caplog.at_level("DEBUG"):
        unusable("newthing", "https://remote.example/1")

    assert "newthing" in caplog.text
    assert "https://remote.example/1" in caplog.text
