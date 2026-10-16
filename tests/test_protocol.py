import io
import json
import unittest
from unittest import mock

from nixkeeper_mcp import protocol

from . import fixtures

META = {
    protocol.VERSION_KEY: "2026-07-28",
    protocol.CAPABILITIES_KEY: {},
    protocol.PREFIX + "clientInfo": {"name": "test", "version": "1"},
}


def request(method, id_=1, meta=None, **params):
    if meta is not None:
        params["_meta"] = meta
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}


class Base(unittest.TestCase):
    def setUp(self):
        self.server = protocol.Server(fixtures.Context())

    def answer(self, *args, **kwargs):
        return self.server.handle(request(*args, **kwargs))


class Modern(Base):
    """2026-07-28: each request says its version and the client's
    capabilities; no handshake."""

    def test_discover(self):
        got = self.answer("server/discover", meta=META)["result"]
        self.assertEqual(got["supportedVersions"][0], "2026-07-28")
        self.assertIn("2025-11-25", got["supportedVersions"])
        self.assertEqual(got["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(got["resultType"], "complete")
        self.assertEqual(
            got["_meta"][protocol.SERVER_INFO_KEY]["name"], "nixkeeper-mcp"
        )
        self.assertGreater(got["ttlMs"], 0)
        self.assertEqual(got["cacheScope"], "public")

    def test_tools_list_cacheable(self):
        got = self.answer("tools/list", meta=META)["result"]
        self.assertEqual(len(got["tools"]), 10)
        self.assertNotIn("run", got["tools"][0])
        self.assertEqual((got["resultType"], got["cacheScope"]), ("complete", "public"))

    def test_tools_call(self):
        got = self.answer(
            "tools/call", meta=META, name="find_packages", arguments={"query": "ttd"}
        )["result"]
        self.assertFalse(got["isError"])
        self.assertEqual(got["resultType"], "complete")
        self.assertEqual(got["structuredContent"]["matches"], 1)
        self.assertEqual(
            json.loads(got["content"][0]["text"]), got["structuredContent"]
        )

    def test_unsupported_version(self):
        meta = {**META, protocol.VERSION_KEY: "1900-01-01"}
        got = self.answer("tools/list", meta=meta)["error"]
        self.assertEqual(got["code"], -32022)
        self.assertEqual(got["data"]["requested"], "1900-01-01")
        self.assertIn("2026-07-28", got["data"]["supported"])

    def test_required_meta(self):
        meta = {protocol.VERSION_KEY: "2026-07-28"}  # no capabilities
        self.assertEqual(self.answer("tools/list", meta=meta)["error"]["code"], -32602)
        # Discovery says which version it speaks: it needs one.
        self.assertEqual(self.answer("server/discover")["error"]["code"], -32602)


class Legacy(Base):
    """2025-11-25 and before: initialize, then plain requests."""

    def test_initialize_agrees_on_a_version(self):
        got = self.answer("initialize", protocolVersion="2025-06-18", capabilities={})
        self.assertEqual(got["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(got["result"]["serverInfo"]["name"], "nixkeeper-mcp")
        self.assertIn("package", got["result"]["instructions"])
        # One it doesn't know: its newest of that era, for the client to judge.
        got = self.answer("initialize", protocolVersion="2099-01-01")
        self.assertEqual(got["result"]["protocolVersion"], "2025-11-25")

    def test_results_without_the_modern_fields(self):
        self.answer("initialize", protocolVersion="2025-11-25")
        got = self.answer("tools/list")["result"]
        self.assertNotIn("resultType", got)
        self.assertNotIn("ttlMs", got)
        got = self.answer("tools/call", name="overview", arguments={})["result"]
        self.assertIn("structuredContent", got)

    def test_no_structured_content_before_2025_06_18(self):
        self.answer("initialize", protocolVersion="2025-03-26")
        got = self.answer("tools/call", name="overview")["result"]
        self.assertNotIn("structuredContent", got)
        self.assertFalse(got["isError"])

    def test_tools_read_only(self):
        # A client may run them without asking: they change nothing.
        for tool in self.answer("tools/list", meta=META)["result"]["tools"]:
            self.assertEqual(
                tool["annotations"], {"readOnlyHint": True, "openWorldHint": True}
            )

    def test_ping(self):
        self.assertEqual(self.answer("ping")["result"], {})


class Errors(Base):
    def test_a_tools_error_is_its_result(self):
        got = self.answer("tools/call", meta=META, name="package", arguments={})
        self.assertTrue(got["result"]["isError"])
        self.assertEqual(got["result"]["content"][0]["text"], "missing argument: name")

    def test_data_that_cant_be_read(self):
        cache = fixtures.FakeCache({})
        server = protocol.Server(fixtures.Context(cache))
        got = server.handle(request("tools/call", name="overview", arguments={}))
        self.assertTrue(got["result"]["isError"])
        self.assertIn("couldn't be read", got["result"]["content"][0]["text"])

    def test_a_bug_says_so_and_serving_goes_on(self):
        class Broken(fixtures.FakeCache):
            def load(self, url, parse):
                raise KeyError("oops")

        server = protocol.Server(fixtures.Context(Broken()))
        with mock.patch.object(protocol, "log"):
            got = server.handle(request("tools/call", name="overview", arguments={}))
        self.assertTrue(got["result"]["isError"])
        self.assertIn("KeyError", got["result"]["content"][0]["text"])

    def test_protocol_errors(self):
        self.assertEqual(
            self.answer("tools/call", name="nosuch")["error"]["code"], -32602
        )
        self.assertEqual(self.answer("resources/list")["error"]["code"], -32601)
        self.assertEqual(
            self.server.handle({"id": 1, "method": "ping"})["error"]["code"], -32600
        )
        bad = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": [1]}
        self.assertEqual(self.server.handle(bad)["error"]["code"], -32602)

    def test_notifications_and_responses_unanswered(self):
        self.assertIsNone(
            self.server.handle(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        )
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "id": 9, "result": {}}))


class Stdio(unittest.TestCase):
    def serve(self, *lines):
        inp = io.BytesIO(b"".join(line + b"\n" for line in lines))
        out = io.BytesIO()
        protocol.Server(fixtures.Context()).serve(inp, out, workers=1)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_one_message_a_line(self):
        call = request("tools/call", 2, META, name="overview", arguments={})
        got = self.serve(
            json.dumps(request("server/discover", 1, META)).encode(),
            b"",
            b"not json",
            json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            ).encode(),
            json.dumps(call).encode(),
        )
        by_id = {a["id"]: a for a in got}
        self.assertEqual(len(got), 3)
        self.assertIn("supportedVersions", by_id[1]["result"])
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertFalse(by_id[2]["result"]["isError"])

    def test_a_failure_outside_a_tool_is_answered(self):
        # Neither a tool call nor any other request goes unanswered when
        # handling it fails unexpectedly; the loop goes on.
        with (
            mock.patch.object(protocol.Server, "handle", side_effect=KeyError("x")),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            got = self.serve(
                json.dumps(request("tools/call", 1, META, name="overview")).encode(),
                json.dumps(request("tools/list", 2, META)).encode(),
                # A cancellation with odd params doesn't stop it either.
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/cancelled",
                        "params": [],
                    }
                ).encode(),
            )
        self.assertEqual(
            sorted((a["id"], a["error"]["code"]) for a in got),
            [(1, -32603), (2, -32603)],
        )

    def test_no_newline_inside_a_message(self):
        call = request("tools/call", 1, META, name="build_failures", arguments={})
        out = io.BytesIO()
        inp = io.BytesIO(json.dumps(call).encode() + b"\n")
        protocol.Server(fixtures.Context()).serve(inp, out, workers=1)
        # An excerpt has a newline: escaped in the JSON, one line in all.
        self.assertEqual(out.getvalue().count(b"\n"), 1)
        self.assertIn(b"\\n", out.getvalue())


if __name__ == "__main__":
    unittest.main()
