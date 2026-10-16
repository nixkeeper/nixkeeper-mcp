"""The Model Context Protocol over stdio: JSON-RPC 2.0, one message a line.

Both eras of the protocol are served, as a client opens:

- the current one (2026-07-28): no handshake, each request carries its
  protocol version and the client's capabilities in its `_meta`
  (io.modelcontextprotocol/...), and `server/discover` says what the
  server supports;
- the earlier ones (2025-11-25 back to 2024-11-05): an `initialize`
  handshake first, then requests without them.

Only tools: no resources, prompts, subscriptions or requests to the client.
"""

import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import __version__, tools
from .cache import Unavailable

MODERN = ("2026-07-28",)
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SUPPORTED = MODERN + LEGACY
# structuredContent in tool results: from 2025-06-18.
STRUCTURED_FROM = "2025-06-18"

PREFIX = "io.modelcontextprotocol/"
VERSION_KEY = PREFIX + "protocolVersion"
CAPABILITIES_KEY = PREFIX + "clientCapabilities"
SERVER_INFO_KEY = PREFIX + "serverInfo"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNSUPPORTED_VERSION = -32022

SERVER_INFO = {"name": "nixkeeper-mcp", "title": "nixkeeper", "version": __version__}
CAPABILITIES = {"tools": {"listChanged": False}}
# The tools never change while the server runs: a day.
TOOLS_TTL_MS = 24 * 3600 * 1000

INSTRUCTIONS = """\
Answers questions about nixpkgs packages from nixkeeper (nixkeeper.com): \
versions against upstream, Hydra builds of master, the update bot's \
(nixpkgs-update, r-ryantm) attempts, open PRs and issues, CVEs. For one \
package use `package`; for what a maintainer or team should look at, \
`needs_attention`; to search across nixpkgs, `build_failures`, \
`pull_requests`, `issues`, `update_attempts`, `vulnerabilities`; for the \
big picture, `overview`. Every answer says when its data was read \
(readFrom; times in UTC): the digests are hourly, the dashboard syncs \
every 3 hours. nixkeeper's checks (an issue that looks done, a PR ready \
for the merge bot) are hints for a person to check, not decisions."""


class ProtocolError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def error(self):
        found = {"code": self.code, "message": self.message}
        if self.data is not None:
            found["data"] = self.data
        return found


def log(*parts):
    print("nixkeeper-mcp:", *parts, file=sys.stderr, flush=True)


class Server:
    def __init__(self, ctx):
        self.ctx = ctx
        # The version an `initialize` agreed on (earlier eras only).
        self.legacy_version = None

    # One request.

    def _era(self, method, params):
        """(the protocol version of a request, whether it's the current
        era's), or ProtocolError."""
        meta = params.get("_meta") or {}
        if not isinstance(meta, dict):
            raise ProtocolError(INVALID_PARAMS, "_meta must be an object")
        version = meta.get(VERSION_KEY)
        if version is None:
            if method == "server/discover":
                raise ProtocolError(INVALID_PARAMS, f"_meta needs {VERSION_KEY}")
            return self.legacy_version or LEGACY[0], False
        if version not in MODERN:
            raise ProtocolError(
                UNSUPPORTED_VERSION,
                "Unsupported protocol version",
                {"supported": list(SUPPORTED), "requested": version},
            )
        if not isinstance(meta.get(CAPABILITIES_KEY), dict):
            raise ProtocolError(INVALID_PARAMS, f"_meta needs {CAPABILITIES_KEY}")
        return version, True

    def _initialize(self, params):
        requested = params.get("protocolVersion")
        # A version this server speaks, else its newest of that era: the
        # client then decides whether it can go on.
        self.legacy_version = requested if requested in LEGACY else LEGACY[0]
        return {
            "protocolVersion": self.legacy_version,
            "capabilities": CAPABILITIES,
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }

    def _call(self, params, version):
        name = params.get("name")
        if name not in tools.BY_NAME:
            raise ProtocolError(INVALID_PARAMS, f"Unknown tool: {name}")
        args = params.get("arguments") or {}
        try:
            answer = tools.call(self.ctx, name, args)
        except tools.ToolError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Unavailable as e:
            text = f"nixkeeper's data couldn't be read: {e}"
            return {"content": [{"type": "text", "text": text}], "isError": True}
        except Exception as e:  # a bug: say so, and keep serving
            log(f"{name} failed:\n{traceback.format_exc()}")
            text = f"{name} failed: {type(e).__name__}: {e}"
            return {"content": [{"type": "text", "text": text}], "isError": True}
        text = json.dumps(answer, ensure_ascii=False)
        result = {"content": [{"type": "text", "text": text}], "isError": False}
        if version >= STRUCTURED_FROM:
            result["structuredContent"] = answer
        return result

    def result(self, method, params):
        """A request's result, or ProtocolError."""
        if not isinstance(params, dict):
            raise ProtocolError(INVALID_PARAMS, "params must be an object")
        if method == "initialize":
            return self._initialize(params)
        version, modern = self._era(method, params)
        if method == "server/discover":
            result = {
                "supportedVersions": list(SUPPORTED),
                "capabilities": CAPABILITIES,
                "instructions": INSTRUCTIONS,
                "ttlMs": TOOLS_TTL_MS,
                "cacheScope": "public",
            }
        elif method == "tools/list":
            result = {"tools": tools.listed()}
            if modern:
                result.update(ttlMs=TOOLS_TTL_MS, cacheScope="public")
        elif method == "tools/call":
            result = self._call(params, version)
        elif method == "ping":
            result = {}
        else:
            raise ProtocolError(METHOD_NOT_FOUND, f"Method not found: {method}")
        if modern:
            result["resultType"] = "complete"
            result["_meta"] = {SERVER_INFO_KEY: SERVER_INFO}
        return result

    def handle(self, message):
        """The answer to one message (a dict), or None for a notification
        or a response."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return error(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message")
        method = message.get("method")
        if not isinstance(method, str):
            return None  # a response to a request: this server sends none
        if "id" not in message:
            return None  # a notification: none needs an answer
        id_ = message["id"]
        try:
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "result": self.result(method, message.get("params") or {}),
            }
        except ProtocolError as e:
            return {"jsonrpc": "2.0", "id": id_, "error": e.error()}

    # The stdio loop.

    def serve(self, inp=None, out=None, workers=4):
        """Read messages from inp (stdin) until it closes, answering on out
        (stdout). Tool calls run beside each other (a download shouldn't
        hold up a quick answer); a cancelled one isn't answered."""
        inp = inp or sys.stdin.buffer
        out = out or sys.stdout.buffer
        write_lock = threading.Lock()
        # Tool calls still running, and those of them the client cancelled,
        # by their ids as JSON (any id, even one JSON-RPC doesn't allow).
        running, cancelled = set(), set()

        def key(id_):
            return json.dumps(id_, sort_keys=True)

        def write(answer):
            if answer is None:
                return
            line = json.dumps(answer, ensure_ascii=False, separators=(",", ":"))
            with write_lock:
                out.write(line.encode() + b"\n")
                out.flush()

        def answer(message):
            try:
                return self.handle(message)
            except Exception:  # a bug outside a tool: answer, don't go silent
                log(f"{message.get('method')} failed:\n{traceback.format_exc()}")
                return error(message.get("id"), INTERNAL_ERROR, "Internal error")

        def run(message):
            id_ = message.get("id")
            found = answer(message)
            with write_lock:
                running.discard(key(id_))
                if key(id_) in cancelled:
                    cancelled.discard(key(id_))
                    return
            write(found)

        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            for raw in inp:
                if not raw.strip():
                    continue
                try:
                    message = json.loads(raw)
                except ValueError:
                    write(error(None, PARSE_ERROR, "Parse error"))
                    continue
                if isinstance(message, dict) and message.get("method") == (
                    "notifications/cancelled"
                ):
                    params = message.get("params")
                    request = (
                        params.get("requestId") if isinstance(params, dict) else None
                    )
                    with write_lock:
                        if key(request) in running:  # else answered already
                            cancelled.add(key(request))
                    continue
                if isinstance(message, dict) and message.get("method") == "tools/call":
                    with write_lock:
                        running.add(key(message.get("id")))
                    pool.submit(run, message)
                elif isinstance(message, dict):
                    write(answer(message))
                else:
                    write(self.handle(message))  # not an object: its error
        finally:
            # stdin closed: the client sends nothing more, but may still be
            # reading. What it asked is answered, then the server exits.
            pool.shutdown(wait=True)


def error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}
