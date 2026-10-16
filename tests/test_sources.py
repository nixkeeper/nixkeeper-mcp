import json
import tomllib
import unittest
from pathlib import Path

import nixkeeper_mcp
from nixkeeper_mcp import sources

from . import fixtures


class Names(unittest.TestCase):
    def test_package_key(self):
        self.assertEqual(
            sources.package_key("python3Packages.Requests"),
            "python313packages.requests",
        )
        self.assertEqual(sources.package_key("Wesnoth"), "wesnoth")

    def test_view_slug(self):
        # nixkeeper's: lower case, each run of other characters a "-".
        self.assertEqual(sources.view_slug("Security review"), "security-review")
        self.assertEqual(sources.view_slug("Qt-KDE"), "qt-kde")

    def test_shard(self):
        # nixkeeper's datastore.shard_of: crc32 of the name % shards (on
        # nixkeeper.com, wesnoth's row is in rows/152.json of 256).
        self.assertEqual(sources.shard_of("wesnoth", 256), 152)
        self.assertEqual(sources.shard_of("anything", 1), 0)

    def test_title_packages(self):
        # Every part of a title, every name before its ":" (nixkeeper's
        # github.title_packages, 2026-10-16).
        self.assertEqual(
            sources.title_packages(
                "minimage: init at 0.1.4; d-seams: 2.10.0 -> 2.11.0, enable on darwin"
            ),
            {"minimage", "d-seams"},
        )
        self.assertEqual(
            sources.title_packages("chromium,chromedriver: 155.0.1 -> 155.0.2"),
            {"chromium", "chromedriver"},
        )
        self.assertEqual(sources.title_packages("Fix the build of everything"), set())

    def test_prs_found_by_every_name(self):
        raw = {
            "prs": [
                {
                    "n": 559522,
                    "title": "python3Packages.triton: 3.7.1 -> 3.8.0; "
                    "python3Packages.torch: 2.13.0 -> 2.14.0",
                    "packages": [],
                }
            ]
        }
        prs = sources._prs(json.dumps(raw).encode())["prs"]
        self.assertIn("python313packages.torch", prs[0]["_keys"])
        self.assertIn("python313packages.triton", prs[0]["_keys"])

    def test_page_beside_the_data(self):
        self.assertEqual(
            sources.page_of("https://nixkeeper.com/data/"), "https://nixkeeper.com/"
        )
        self.assertEqual(
            sources.page_of("https://example.org/nixkeeper/"),
            "https://example.org/nixkeeper/",
        )

    def test_status(self):
        self.assertEqual(sources.status_text("fv"), "failed, vulnerable")
        self.assertEqual(sources.status_text("m"), "outdated, update merged on master")
        self.assertIsNone(sources.status_text(None))


class Builds(unittest.TestCase):
    def setUp(self):
        self.builds = sources.Builds(fixtures.BUILDS_CSV.encode())

    def test_only_those_not_ok_parsed(self):
        self.assertEqual(
            sorted(b["attr"] for b in self.builds.not_ok),
            ["libfoo", "openttd", "python313Packages.bar", "zzz"],
        )

    def test_a_row_cleaned(self):
        bar = [b for b in self.builds.not_ok if b["status"] == "dependency"][0]
        self.assertEqual(bar["blockedBy"], ["libfoo", "source"])
        self.assertEqual(bar["url"], "https://hydra.nixos.org/build/40")
        self.assertNotIn("failedBecause", bar)  # empty fields left out

    def test_of_an_attribute(self):
        self.assertEqual([b["build"] for b in self.builds.of("wesnoth")], ["11", "12"])
        libfoo = self.builds.of("libfoo")
        self.assertEqual([b["build"] for b in libfoo], ["30", "31"])
        # A line of an excerpt starting with "openttd," isn't openttd's row.
        self.assertEqual([b["build"] for b in self.builds.of("openttd")], ["21"])
        self.assertEqual(self.builds.of("wesnot"), [])


class Attempts(unittest.TestCase):
    def test_parsed_when_asked(self):
        attempts, _ = sources.attempts(fixtures.FakeCache())
        self.assertIn("wesnoth", attempts)
        self.assertEqual(attempts.get("wesnoth")["pending"], "2026-10-14")
        self.assertIsNone(attempts.get("nosuch"))
        self.assertEqual(len(list(attempts.entries())), 3)


class Prs(unittest.TestCase):
    def test_kept_with_their_packages(self):
        prs, _ = sources.prs(fixtures.FakeCache())
        first, second, third = prs["prs"]
        self.assertEqual(first["_keys"], {"wesnoth"})
        # "games: ..." names "games", as nixkeeper reads titles.
        self.assertEqual(second["_keys"], {"games", "wesnoth", "openttd"})
        self.assertEqual(third["_keys"], {"python313packages.requests"})
        self.assertNotIn("files", first)
        self.assertEqual(second["duplicates"], [{"kind": "sameDiff", "prs": [1]}])


class Row(unittest.TestCase):
    def test_found_in_its_shard(self):
        cache = fixtures.FakeCache()
        row, _ = sources.row(cache, "OPENTTD")
        self.assertEqual(row["nixVersion"], "14.1")
        self.assertIn(sources.DASHBOARD + "rows/0.json", cache.asked)
        self.assertEqual(sources.row(cache, "nosuch"), (None, None))


class Version(unittest.TestCase):
    def test_one_version(self):
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            version = tomllib.load(f)["project"]["version"]
        self.assertEqual(nixkeeper_mcp.__version__, version)


class Fixtures(unittest.TestCase):
    def test_well_formed(self):
        for url, data in fixtures.files().items():
            with self.subTest(url):
                if url.endswith(".json"):
                    json.loads(data)


if __name__ == "__main__":
    unittest.main()
