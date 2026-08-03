import pytest

from fedifetcher.api.misskey import MisskeyApi
from fedifetcher.servers import ApiFlavour


@pytest.fixture
def api(http):
    return MisskeyApi("misskey.example", http)


def test_it_claims_the_misskey_flavour():
    assert MisskeyApi.flavour is ApiFlavour.MISSKEY


def test_user_posts_are_fetched_for_the_local_account(api, http, reply):
    http.post.side_effect = [
        reply(200, [{"id": "remote", "host": "elsewhere"}, {"id": "local", "host": None}]),
        reply(200, [{"id": "note1"}]),
    ]

    notes = api.fetch_user_posts("someone", "https://misskey.example/@someone")

    assert notes == [{"id": "note1", "url": "https://misskey.example/notes/note1"}]
    assert http.post.call_args_list[1][0][1] == {"userId": "local", "limit": 40}


def test_a_note_that_knows_its_url_keeps_it(api, http, reply):
    http.post.side_effect = [
        reply(200, [{"id": "local", "host": None}]),
        reply(200, [{"id": "note1", "url": "https://elsewhere/notes/note1"}]),
    ]

    notes = api.fetch_user_posts("someone", "https://misskey.example/@someone")

    assert notes[0]["url"] == "https://elsewhere/notes/note1"


def test_user_posts_give_up_when_the_account_is_not_found(api, http, reply):
    http.post.return_value = reply(200, [{"id": "remote", "host": "elsewhere"}])
    assert api.fetch_user_posts("someone", "https://misskey.example/@someone") is None


def test_user_posts_give_up_on_a_search_error(api, http, reply):
    http.post.return_value = reply(500)
    assert api.fetch_user_posts("someone", "https://misskey.example/@someone") is None


def test_user_posts_give_up_when_the_request_fails(api, http):
    http.post.side_effect = Exception("no route to host")
    assert api.fetch_user_posts("someone", "https://misskey.example/@someone") is None


def test_context_combines_children_and_conversation(api, http, reply):
    http.post.side_effect = [
        reply(200, [{"id": "child"}]),
        reply(200, [{"id": "parent"}]),
    ]

    urls = api.fetch_context_urls("note1", "https://misskey.example/notes/note1")

    assert urls == [
        "https://misskey.example/notes/child",
        "https://misskey.example/notes/parent",
    ]


def test_context_keeps_what_it_can_when_one_endpoint_fails(api, http, reply):
    http.post.side_effect = [reply(500), reply(200, [{"id": "parent"}])]

    urls = api.fetch_context_urls("note1", "https://misskey.example/notes/note1")

    assert urls == ["https://misskey.example/notes/parent"]


def test_context_is_empty_when_the_request_fails(api, http):
    http.post.side_effect = Exception("no route to host")
    assert api.fetch_context_urls("note1", "https://misskey.example/notes/note1") == []


def test_context_is_empty_when_the_body_makes_no_sense(api, http, reply):
    http.post.return_value = reply(200, None)
    assert api.fetch_context_urls("note1", "https://misskey.example/notes/note1") == []
