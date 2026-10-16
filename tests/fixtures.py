"""A small nixkeeper, in the formats the dashboard and the digests publish
(nixkeeper's docs/data.md, each digest's README), served by FakeCache."""

import gzip
import json
from datetime import UTC, datetime

from nixkeeper_mcp import sources
from nixkeeper_mcp.cache import File, NotFound

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
CHECKED = NOW.timestamp() - 60

INDEX = {
    "format": 2,
    "checkedAt": "2026-10-14T09:00:00+00:00",
    "version": "0.18.0",
    "packageCount": 5,
    "shardCount": 1,
    "allPackages": True,
    "counts": {"tracked": 5, "outdated": 2, "buildFailures": 1},
    "highlights": {"failing": {"count": 1, "newest": [], "oldest": []}},
    "blockers": {"count": 1, "packages": 2, "top": [["libfoo", True, 2, 3]]},
    "causes": {
        "builds": [
            {
                "key": "abc",
                "count": 3,
                "reason": "compile",
                "line": "error: x",
                "signature": "error: …",
                "title": "A compiler change",
            }
        ],
        "bot": {"hash": 2},
    },
    "fixed": {"days": 7},
    "views": {"teams": {"Gaming": 2}},
    "sources": {
        "hydra": {"used": True, "at": "2026-10-14T06:00:00+00:00", "eval": 100},
        "updates": {"used": True, "at": "2026-10-14T08:00:00+00:00"},
    },
}

NAMES = {
    "names": [
        ["wesnoth", "o"],
        ["wesnoth-devel", "u"],
        ["openttd", "fv"],
        ["python313Packages.requests", "u"],
        ["haskellPackages.aeson", "o", "haskellPackages"],
        ["unciv", "m"],
    ]
}

WESNOTH = {
    "name": "wesnoth",
    "attrs": ["wesnoth"],
    "dataFile": "wesnoth.json",
    "nixStatus": "outdated",
    "nixVersion": "1.18.7",
    "refVersion": "1.18.8",
    "maintainers": ["iedame"],
    "teams": ["Gaming"],
    "platforms": {"linux": True, "darwin": True},
    "builds": [
        {"attr": "wesnoth", "system": "x86_64-linux", "status": "ok", "build": 10},
        {"attr": "wesnoth", "system": "aarch64-darwin", "status": "ok", "build": 11},
    ],
    "update": {
        "attr": "wesnoth",
        "date": "2026-10-01",
        "outcome": "noChange",
        "from": "0",
        "to": "1",
    },
    "repology": [
        {"repo": "nix_unstable", "srcname": "wesnoth", "version": "1.18.7"},
        {"repo": "nix_stable_25_11", "srcname": "wesnoth", "version": "1.18.5"},
        {"repo": "nix_stable_26_05", "srcname": "wesnoth", "version": "1.18.6"},
        {"repo": "arch", "srcname": "wesnoth", "version": "1.18.8", "status": "newest"},
    ],
}
OPENTTD = {
    "name": "openttd",
    "attrs": ["openttd"],
    "nixStatus": "newest",
    "nixVersion": "14.1",
    "maintainers": ["iedame", "someone"],
    "platforms": {"linux": True, "darwin": False},
    "builds": [
        {
            "attr": "openttd",
            "system": "x86_64-linux",
            "status": "failed",
            "build": 20,
            "failedBecause": "compile",
        }
    ],
    "failingSince": "2026-09-01T00:00:00+00:00",
    "vulnerabilities": [
        {"id": "CVE-2026-1", "source": "tracker", "verdict": "affected"}
    ],
    "update": None,
}
ROWS = {
    "packages": [
        WESNOTH,
        {"name": "wesnoth-devel", "attrs": ["wesnoth-devel"], "nixStatus": "newest"},
        OPENTTD,
        {"name": "python313Packages.requests", "attrs": ["python313Packages.requests"]},
        {"name": "haskellPackages.aeson", "set": "haskellPackages"},
        {"name": "unciv", "nixStatus": "outdated"},
    ]
}


def summary(row, **more):
    entry = {k: v for k, v in row.items() if k not in ("dataFile", "repology")}
    entry["builds"] = [
        {"status": b["status"], "system": b["system"]} for b in row.get("builds", [])
    ]
    return {**entry, **more}


MAINTAINER_IEDAME = {
    "packages": [
        summary(OPENTTD, vuln={"n": 1, "by": ["tracker"], "severity": "high"}),
        summary(
            WESNOTH,
            stagingPR={
                "number": 9,
                "on": "staging-next",
                "to": "1.18.8",
                "url": "https://github.com/NixOS/nixpkgs/pull/9",
            },
        ),
        summary(
            {"name": "wesnoth-devel", "nixStatus": "newest", "builds": []},
            # Builds on master, fails its own build on staging-next.
            stagingNextBreaks={
                "eval": 1830302,
                "evaluatedAt": "2026-10-16T01:08:22Z",
                "builds": [{"attr": "wesnoth-devel", "system": "x86_64-linux"}],
            },
        ),
    ]
}
ATTENTION = {
    "packages": [
        summary(OPENTTD, vuln={"n": 1, "by": ["tracker"], "severity": "high"}),
        summary(WESNOTH),
        summary({"name": "unciv", "nixStatus": "outdated", "builds": []}),
    ]
}

BUILDS_CSV = (
    ",".join(sources.BUILD_COLUMNS)
    + "\n"
    + "\n".join(
        [
            "libfoo,x86_64-linux,30,failed,2026-10-13T10:00:00+00:00,libfoo-1.0,"
            '25,2026-09-01T00:00:00+00:00,libfoo-1.0,,tests,"FAIL: test_a\n'
            "openttd,x86_64-linux,99: looks like a row, isn't\"",
            "libfoo,aarch64-darwin,31,ok,2026-10-12T00:00:00+00:00,libfoo-1.0,,,,,,",
            "openttd,x86_64-linux,21,failed,2026-10-14T01:00:00+00:00,openttd-14.1,"
            "15,2026-09-01T00:00:00+00:00,openttd-14.0,,compile,error: x",
            "python313Packages.bar,aarch64-linux,40,dependency,"
            "2026-10-10T00:00:00+00:00,python3.13-bar-2,,never,,libfoo source,,",
            "wesnoth,aarch64-darwin,11,ok,2026-10-01T00:00:00+00:00,wesnoth-1.18.7,"
            ",,,,,",
            "wesnoth,x86_64-linux,12,ok,2026-10-13T00:00:00+00:00,wesnoth-1.18.7,,,,,,",
            "zzz,x86_64-linux,50,queued,,zzz-1,,,,,,",
        ]
    )
    + "\n"
)

ATTEMPTS = [
    {
        "attr": "openttd",
        "attempt": {
            "attr": "openttd",
            "date": "2026-10-12",
            "started": 300,
            "outcome": "failed",
            "failedBecause": "hash",
            "from": "14.0",
            "to": "14.1",
        },
    },
    {
        "attr": "python3Packages.requests",
        "attempt": {"date": "2026-09-01", "started": 100, "outcome": "noChange"},
    },
    {
        "attr": "wesnoth",
        "attempt": {
            "attr": "wesnoth",
            "date": "2026-10-10",
            "started": 200,
            "outcome": "prOpened",
            "from": "1.18.7",
            "to": "1.18.8",
        },
        "pending": "2026-10-14",
    },
]

QUEUE = {
    "cycleDays": 10.0,
    "positions": 100,
    "updatedAt": "2026-10-14T00:00:00+00:00",
    "queue": {
        "wesnoth": {
            "position": 50,
            "script": True,
            "candidates": [["1.18.7", "1.18.8", "https://example.org"]],
        }
    },
}

PRS = {
    "format": 1,
    "generatedAt": "2026-10-14T11:00:00+00:00",
    "groups": [{"key": "k", "kind": "sameDiff", "prs": [1, 2]}],
    "prs": [
        {
            "n": 1,
            "title": "wesnoth: 1.18.7 -> 1.18.8",
            "author": "r-ryantm",
            "draft": False,
            "updated": "2026-10-13T00:00:00Z",
            "created": "2026-10-12T00:00:00Z",
            "base": "master",
            "buckets": ["update", "bot"],
            "packages": ["wesnoth"],
            "files": ["pkgs/by-name/we/wesnoth/package.nix"],
            "labels": ["x"],
            "update": {"attr": "wesnoth", "from": "1.18.7", "to": "1.18.8"},
            "mergeBot": {"ready": True, "label": True},
        },
        {
            "n": 2,
            "title": "games: tidy up",
            "author": "Someone",
            "draft": True,
            "updated": "2026-10-11T00:00:00Z",
            "created": "2026-10-01T00:00:00Z",
            "base": "staging",
            "buckets": [],
            "packages": ["wesnoth", "openttd"],
        },
        {
            "n": 3,
            "title": "python3Packages.requests: 2.32 -> 2.33",
            "author": "a",
            "draft": False,
            "updated": "2026-10-14T00:00:00Z",
            "created": "2026-10-14T00:00:00Z",
            "base": "master",
            "buckets": ["update", "python"],
            "packages": [],
            "state": "superseded",
            "mergeBot": {"label": True},
        },
    ],
}

ISSUES = {
    "format": 1,
    "generatedAt": "2026-10-14T11:00:00+00:00",
    "issues": [
        {
            "n": 10,
            "title": "Build failure: openttd",
            "hydra": {"package": "openttd", "verdict": "failing"},
        },
        {"n": 11, "title": "OpenTTD crashes on start"},
        {
            "n": 12,
            "title": "Update request: wesnoth 1.18.7 → 1.18.8",
            "update": {"package": "wesnoth", "verdict": "open"},
        },
        {"n": 13, "title": "Build failure: libfoo", "hydra": {"verdict": "builds"}},
    ],
}

VULNERABILITIES = {
    "format": 1,
    "tracker": {
        "suggestions": {
            "1": {
                "cve": "CVE-2026-1",
                "issue": "NIXPKGS-2026-1",
                "title": "A hole",
                "score": 7.5,
                "severity": "high",
                "packages": {
                    "openttd": {"version": "14.1", "status": "affected"},
                    "other": {"version": "1", "status": "unaffected"},
                },
            },
            "2": {
                "cve": "CVE-2026-2",
                "score": 9.8,
                "severity": "critical",
                "packages": {"zzz": {"status": "affected"}},
            },
            "3": {
                "cve": "CVE-2026-3",
                "score": 5.0,
                "severity": "medium",
                "packages": {"zzz": {"status": "unaffected"}},
            },
        },
        "issues": {
            "NIXPKGS-2026-1": {
                "status": "affected",
                "github": "https://github.com/NixOS/nixpkgs/issues/5",
            }
        },
        "packages": {
            "openttd": [
                {
                    "suggestion": "1",
                    "version": "14.1",
                    "status": "affected",
                    "branch": "master",
                }
            ]
        },
    },
    "osv": {
        "advisories": {
            "PYSEC-1": {
                "aliases": ["GHSA-1"],
                "cves": ["CVE-2023-9"],
                "ecosystem": "PyPI",
                "package": "requests",
            }
        },
        "packages": {"python313Packages.requests": ["PYSEC-1"]},
    },
}

BUILDS_META = {
    "eval": 100,
    "revision": "abc",
    "fetchedAt": "2026-10-14T06:00:00+00:00",
}


def files():
    d = sources.DASHBOARD
    found = {
        d + "index.json": json.dumps(INDEX).encode(),
        d + "names.json": json.dumps(NAMES).encode(),
        d + "rows/0.json": json.dumps(ROWS).encode(),
        d + "views/attention.json": json.dumps(ATTENTION).encode(),
        d + "views/maintainer/iedame.json": json.dumps(MAINTAINER_IEDAME).encode(),
        d + "views/team/gaming.json": json.dumps(MAINTAINER_IEDAME).encode(),
        sources.BUILDS: gzip.compress(BUILDS_CSV.encode()),
        sources.ATTEMPTS: gzip.compress(
            "\n".join(json.dumps(a) for a in ATTEMPTS).encode() + b"\n"
        ),
        sources.QUEUE: gzip.compress(json.dumps(QUEUE).encode()),
        sources.PRS: json.dumps(PRS).encode(),
        sources.ISSUES: json.dumps(ISSUES).encode(),
        sources.VULNERABILITIES: gzip.compress(json.dumps(VULNERABILITIES).encode()),
    }
    for name, url in sources.METAS.items():
        found[url] = json.dumps(BUILDS_META if name == "builds" else {}).encode()
    return found


class FakeCache:
    """The cache's interface (get, load, files), over FILES."""

    directory = "/nonexistent"
    ttl = 900
    offline = False

    def __init__(self, files=None):
        self.data = files if files is not None else globals()["files"]()
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        if url not in self.data:
            raise NotFound(url)
        return File(self.data[url], CHECKED, CHECKED)

    def load(self, url, parse):
        file = self.get(url)
        return parse(file.data), file

    def files(self):
        return []


class Context:
    def __init__(self, cache=None):
        self.cache = cache or FakeCache()

    def now(self):
        return NOW
