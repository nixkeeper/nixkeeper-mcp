import unittest
from datetime import timedelta

from nixkeeper_mcp import sources, tools

from . import fixtures


def call(tool, **args):
    return tools.call(fixtures.Context(), tool, args)


class Arguments(unittest.TestCase):
    def test_what_the_schema_says(self):
        for args, wrong in (
            ({}, "missing argument: name"),
            ({"name": 1}, "name must be a string"),
            ({"name": "x", "nmae": "y"}, "unknown argument: nmae"),
            ({"name": "x", "repology": "yes"}, "repology must be a boolean"),
        ):
            with self.subTest(args), self.assertRaisesRegex(tools.ToolError, wrong):
                tools.call(fixtures.Context(), "package", args)

    def test_enums_and_bounds(self):
        with self.assertRaisesRegex(tools.ToolError, "kind must be one of"):
            call("needs_attention", kind="sometimes")
        with self.assertRaisesRegex(tools.ToolError, "limit must be at least 1"):
            call("find_packages", query="x", limit=0)
        with self.assertRaisesRegex(tools.ToolError, "limit must be an integer"):
            call("find_packages", query="x", limit=True)

    def test_since(self):
        now = fixtures.NOW
        self.assertEqual(tools.since_time("24h", now), now - timedelta(hours=24))
        self.assertEqual(tools.since_time("2w", now), now - timedelta(weeks=2))
        self.assertEqual(
            tools.since_time("2026-10-01", now).isoformat(),
            "2026-10-01T00:00:00+00:00",
        )
        with self.assertRaisesRegex(tools.ToolError, "since"):
            tools.since_time("last tuesday", now)


class Package(unittest.TestCase):
    def test_the_dashboards_row_with_what_the_digests_have_newer(self):
        got = call("package", name="Wesnoth")
        self.assertEqual(got["name"], "wesnoth")
        self.assertEqual(got["status"], "outdated")
        self.assertEqual(got["page"], "https://nixkeeper.com/?pkg=wesnoth")
        self.assertNotIn("dataFile", got)
        self.assertEqual(got["builds"][0]["url"], "https://hydra.nixos.org/build/10")
        newer = got["newerInDigests"]
        # x86_64-linux was built again (12 > 10); aarch64-darwin wasn't.
        self.assertEqual([b["build"] for b in newer["builds"]], ["12"])
        self.assertEqual(newer["updateAttempt"]["outcome"], "prOpened")
        self.assertEqual(newer["updatePending"], "2026-10-14")
        self.assertEqual(got["readFrom"]["dashboard"]["syncedAt"], INDEX_AT)

    def test_an_older_version_kept_says_so(self):
        got = call("package", name="firefox-esr")
        self.assertEqual(got["status"], "older version kept beside firefox 158.0.1")

    def test_repology_trimmed_to_nixpkgs_and_the_newest(self):
        got = call("package", name="wesnoth")["repology"]
        self.assertEqual(
            [e["repo"] for e in got["nixpkgs"]], ["nix_unstable", "nix_stable_26_05"]
        )
        self.assertEqual([e["repo"] for e in got["newestElsewhere"]], ["arch"])
        self.assertEqual(got["repositories"], 4)
        self.assertEqual(
            len(call("package", name="wesnoth", repology=True)["repology"]), 4
        )

    def test_python3packages_is_the_versioned_set(self):
        self.assertEqual(
            call("package", name="python3Packages.requests")["name"],
            "python313Packages.requests",
        )

    def test_an_attribute_only_the_digests_know(self):
        got = call("package", name="libfoo")
        self.assertFalse(got["inDashboard"])
        self.assertEqual(
            [b["system"] for b in got["builds"]], ["x86_64-linux", "aarch64-darwin"]
        )

    def test_unknown_suggests(self):
        with self.assertRaisesRegex(
            tools.ToolError, "did you mean: wesnoth, wesnoth-devel"
        ):
            call("package", name="wesno")


INDEX_AT = fixtures.INDEX["checkedAt"]


class FindPackages(unittest.TestCase):
    def test_exact_then_prefix_then_containing(self):
        got = call("find_packages", query="wesnoth")
        self.assertEqual(
            [p["name"] for p in got["packages"]], ["wesnoth", "wesnoth-devel"]
        )
        got = call("find_packages", query="ttd")
        self.assertEqual(
            got["packages"], [{"name": "openttd", "status": "failed, vulnerable"}]
        )
        got = call("find_packages", query="aeson")
        self.assertEqual(got["packages"][0]["set"], "haskellPackages")

    def test_limit(self):
        got = call("find_packages", query="e", limit=2)
        self.assertEqual(len(got["packages"]), 2)
        self.assertGreater(got["matches"], 2)


class NeedsAttention(unittest.TestCase):
    def test_a_maintainers_packages_that_need_it_worst_first(self):
        got = call("needs_attention", maintainer="@IEDAME")
        self.assertEqual(got["view"], "views/maintainer/iedame.json")
        # wesnoth-devel is up to date: not listed.
        self.assertEqual([p["name"] for p in got["packages"]], ["openttd", "wesnoth"])
        openttd = got["packages"][0]
        self.assertEqual(openttd["why"], ["failing", "vulnerable"])
        self.assertEqual(openttd["failingOn"], ["x86_64-linux"])
        self.assertEqual(got["counts"], {"failing": 1, "vulnerable": 1, "outdated": 1})

    def test_kind_and_platform(self):
        got = call("needs_attention", maintainer="iedame", kind="outdated")
        self.assertEqual([p["name"] for p in got["packages"]], ["wesnoth"])
        got = call("needs_attention", maintainer="iedame", kind="all")
        self.assertEqual(len(got["packages"]), 3)
        # openttd isn't available on Darwin.
        got = call("needs_attention", maintainer="iedame", platform="darwin")
        self.assertEqual([p["name"] for p in got["packages"]], ["wesnoth"])
        got = call("needs_attention", kind="failing", platform="darwin")
        self.assertEqual(got["packages"], [])

    def test_staging(self):
        # On its way: the update on staging-next, with the other fields.
        got = call("needs_attention", maintainer="iedame", kind="outdated")
        self.assertEqual(
            got["packages"][0]["stagingPR"],
            {
                "on": "staging-next",
                "to": "1.18.8",
                "url": "https://github.com/NixOS/nixpkgs/pull/9",
            },
        )
        # A forecast: its own kind, not in what needs attention now.
        got = call("needs_attention", maintainer="iedame", kind="stagingNext")
        self.assertEqual([p["name"] for p in got["packages"]], ["wesnoth-devel"])
        self.assertEqual(
            got["packages"][0]["breaksOnStagingNext"],
            {"systems": ["x86_64-linux"], "evaluatedAt": "2026-10-16T01:08:22Z"},
        )
        got = call("needs_attention", maintainer="iedame")
        self.assertNotIn("wesnoth-devel", [p["name"] for p in got["packages"]])

    def test_all_of_nixpkgs_and_waiting(self):
        got = call("needs_attention")
        self.assertEqual(got["view"], "views/attention.json")
        unciv = [p for p in got["packages"] if p["name"] == "unciv"][0]
        self.assertEqual(unciv["why"], ["waiting"])

    def test_a_team(self):
        self.assertEqual(
            call("needs_attention", team="Gaming")["view"], "views/team/gaming.json"
        )

    def test_unknown(self):
        with self.assertRaisesRegex(tools.ToolError, "no packages list 'nobody'"):
            call("needs_attention", maintainer="nobody")
        with self.assertRaisesRegex(tools.ToolError, "teams: Gaming"):
            call("needs_attention", team="Nobody")
        with self.assertRaisesRegex(tools.ToolError, "one of maintainer, team or list"):
            call("needs_attention", maintainer="iedame", team="Gaming")


class CanMerge(unittest.TestCase):
    """The PRs a maintainer or team can merge with the merge bot."""

    def test_a_maintainers(self):
        got = call("needs_attention", maintainer="iedame")["canMerge"]
        self.assertEqual(got["matches"], 1)
        self.assertEqual(
            got["prs"][0],
            {
                "n": 1,
                "title": "wesnoth: 1.18.7 -> 1.18.8",
                "url": "https://github.com/NixOS/nixpkgs/pull/1",
                "author": "r-ryantm",
                "created": "2026-10-12T00:00:00Z",
                "base": "master",
                # What the dashboard's merge list adds.
                "behind": "1.18.9",
                "vulnerable": True,
            },
        )
        self.assertIn("@NixOS/nixpkgs-maintainers", got["note"])
        self.assertIn("prs", call("needs_attention", maintainer="iedame")["readFrom"])
        # Nothing to merge: no canMerge (all of nixpkgs: not asked).
        self.assertNotIn("canMerge", call("needs_attention"))

    def test_a_teams_by_meta_teams_only(self):
        got = call("needs_attention", team="Gaming")["canMerge"]
        self.assertEqual(got["prs"][0]["canMerge"], ["iedame"])
        # Packages a list of the team's name adds: their own maintainers'.
        ctx = fixtures.Context()
        entries = [
            {"name": e["name"], "teamsByList": ["Gaming"]}
            for e in fixtures.MAINTAINER_IEDAME["packages"]
        ]
        answer = {"readFrom": {}}
        tools._add_can_merge(ctx.cache, answer, entries, None, "gaming")
        self.assertNotIn("canMerge", answer)

    def test_what_nixkeeper_adds(self):
        got = call("needs_attention", maintainer="iedame")["canMerge"]["prs"][0]
        self.assertEqual((got["behind"], got["vulnerable"]), ("1.18.9", True))

    def test_pull_requests(self):
        got = call("pull_requests", can_merge="@IEDAME")
        self.assertEqual([p["n"] for p in got["prs"]], [1])
        self.assertEqual(got["prs"][0]["noPRFailures"], "SUCCESS")
        self.assertIn("merge bot", got["note"])
        self.assertEqual(call("pull_requests", can_merge="someone")["matches"], 0)


class NewFacts(unittest.TestCase):
    """Since nixkeeper 0.20.0: platforms listed but not built, the bot's
    expected day, the overview's numbers."""

    def test_package_not_built_where_listed(self):
        self.assertEqual(
            call("package", name="wesnoth-devel")["notBuiltWhereListed"], ["darwin"]
        )
        self.assertNotIn("notBuiltWhereListed", call("package", name="wesnoth"))

    def test_unbuilt_rule(self):
        def row(platforms, *builds):
            return {
                "platforms": platforms,
                "builds": [{"system": s, "status": st} for s, st in builds],
            }

        both = {"linux": True, "darwin": True}
        self.assertEqual(
            sources.unbuilt_where(
                row(both, ("x86_64-linux", "ok"), ("aarch64-linux", "notBuilt"))
            ),
            ["aarch64-linux"],
        )
        nowhere = row(
            both, ("x86_64-linux", "notBuilt"), ("aarch64-darwin", "notBuilt")
        )
        self.assertEqual(sources.unbuilt_where(nowhere), [])
        anywhere = row(None, ("x86_64-linux", "ok"), ("aarch64-darwin", "notBuilt"))
        self.assertEqual(sources.unbuilt_where(anywhere), ["darwin"])

    def test_overview_numbers(self):
        got = call("overview")
        self.assertEqual(got["numbers"]["builds"], 5)
        self.assertEqual(got["mergeBot"]["prs"], 1)
        self.assertEqual(got["notBuiltWhereListed"], 1)


class Overview(unittest.TestCase):
    def test_counts_and_blockers(self):
        got = call("overview")
        self.assertEqual(got["counts"]["tracked"], 5)
        self.assertEqual(
            got["blockers"]["top"], [{"name": "libfoo", "packages": 2, "builds": 3}]
        )
        self.assertEqual(got["buildFailureCauses"][0]["title"], "A compiler change")


class BuildFailures(unittest.TestCase):
    def test_failed_newest_first(self):
        got = call("build_failures")
        self.assertEqual([b["attr"] for b in got["builds"]], ["openttd", "libfoo"])
        libfoo = got["builds"][1]
        # The excerpt's second line starts like a row, and isn't one.
        self.assertTrue(libfoo["failedExcerpt"].startswith("FAIL: test_a\nopenttd"))
        self.assertEqual(got["evaluation"]["eval"], 100)

    def test_filters(self):
        self.assertEqual(call("build_failures", reason="tests")["matches"], 1)
        self.assertEqual(call("build_failures", since="24h")["matches"], 1)
        got = call("build_failures", status="dependency", blocked_by="LIBFOO")
        self.assertEqual(got["builds"][0]["blockedBy"], ["libfoo", "source"])
        got = call("build_failures", package="python313Packages", status="notOk")
        self.assertEqual([b["attr"] for b in got["builds"]], ["python313Packages.bar"])
        self.assertEqual(call("build_failures", search="TTD")["matches"], 1)
        self.assertEqual(call("build_failures", status="queued")["matches"], 1)

    def test_longest_failing_never_first(self):
        got = call("build_failures", status="notOk", sort="longestFailing")
        self.assertEqual(got["builds"][0]["attr"], "python313Packages.bar")


class PullRequests(unittest.TestCase):
    def test_touching_a_package(self):
        got = call("pull_requests", package="wesnoth")
        self.assertEqual([p["n"] for p in got["prs"]], [1, 2])
        first = got["prs"][0]
        self.assertEqual(first["url"], "https://github.com/NixOS/nixpkgs/pull/1")
        self.assertEqual(first["duplicates"], [{"kind": "sameDiff", "prs": [2]}])
        self.assertNotIn("files", first)
        self.assertNotIn("_keys", first)
        # By the title's package, Python's alias as the versioned set.
        got = call("pull_requests", package="python313Packages.requests")
        self.assertEqual([p["n"] for p in got["prs"]], [3])

    def test_filters(self):
        self.assertEqual(call("pull_requests", merge_bot="ready")["matches"], 1)
        self.assertEqual(call("pull_requests", merge_bot="eligible")["matches"], 2)
        self.assertEqual(
            call("pull_requests", drafts=False, package="openttd")["matches"], 0
        )
        self.assertEqual(call("pull_requests", author="someone")["prs"][0]["n"], 2)
        self.assertEqual(call("pull_requests", state="superseded")["prs"][0]["n"], 3)
        got = call("pull_requests", sort="created")
        self.assertEqual([p["n"] for p in got["prs"]], [3, 1, 2])


class Issues(unittest.TestCase):
    def test_about_a_package(self):
        got = call("issues", package="openttd")
        # The build failure it names, and its name whole in a title (not
        # openttd-jgrpp's).
        self.assertEqual([i["n"] for i in got["issues"]], [11, 10])
        self.assertEqual(
            got["issues"][0]["url"], "https://github.com/NixOS/nixpkgs/issues/11"
        )

    def test_kind_and_verdict(self):
        self.assertEqual(call("issues", kind="update")["issues"][0]["n"], 12)
        self.assertEqual(
            call("issues", kind="build", verdict="builds")["issues"][0]["n"], 13
        )


class UpdateAttempts(unittest.TestCase):
    def test_one_package_with_its_place_in_the_queue(self):
        got = call("update_attempts", package="wesnoth")
        self.assertEqual(got["attempt"]["outcome"], "prOpened")
        # Halfway through a 10-day queue made on the 14th.
        self.assertEqual(got["queued"]["expectedBy"], "2026-10-19")
        self.assertTrue(got["queued"]["script"])
        self.assertEqual(
            call("update_attempts", package="python313Packages.requests")["attr"],
            "python3Packages.requests",
        )
        with self.assertRaisesRegex(tools.ToolError, "no attempt"):
            call("update_attempts", package="nosuch")

    def test_filters_newest_first(self):
        got = call("update_attempts")
        self.assertEqual(
            [a["attr"] for a in got["attempts"]],
            ["openttd", "wesnoth", "python3Packages.requests"],
        )
        got = call("update_attempts", outcome="failed", reason="hash", since="7d")
        self.assertEqual([a["attr"] for a in got["attempts"]], ["openttd"])
        self.assertEqual(call("update_attempts", since="2026-10-11")["matches"], 1)


class Vulnerabilities(unittest.TestCase):
    def test_a_packages(self):
        got = call("vulnerabilities", package="openttd")
        cve = got["tracker"][0]
        self.assertEqual(cve["cve"], "CVE-2026-1")
        self.assertEqual(cve["status"], {"version": "14.1", "status": "affected"})
        self.assertNotIn("packages", cve)  # the others' statuses
        self.assertEqual(cve["github"], "https://github.com/NixOS/nixpkgs/issues/5")
        got = call("vulnerabilities", package="python3Packages.requests")
        self.assertEqual(got["osv"][0]["id"], "PYSEC-1")

    def test_a_cve_or_advisory(self):
        self.assertEqual(
            call("vulnerabilities", cve="nixpkgs-2026-1")["tracker"][0]["id"], "1"
        )
        self.assertEqual(
            call("vulnerabilities", cve="ghsa-1")["osv"][0]["id"], "PYSEC-1"
        )
        self.assertEqual(
            call("vulnerabilities", cve="CVE-2023-9")["osv"][0]["id"], "PYSEC-1"
        )

    def test_affecting_something_worst_first(self):
        got = call("vulnerabilities")
        self.assertEqual(
            [s["cve"] for s in got["tracker"]], ["CVE-2026-2", "CVE-2026-1"]
        )
        self.assertEqual(got["tracker"][1]["affectedPackages"], ["openttd"])
        self.assertEqual(call("vulnerabilities", severity="high")["matches"], 1)


class DataStatus(unittest.TestCase):
    def test_each_source(self):
        got = call("data_status")
        self.assertEqual(got["dashboard"]["syncedAt"], INDEX_AT)
        self.assertEqual(got["builds"]["meta"]["eval"], 100)
        self.assertEqual(got["cache"]["files"], 0)

    def test_one_down_says_so(self):
        cache = fixtures.FakeCache()
        del cache.data[fixtures.sources.PRS_META]
        got = tools.call(fixtures.Context(cache), "data_status", {})
        self.assertIn("error", got["prs"])
        self.assertIn("meta", got["builds"])


class Listing(unittest.TestCase):
    def test_well_formed(self):
        names = [t["name"] for t in tools.listed()]
        self.assertEqual(len(names), len(set(names)))
        for tool in tools.listed():
            with self.subTest(tool["name"]):
                self.assertRegex(tool["name"], r"^[A-Za-z0-9_.-]{1,128}$")
                self.assertTrue(tool["description"])
                schema = tool["inputSchema"]
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                for name in schema.get("required", []):
                    self.assertIn(name, schema["properties"])
                for prop in schema.get("properties", {}).values():
                    self.assertIn(prop["type"], ("string", "integer", "boolean"))
                    self.assertTrue(prop["description"])


if __name__ == "__main__":
    unittest.main()
