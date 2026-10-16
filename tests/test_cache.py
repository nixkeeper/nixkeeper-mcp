import email.message
import gzip
import io
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from nixkeeper_mcp import cache

URL = "https://example.org/data/prs.json"


class Answer(io.BytesIO):
    def __init__(self, body, etag=None, encoding=None):
        super().__init__(body)
        self.headers = email.message.Message()
        if etag:
            self.headers["ETag"] = etag
        if encoding:
            self.headers["Content-Encoding"] = encoding

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code):
    return urllib.error.HTTPError(URL, code, "", email.message.Message(), None)


class Server:
    """Answers urlopen's requests in turn, remembering them."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append(req)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Caching(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = tmp.name
        self.now = 1000.0

    def cache(self, **kwargs):
        return cache.Cache(self.directory, ttl=900, clock=lambda: self.now, **kwargs)

    def serve(self, *answers):
        server = Server(*answers)
        patch = mock.patch.object(cache.urllib.request, "urlopen", server)
        patch.start()
        self.addCleanup(patch.stop)
        return server

    def test_downloaded_once_then_from_disk_while_fresh(self):
        server = self.serve(Answer(b"one", etag='W/"1"'))
        c = self.cache()
        self.assertEqual(c.get(URL).data, b"one")
        self.now += 899
        # Another process (a second server) reads it from disk too.
        self.assertEqual(self.cache().get(URL).data, b"one")
        self.assertEqual(len(server.requests), 1)
        sent = server.requests[0]
        self.assertIn("nixkeeper-mcp", sent.get_header("User-agent"))
        self.assertEqual(sent.get_header("Accept-encoding"), "gzip")

    def test_then_only_whether_it_changed(self):
        server = self.serve(
            Answer(b"one", etag='W/"1"'), http_error(304), Answer(b"two", etag='W/"2"')
        )
        c = self.cache()
        first = c.get(URL)
        self.now += 901
        same = c.get(URL)
        self.assertEqual(server.requests[1].get_header("If-none-match"), 'W/"1"')
        self.assertEqual((same.data, same.changed_at), (b"one", first.changed_at))
        self.assertEqual(same.checked_at, self.now)
        self.now += 901
        changed = c.get(URL)
        self.assertEqual((changed.data, changed.changed_at), (b"two", self.now))
        self.assertEqual(c.status[URL], "downloaded")

    def test_compressed_for_the_way(self):
        self.serve(Answer(gzip.compress(b"{}"), encoding="gzip"))
        self.assertEqual(self.cache().get(URL).data, b"{}")

    def test_source_down_uses_what_it_has_saying_so(self):
        self.serve(Answer(b"one"), urllib.error.URLError("no route"))
        c = self.cache()
        c.get(URL)
        self.now += 901
        got = c.get(URL)
        self.assertEqual((got.data, got.stale), (b"one", "no route"))

    def test_nothing_on_disk_and_down(self):
        self.serve(TimeoutError("slow"))
        with self.assertRaisesRegex(cache.Unavailable, "slow"):
            self.cache().get(URL)

    def test_not_found(self):
        self.serve(http_error(404))
        with self.assertRaises(cache.NotFound):
            self.cache().get(URL)

    def test_offline_never_asks(self):
        self.serve(Answer(b"one"))
        self.cache().get(URL)
        self.now += 10**6
        offline = self.cache(offline=True)
        got = offline.get(URL)
        self.assertEqual((got.data, got.stale), (b"one", "offline"))
        with self.assertRaises(cache.Unavailable):
            offline.get(URL + "?other")

    def test_parsed_once_per_change(self):
        self.serve(Answer(b"one"), http_error(304), Answer(b"two"))
        c = self.cache()
        parsed = []

        def parse(data):
            parsed.append(data)
            return data.upper()

        self.assertEqual(c.load(URL, parse)[0], b"ONE")
        self.now += 901
        self.assertEqual(c.load(URL, parse)[0], b"ONE")
        self.now += 901
        self.assertEqual(c.load(URL, parse)[0], b"TWO")
        self.assertEqual(parsed, [b"one", b"two"])

    def test_memory_keeps_the_most_recent(self):
        self.serve(*[Answer(b"x") for _ in range(cache.MEMORY + 1)])
        c = self.cache()
        for i in range(cache.MEMORY + 1):
            c.load(f"{URL}?{i}", bytes)
        self.assertEqual(len(c._memory), cache.MEMORY)
        self.assertNotIn(f"{URL}?0", c._memory)

    def test_files_lists_whats_on_disk(self):
        self.serve(Answer(b"one"))
        c = self.cache()
        c.get(URL)
        self.assertEqual(c.files(), [(URL, 3, self.now)])
        names = os.listdir(self.directory)
        self.assertTrue(all("prs.json" in n for n in names), names)

    def test_default_directory(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/x"}):
            self.assertEqual(cache.default_directory(), "/x/nixkeeper-mcp")


if __name__ == "__main__":
    unittest.main()
