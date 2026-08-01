from __future__ import annotations

import logging

import requests

logger = logging.getLogger("FediFetcher")


def get_redirect_url(url: str) -> str | None:
    """get the URL given URL redirects to"""
    try:
        resp = requests.head(url, allow_redirects=False, timeout=5,headers={
            'User-Agent': 'FediFetcher (https://go.thms.uk/mgr)'
        })
    except Exception as ex:
        logger.error(f"Error getting redirect URL for URL {url}. Exception: {ex}")
        return None

    if resp.status_code == 200:
        return url
    elif resp.status_code == 302:
        redirect_url = resp.headers["Location"]
        logger.debug(f"Discovered redirect for URL {url}")
        return redirect_url
    else:
        logger.error(
            f"Error getting redirect URL for URL {url}. Status code: {resp.status_code}"
        )
        return None
