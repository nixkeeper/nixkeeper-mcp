from nixkeeper_mcp import cache


def _no_network(req, *args, **kwargs):
    url = getattr(req, "full_url", req)
    raise AssertionError(f"a test asked the network: {url}")


# Tests never ask the real sources: each gives its own answers (cache.py's
# own tests replace urlopen with theirs).
cache.urllib.request.urlopen = _no_network
