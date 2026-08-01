from unittest.mock import patch

import requests
from requests.models import Response

from fedifetcher.http import get_redirect_url


@patch("fedifetcher.http.requests")
@patch("fedifetcher.http.logger")
def test_get_redirect_url_success(mock_logger, mock_requests):
    response = Response()
    response.status_code = 200
    mock_requests.head.return_value = response
    assert get_redirect_url("https://test.com") == "https://test.com"
    mock_logger.error.assert_not_called()
    mock_logger.debug.assert_not_called()


@patch("fedifetcher.http.requests")
@patch("fedifetcher.http.logger")
def test_get_redirect_url_redirected(mock_logger, mock_requests):
    response = Response()
    response.status_code = 302
    response.headers = {"Location": "https://redirected.com"}
    mock_requests.head.return_value = response
    assert get_redirect_url("https://test.com") == "https://redirected.com"
    mock_logger.error.assert_not_called()
    mock_logger.debug.assert_called_once()


@patch("fedifetcher.http.requests")
@patch("fedifetcher.http.logger")
def test_get_redirect_url_error_status_code(mock_logger, mock_requests):
    response = Response()
    response.status_code = 500
    mock_requests.head.return_value = response
    assert get_redirect_url("https://test.com") is None
    mock_logger.error.assert_called_once()
    mock_logger.debug.assert_not_called()


@patch("fedifetcher.http.requests")
@patch("fedifetcher.http.logger")
def test_get_redirect_url_exception(mock_logger, mock_requests):
    mock_requests.head.side_effect = requests.exceptions.RequestException
    assert get_redirect_url("https://test.com") is None
    mock_logger.error.assert_called_once()
    mock_logger.debug.assert_not_called()
