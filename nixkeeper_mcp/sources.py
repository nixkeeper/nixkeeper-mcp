"""Where each piece of data is, and how it's read.

Two kinds of files, all public:

- The dashboard's data (nixkeeper.com/data/, the community instance of
  nixkeeper, every nixpkgs package): one row per package with everything
  nixkeeper joined from the digests, its verdicts included (docs/data.md in
  nixkeeper). What a package's state is, and what needs attention, comes
  from there, so the answers are the page's.
- The digests themselves (the `data` branch of each nixkeeper/digest-*
  repository, each its README's format): fresher (hourly), and searchable
  across all of nixpkgs by what each one knows.
"""

import csv
import gzip
import io
import json
import os
import re
import zlib

from .cache import Unavailable

DASHBOARD = os.environ.get("NIXKEEPER_MCP_DASHBOARD", "https://nixkeeper.com/data/")
DIGEST_OWNER = os.environ.get("NIXKEEPER_MCP_DIGEST_OWNER", "nixkeeper")


def page_of(dashboard):
    """The page a dashboard's data belongs to, served beside it
    (https://nixkeeper.com/data/: https://nixkeeper.com/)."""
    return dashboard[: -len("data/")] if dashboard.endswith("/data/") else dashboard


# The page the answers link to: the dashboard's, else NIXKEEPER_MCP_PAGE.
PAGE = os.environ.get("NIXKEEPER_MCP_PAGE") or page_of(DASHBOARD)


def digest_url(repo, path):
    return f"https://raw.githubusercontent.com/{DIGEST_OWNER}/{repo}/data/data/{path}"


BUILDS = digest_url("digest-builds", "builds.csv.gz")
BUILDS_META = digest_url("digest-builds", "meta.json")
PRS = digest_url("digest-prs", "prs.json")
ISSUES = digest_url("digest-prs", "issues.json")
PRS_META = digest_url("digest-prs", "meta.json")
ATTEMPTS = digest_url("digest-update-bot", "attempts.jsonl.gz")
QUEUE = digest_url("digest-update-bot", "queue.json.gz")
UPDATES_META = digest_url("digest-update-bot", "meta.json")
VULNERABILITIES = digest_url("digest-vulnerabilities", "vulnerabilities.json.gz")
VULNERABILITIES_META = digest_url("digest-vulnerabilities", "meta.json")
VERSIONS_META = digest_url("digest-versions", "meta.json")

METAS = {
    "builds": BUILDS_META,
    "prs": PRS_META,
    "updates": UPDATES_META,
    "vulnerabilities": VULNERABILITIES_META,
    "versions": VERSIONS_META,
}

HYDRA_BUILD = "https://hydra.nixos.org/build/"
PR_URL = "https://github.com/NixOS/nixpkgs/pull/"
ISSUE_URL = "https://github.com/NixOS/nixpkgs/issues/"

# names.json's status letters (nixkeeper's page dot): then "v" when
# vulnerable.
STATUS = {
    "f": "failed",
    "m": "outdated, update merged on master",
    "o": "outdated",
    "u": "up to date",
    "n": "can't be compared",
}

# The packages a PR's title names, nixpkgs' convention ("foo: drop"): in
# each of its ";"-separated parts, each of the ","-separated names before
# the ":" ("minimage: init at 0.1.4; d-seams: 2.10.0 -> 2.11.0",
# "chromium,chromedriver: ..."), as nixkeeper reads titles
# (nixkeeper/sources/github.py: title_packages). And Python's alias as the
# versioned set rows are kept by (prs_digest.py: package_key).
TITLE_NAMES = re.compile(r"^\s*([\w.+-]+(?:\s*,\s*[\w.+-]+)*):")


def title_packages(title):
    """The package names a PR's title is about."""
    found = set()
    for part in (title or "").split(";"):
        if m := TITLE_NAMES.match(part):
            found.update(n.strip() for n in m.group(1).split(","))
    return found


PYTHON_ALIAS = ("python3packages.", "python313packages.")


def package_key(name):
    key = (name or "").lower()
    if key.startswith(PYTHON_ALIAS[0]):
        key = PYTHON_ALIAS[1] + key[len(PYTHON_ALIAS[0]) :]
    return key


def _json(data):
    return json.loads(data)


def _gzip_json(data):
    return json.loads(gzip.decompress(data))


def status_text(letter):
    if not letter:
        return None
    text = STATUS.get(letter[0], letter)
    return text + ", vulnerable" if letter.endswith("v") else text


# The dashboard.


def index(cache):
    return cache.load(DASHBOARD + "index.json", _json)


def _names(data):
    """{lower-case name: [name, status letter, set?]}."""
    return {entry[0].lower(): entry for entry in json.loads(data)["names"]}


def names(cache):
    return cache.load(DASHBOARD + "names.json", _names)


def shard_of(name, count):
    """The shard a row is in (nixkeeper's datastore.shard_of)."""
    return zlib.crc32(name.encode()) % count


def resolve(cache, name):
    """The dashboard's name for name (any case; python3Packages.* as
    python313Packages.*), or None."""
    known, _ = names(cache)
    for key in (name.lower(), package_key(name)):
        if key in known:
            return known[key][0]
    return None


def row(cache, name):
    """(The dashboard's row for name, its File), or (None, None)."""
    found = resolve(cache, name)
    if not found:
        return None, None
    idx, _ = index(cache)
    shard = shard_of(found, idx.get("shardCount") or 1)
    rows, file = cache.load(f"{DASHBOARD}rows/{shard}.json", _json)
    for candidate in rows["packages"]:
        if candidate["name"] == found:
            return candidate, file
    return None, None


def view(cache, path):
    """A view's summary entries (views/attention.json, ...)."""
    data, file = cache.load(DASHBOARD + path, _json)
    return data["packages"], file


def merge_facts(cache):
    """{PR number: {"behind"?, "vulnerable"?}} from the dashboard's merge
    list (views/merge.json): what nixkeeper adds to a PR ready for the merge
    bot, as its "You can merge these" shows. {} without it."""
    try:
        data, _ = cache.load(DASHBOARD + "views/merge.json", _json)
    except Unavailable:
        return {}
    return {
        pr["number"]: {k: pr[k] for k in ("behind", "vulnerable") if pr.get(k)}
        for pr in data.get("prs") or []
    }


# Where a package is listed but Hydra doesn't build it: each Linux system
# apart, Darwin as one (nixkeeper's datastore.unbuilt_where, the page's
# struck platform tags).
UNBUILT_KEYS = ("x86_64-linux", "aarch64-linux", "darwin")


def _on_platform(row, key):
    platforms = row.get("platforms", {})
    if platforms is None:
        return True  # no restriction: every platform
    family = key.split("-")[-1]
    if not platforms.get(family):
        return False
    systems = platforms.get("systems")
    return key == family or not systems or key in systems


def _on_system(system, key):
    return system == key if "-" in key else system.endswith("-" + key)


def unbuilt_where(row):
    """The platforms row is listed for but Hydra doesn't build it on (none
    of its builds there exists, usually as a dependency isn't available
    there), while Hydra builds it elsewhere: [] when built everywhere
    listed, or nowhere (unfree, kept off it)."""
    builds = row.get("builds") or []
    found = []
    for key in UNBUILT_KEYS:
        here = [b for b in builds if _on_system(b["system"], key)]
        if (
            here
            and _on_platform(row, key)
            and all(b["status"] == "notBuilt" for b in here)
            and any(
                b["status"] != "notBuilt"
                for b in builds
                if not _on_system(b["system"], key)
            )
        ):
            found.append(key)
    return found


def view_slug(name):
    """A team's or list's file name (nixkeeper's: lower case, each run of
    other characters than letters and digits a "-")."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# The builds digest (digest-builds): 217,000 rows, about 25 MB as text. All
# of them parsed would take 400 MB, so the text is kept and searched (it's
# sorted by attribute), and only the builds that aren't ok are parsed.

BUILD_COLUMNS = (
    "attr",
    "system",
    "build",
    "status",
    "finished",
    "name",
    "lastSuccessBuild",
    "lastSuccessAt",
    "lastSuccessName",
    "blockedBy",
    "failedBecause",
    "failedExcerpt",
)


class Builds:
    def __init__(self, text):
        self.text = text
        self.header = text[: text.index(b"\n") + 1]
        self.not_ok = []
        for line in self._lines(text):
            # A cheap look before parsing: the status is the fourth field
            # and never quoted.
            fields = line.split(b",", 4)
            if len(fields) > 4 and fields[3] != b"ok":
                self.not_ok.extend(self._parse(line))

    @staticmethod
    def _lines(text):
        # Excerpts can hold newlines inside quotes: a record is complete
        # when its quotes are balanced.
        start = text.index(b"\n") + 1
        record = b""
        for line in text[start:].split(b"\n"):
            record = record + b"\n" + line if record else line
            if record.count(b'"') % 2 == 0:
                if record:
                    yield record
                record = b""

    def _parse(self, record):
        reader = csv.DictReader(io.StringIO((self.header + record).decode()))
        return [self._clean(r) for r in reader]

    @staticmethod
    def _clean(r):
        found = {k: v for k, v in r.items() if v}
        if found.get("blockedBy"):
            found["blockedBy"] = found["blockedBy"].split()
        if "build" in found:
            found["url"] = HYDRA_BUILD + found["build"]
        return found

    def of(self, attr):
        """The builds of attr (every system), from the text."""
        text = self.text
        needle = b"\n" + attr.encode() + b","
        at = text.find(needle)
        found = []
        while at != -1:
            # A line of a quoted excerpt can start like a row: a row starts
            # where the quotes before it are balanced.
            if text.count(b'"', 0, at) % 2:
                at = text.find(needle, at + 1)
                continue
            # And its own excerpt may run over lines: up to where its
            # quotes are balanced.
            end = text.find(b"\n", at + 1)
            while end != -1 and text.count(b'"', at, end) % 2:
                end = text.find(b"\n", end + 1)
            end = len(text) if end == -1 else end
            found.extend(self._parse(text[at + 1 : end]))
            at = text.find(needle, end)
        return found


def builds(cache):
    return cache.load(BUILDS, lambda data: Builds(gzip.decompress(data)))


# The update bot's digest (digest-update-bot).


class Attempts:
    """The bot's attempts, each kept as its line (34,000 parsed would take
    50 MB) and parsed when asked for."""

    def __init__(self, data):
        self.lines = {}
        for line in gzip.decompress(data).splitlines():
            if line.strip():
                # Each line starts {"attempt": ...} or {"attr": ...}: the
                # attribute is read from the whole line.
                self.lines[json.loads(line)["attr"]] = line

    def __contains__(self, attr):
        return attr in self.lines

    def __iter__(self):
        return iter(self.lines)

    def get(self, attr):
        line = self.lines.get(attr)
        return json.loads(line) if line is not None else None

    def entries(self):
        for line in self.lines.values():
            yield json.loads(line)


def attempts(cache):
    return cache.load(ATTEMPTS, Attempts)


def queue(cache):
    return cache.load(QUEUE, _gzip_json)


# The PR digest (digest-prs), kept to what the tools show: a PR's first 100
# files and its labels are left out, its packages and title say enough.

PR_FIELDS = (
    "n",
    "title",
    "author",
    "draft",
    "created",
    "updated",
    "base",
    "additions",
    "deletions",
    "changedFiles",
    "mergeable",
    "review",
    "approvedBy",
    "ci",
    "noPRFailures",
    "buckets",
    "packages",
    "maintainers",
    "update",
    "state",
    "blocksBot",
    "alreadyIn",
    "hydraFailing",
    "mergeBot",
)


def _prs(data):
    raw = json.loads(data)
    groups = {}
    for group in raw.get("groups") or []:
        for n in group["prs"]:
            others = [m for m in group["prs"] if m != n]
            groups.setdefault(n, []).append({"kind": group["kind"], "prs": others})
    prs = []
    for pr in raw["prs"]:
        kept = {k: pr[k] for k in PR_FIELDS if pr.get(k) not in (None, [], {})}
        kept["url"] = PR_URL + str(pr["n"])
        if pr["n"] in groups:
            kept["duplicates"] = groups[pr["n"]]
        keys = {package_key(p) for p in pr.get("packages") or []}
        keys |= {package_key(n) for n in title_packages(pr.get("title"))}
        if (pr.get("update") or {}).get("attr"):
            keys.add(package_key(pr["update"]["attr"]))
        kept["_keys"] = keys
        prs.append(kept)
    return {"generatedAt": raw.get("generatedAt"), "prs": prs}


def prs(cache):
    return cache.load(PRS, _prs)


def issues(cache):
    return cache.load(ISSUES, _json)


def vulnerabilities(cache):
    return cache.load(VULNERABILITIES, _gzip_json)


def meta(cache, name):
    return cache.load(METAS[name], _json)
