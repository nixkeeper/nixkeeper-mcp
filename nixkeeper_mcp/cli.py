"""`nixkeeper-mcp`: the MCP server over stdio, for an assistant to start
(`claude mcp add nixkeeper -- nixkeeper-mcp`, README).

`nixkeeper-mcp --call TOOL [JSON]` runs one tool and prints its answer,
to try the tools by hand."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime

from . import __version__, tools
from .cache import TTL, Cache, Unavailable
from .protocol import Server, log


class Context:
    """What a tool runs with: the cache, and the time."""

    def __init__(self, cache):
        self.cache = cache

    def now(self):
        return datetime.now(UTC)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="nixkeeper-mcp",
        description="An MCP server (stdio) answering questions about nixpkgs "
        "packages from nixkeeper's digests and dashboard.",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("NIXKEEPER_MCP_CACHE"),
        help="where downloaded files are kept "
        "(default: $XDG_CACHE_HOME/nixkeeper-mcp, else ~/.cache/nixkeeper-mcp)",
    )
    parser.add_argument(
        "--ttl",
        type=float,
        default=TTL / 60,
        metavar="MINUTES",
        help="use a downloaded file this long before asking whether it "
        f"changed (default {TTL // 60})",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="never download: answer from what's cached",
    )
    parser.add_argument(
        "--call",
        nargs="+",
        metavar=("TOOL", "JSON"),
        help="run one tool with its arguments (a JSON object) and print the "
        "answer, instead of serving",
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    cache = Cache(args.cache_dir, ttl=args.ttl * 60, offline=args.offline)
    ctx = Context(cache)

    if args.call:
        name, *rest = args.call
        if name not in tools.BY_NAME:
            parser.error(f"no tool {name!r}: {', '.join(tools.BY_NAME)}")
        try:
            arguments = json.loads(rest[0]) if rest else {}
            answer = tools.call(ctx, name, arguments)
        except ValueError as e:
            parser.error(f"arguments: {e}")
        except (tools.ToolError, Unavailable) as e:
            print(e, file=sys.stderr)
            return 1
        json.dump(answer, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    log(f"{__version__}, serving on stdio; cache: {cache.directory}")
    Server(ctx).serve()
    return 0
