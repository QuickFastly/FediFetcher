from unittest.mock import Mock

import pytest

from fedifetcher.store import State


@pytest.fixture
def http():
    """A stand-in HttpClient whose get/post return whatever a test sets up"""
    return Mock()


def response(status_code=200, json_data=None, text=""):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = text
    return resp


@pytest.fixture
def reply():
    return response


@pytest.fixture
def state():
    """Real state: it is a plain bag of collections, so mocking it hides bugs"""
    return State()
