"""The digests and the dashboard's data, downloaded once and kept on disk:
each file is asked again only once it's older than its TTL, and then only
whether it changed (its ETag: an answer of 304 costs nothing). Offline, or
with a source down, what's on disk is used, saying so."""

import gzip
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

from . import __version__

USER_AGENT = (
    f"nixkeeper-mcp/{__version__} (+https://github.com/nixkeeper/nixkeeper-mcp)"
)
# Minutes a file is used without asking again. The digests change hourly at
# most (the versions digest every 12 hours, the dashboard every 3 hours):
# a quarter of an hour keeps answers within an hour of the source.
TTL = 15 * 60
# urlopen's timeout bounds each wait for the next bytes; DEADLINE bounds the
# whole answer (the biggest file, prs.json, is about 2 MB compressed).
TIMEOUT = 30
DEADLINE = 120
# How many parsed files are kept in memory, the most recently used.
MEMORY = 24


class Unavailable(Exception):
    """A file that couldn't be downloaded and isn't on disk either."""


class NotFound(Unavailable):
    """The server says there's no such file (404)."""


def default_directory():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "nixkeeper-mcp")


def _read(resp, deadline):
    read = getattr(resp, "read1", resp.read)
    chunks = []
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("the answer took too long to arrive")
        chunk = read(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


class File:
    """A file as the cache has it: its bytes (decompressed, when the server
    compressed them for the way: a .gz file stays as it is), when it was
    last checked with its source, when it last changed, and whether the
    check failed (stale: the source couldn't be asked)."""

    def __init__(self, data, checked_at, changed_at, stale=None):
        self.data = data
        self.checked_at = checked_at
        self.changed_at = changed_at
        self.stale = stale  # why it couldn't be refreshed, or None


class Cache:
    def __init__(self, directory=None, ttl=TTL, offline=False, clock=time.time):
        self.directory = directory or default_directory()
        self.ttl = ttl
        self.offline = offline
        self.clock = clock
        self._locks = {}
        self._locks_lock = threading.Lock()
        self._memory = {}  # url: (changed_at, parsed), the most recent last
        self._memory_lock = threading.Lock()
        self.status = {}  # url: what happened the last time it was used

    def _lock(self, url):
        with self._locks_lock:
            return self._locks.setdefault(url, threading.Lock())

    def _paths(self, url):
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        name = url.rstrip("/").rsplit("/", 1)[-1]
        base = os.path.join(self.directory, f"{key}-{name}")
        return base + ".body", base + ".meta"

    def _meta(self, url):
        _, meta = self._paths(url)
        try:
            with open(meta) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write(self, url, data, meta):
        body, meta_path = self._paths(url)
        os.makedirs(self.directory, exist_ok=True)
        for path, content in ((body, data), (meta_path, json.dumps(meta).encode())):
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "wb") as f:
                f.write(content)
            os.replace(tmp, path)

    def _body(self, url):
        body, _ = self._paths(url)
        with open(body, "rb") as f:
            return f.read()

    def _download(self, url, etag):
        """(bytes, ETag), or (None, etag) when unchanged (304)."""
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        if etag:
            headers["If-None-Match"] = etag
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = _read(resp, time.monotonic() + DEADLINE)
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data, resp.headers.get("ETag")
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None, etag
            if e.code == 404:
                raise NotFound(f"{url}: not found") from e
            raise

    def get(self, url):
        """url's File: from disk while it's fresh (younger than the TTL),
        else asked again (only whether it changed). Raises NotFound for a
        file the source doesn't have, Unavailable when it can't be read and
        isn't on disk."""
        with self._lock(url):
            meta = self._meta(url)
            now = self.clock()
            if meta and (self.offline or now - meta["checkedAt"] < self.ttl):
                try:
                    self.status[url] = "cached"
                    stale = "offline" if self.offline else None
                    return File(
                        self._body(url), meta["checkedAt"], meta["changedAt"], stale
                    )
                except OSError:
                    meta = None
            if self.offline:
                raise Unavailable(f"{url}: not downloaded yet, and offline")
            try:
                data, etag = self._download(url, meta and meta.get("etag"))
            except NotFound:
                self.status[url] = "not found"
                raise
            except (urllib.error.URLError, OSError, ValueError, EOFError) as e:
                why = str(getattr(e, "reason", None) or e)
                self.status[url] = f"stale: {why}"
                if meta:
                    try:
                        return File(
                            self._body(url), meta["checkedAt"], meta["changedAt"], why
                        )
                    except OSError:
                        pass
                raise Unavailable(f"{url}: {why}") from e
            if data is None:
                meta["checkedAt"] = now
                self._write_meta(url, meta)
                self.status[url] = "unchanged"
                return File(self._body(url), now, meta["changedAt"])
            meta = {"url": url, "etag": etag, "checkedAt": now, "changedAt": now}
            self._write(url, data, meta)
            self.status[url] = "downloaded"
            return File(data, now, now)

    def _write_meta(self, url, meta):
        _, meta_path = self._paths(url)
        tmp = f"{meta_path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w") as f:
            json.dump(meta, f)
        os.replace(tmp, meta_path)

    def load(self, url, parse):
        """(parse(bytes), File): parsed once per change of the file, the
        MEMORY most recently used kept parsed."""
        file = self.get(url)
        with self._memory_lock:
            kept = self._memory.pop(url, None)
            if kept and kept[0] == file.changed_at:
                self._memory[url] = kept
                return kept[1], file
        parsed = parse(file.data)
        with self._memory_lock:
            self._memory[url] = (file.changed_at, parsed)
            while len(self._memory) > MEMORY:
                self._memory.pop(next(iter(self._memory)))
        return parsed, file

    def files(self):
        """What's on disk: [(url, bytes, checkedAt)]."""
        found = []
        try:
            names = os.listdir(self.directory)
        except OSError:
            return found
        for name in sorted(names):
            if not name.endswith(".meta"):
                continue
            try:
                with open(os.path.join(self.directory, name)) as f:
                    meta = json.load(f)
                size = os.path.getsize(
                    os.path.join(self.directory, name[: -len(".meta")] + ".body")
                )
            except (OSError, ValueError):
                continue
            found.append((meta["url"], size, meta["checkedAt"]))
        return found
