"""The tools: what an assistant can ask, each answered from the dashboard's
data or one digest (sources.py), with when that data was read."""

import re
from datetime import UTC, datetime, timedelta

from . import sources
from .cache import NotFound


class ToolError(Exception):
    """A tool's answer that something's wrong with what it was asked (an
    unknown package, a bad date): shown to the assistant to correct."""


# Arguments.


def check_arguments(schema, args):
    """args against a tool's inputSchema, as far as its schemas go: object
    of known properties, each a string, integer or boolean, enums and
    bounds. Raises ToolError saying what's wrong."""
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            raise ToolError(f"missing argument: {name}")
    types = {"string": str, "integer": int, "boolean": bool}
    article = {"string": "a", "integer": "an", "boolean": "a"}
    for name, value in args.items():
        if name not in props:
            known = ", ".join(sorted(props)) or "none"
            raise ToolError(f"unknown argument: {name} (known: {known})")
        prop = props[name]
        want = types[prop["type"]]
        if not isinstance(value, want) or (want is int and isinstance(value, bool)):
            raise ToolError(f"{name} must be {article[prop['type']]} {prop['type']}")
        if "enum" in prop and value not in prop["enum"]:
            raise ToolError(f"{name} must be one of: {', '.join(prop['enum'])}")
        if "minimum" in prop and value < prop["minimum"]:
            raise ToolError(f"{name} must be at least {prop['minimum']}")
        if "maximum" in prop and value > prop["maximum"]:
            raise ToolError(f"{name} must be at most {prop['maximum']}")


def parse_time(value):
    """An aware datetime from an ISO 8601 date or time, or a plain day."""
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def since_time(value, now):
    """`since`: "7d", "24h", "2w", or an ISO 8601 day or time."""
    if m := re.fullmatch(r"(\d+)\s*([hdw])", value.strip()):
        unit = {"h": "hours", "d": "days", "w": "weeks"}[m.group(2)]
        return now - timedelta(**{unit: int(m.group(1))})
    try:
        return parse_time(value.strip())
    except ValueError:
        raise ToolError(
            f"since: {value!r} isn't a day (2026-10-01), a time, or 24h, 7d, 2w"
        ) from None


def is_since(value, since):
    if since is None:
        return True
    if not value:
        return False
    try:
        return parse_time(value) >= since
    except ValueError:
        return False


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")


def read_from(file, **more):
    """Where an answer's data was read: when it was last checked with its
    source, and why it couldn't be when it couldn't (then it's what was on
    disk)."""
    found = {"checkedAt": iso(file.checked_at), **more}
    if file.stale:
        found["stale"] = file.stale
    return found


def page_link(name):
    return f"{sources.PAGE}?pkg={name}"


# The tools.


def find_packages(ctx, query, limit=20):
    known, file = sources.names(ctx.cache)
    q = query.lower().strip()
    if not q:
        raise ToolError("query is empty")
    exact, prefix, inside = [], [], []
    for key, entry in known.items():
        if key == q or key == sources.package_key(q):
            exact.append(entry)
        elif key.startswith(q):
            prefix.append(entry)
        elif q in key:
            inside.append(entry)
    found = exact + sorted(prefix, key=lambda e: e[0]) + sorted(inside, key=len)
    return {
        "query": query,
        "matches": len(found),
        "packages": [
            {
                "name": e[0],
                "status": sources.status_text(e[1]),
                **({"set": e[2]} if len(e) > 2 else {}),
            }
            for e in found[:limit]
        ],
        "readFrom": {"dashboard": read_from(file)},
    }


# A row's Repology entries (every repository) can run to hundreds: shown
# are nixpkgs' own and those with the newest version, the rest counted.
REPOLOGY_SHOWN = 8


def _repology(entries):
    # nixpkgs' own: unstable's, and the newest release's (nix_stable_26_05).
    stable = max(
        (e["repo"] for e in entries if e.get("repo", "").startswith("nix_stable_")),
        default=None,
    )
    nixpkgs = [e for e in entries if e.get("repo") in ("nix_unstable", stable)]
    newest = [e for e in entries if e.get("status") == "newest" and e not in nixpkgs]
    return {
        "nixpkgs": nixpkgs,
        "newestElsewhere": newest[:REPOLOGY_SHOWN],
        "repositories": len({e.get("repo") for e in entries}),
    }


def _build_id(build):
    try:
        return int(build.get("build") or 0)
    except ValueError:
        return 0


def package(ctx, name, repology=False):
    cache = ctx.cache
    row, file = sources.row(cache, name)
    builds, builds_file = sources.builds(cache)
    attempts, attempts_file = sources.attempts(cache)
    if row is None:
        # Not a row of the dashboard's: maybe an attribute a row covers
        # (heroic-unwrapped, in heroic's), which the digests know by itself.
        found = {
            "name": name,
            "inDashboard": False,
            "builds": builds.of(name),
            "updateAttempt": attempts.get(name),
        }
        if not found["builds"] and not found["updateAttempt"]:
            near = find_packages(ctx, name, limit=8)["packages"]
            raise ToolError(
                f"no package {name!r} in nixkeeper's data"
                + (
                    "; did you mean: " + ", ".join(p["name"] for p in near)
                    if near
                    else ""
                )
            )
        found["note"] = (
            "Not a package of the dashboard's by this name (maybe an attribute "
            "another row covers): only what the builds and update-bot digests "
            "say of this attribute."
        )
        found["readFrom"] = {
            "builds": read_from(builds_file),
            "updates": read_from(attempts_file),
        }
        return found

    idx, idx_file = sources.index(cache)
    known, _ = sources.names(cache)
    letter = (known.get(row["name"].lower()) or [None, None])[1]
    shown = {k: v for k, v in row.items() if k not in ("dataFile", "repology")}
    shown["status"] = sources.status_text(letter)
    shown["page"] = page_link(row["name"])
    if row.get("repology"):
        if repology:
            shown["repology"] = row["repology"]
        else:
            shown["repology"] = _repology(row["repology"])
    for build in shown.get("builds") or []:
        if build.get("build"):
            build["url"] = sources.HYDRA_BUILD + str(build["build"])

    # What the digests have that's newer than the row (read hourly; the
    # dashboard syncs every 3 hours): a newer Hydra build, a newer attempt.
    known_builds = {
        (b.get("attr"), b.get("system")): _build_id(b) for b in row.get("builds") or []
    }
    newer_builds = [
        b
        for attr in row.get("attrs") or [row["name"]]
        for b in builds.of(attr)
        if _build_id(b) > known_builds.get((b.get("attr"), b.get("system")), 0)
    ]
    newer = {}
    if newer_builds:
        newer["builds"] = newer_builds
    tried = (row.get("update") or {}).get("attr") or row["name"]
    entry = attempts.get(tried)
    if entry:
        attempt = entry.get("attempt") or {}
        if attempt.get("date", "") > (row.get("update") or {}).get("date", ""):
            newer["updateAttempt"] = attempt
        if entry.get("pending"):
            newer["updatePending"] = entry["pending"]
    if newer:
        shown["newerInDigests"] = newer

    sync = idx.get("sources") or {}
    shown["readFrom"] = {
        "dashboard": read_from(file, syncedAt=idx.get("checkedAt")),
        "dashboardSources": {
            key: sync[key].get("at")
            for key in (
                "hydra",
                "updates",
                "queue",
                "prs",
                "tracker",
                "osv",
                "versions",
            )
            if key in sync
        },
        "builds": read_from(builds_file),
        "updates": read_from(attempts_file),
    }
    return shown


ATTENTION_KINDS = (
    "any",
    "failing",
    "updateFailing",
    "outdated",
    "waiting",
    "vulnerable",
    "backport",
    "broken",
    "stagingNext",
    "all",
)


def _reasons(entry, letter):
    """Why a summary entry needs attention (nixkeeper's verdicts)."""
    found = []
    failing = [
        b["system"] for b in entry.get("builds") or [] if b["status"] == "failed"
    ]
    if failing:
        found.append("failing")
    if entry.get("updateFailure"):
        found.append("updateFailing")
    if letter.startswith("m"):
        found.append("waiting")
    elif (
        letter.startswith("o")
        or entry.get("nixStatus") == "outdated"
        or (entry.get("upstream") or {}).get("newer")
    ):
        found.append("outdated")
    if letter.endswith("v") or (entry.get("vuln") or {}).get("n"):
        found.append("vulnerable")
    if entry.get("backport"):
        found.append("backport")
    if entry.get("markedBroken"):
        found.append("broken")
    if entry.get("stagingNextBreaks"):
        # A forecast, not attention now: its own kind, outside "any".
        found.append("stagingNext")
    return found, failing


def _needs_attention(entry, letter):
    """nixkeeper's views/attention.json: failing, outdated (waiting for the
    channel too), flagged vulnerable, or a fix to backport."""
    return (
        letter[:1] in ("f", "m", "o") or letter.endswith("v") or entry.get("backport")
    )


def _available(entry, platform):
    platforms = entry.get("platforms")
    return platforms is None or bool(platforms.get(platform))


ORDER = (
    "failing",
    "vulnerable",
    "backport",
    "updateFailing",
    "outdated",
    "waiting",
    "stagingNext",
)


def needs_attention(
    ctx, maintainer=None, team=None, list=None, kind="any", platform=None, limit=50
):
    cache = ctx.cache
    given = [a for a in (maintainer, team, list) if a]
    if len(given) > 1:
        raise ToolError("give one of maintainer, team or list")
    if maintainer:
        path = f"views/maintainer/{maintainer.lstrip('@').lower()}.json"
    elif team:
        path = f"views/team/{sources.view_slug(team)}.json"
    elif list:
        path = f"views/list/{sources.view_slug(list)}.json"
    else:
        path = "views/attention.json"
    try:
        entries, file = sources.view(cache, path)
    except NotFound:
        if maintainer:
            raise ToolError(
                f"no packages list {maintainer!r} as a maintainer (by GitHub handle)"
            ) from None
        if team:
            idx, _ = sources.index(cache)
            teams = sorted((idx.get("views") or {}).get("teams") or {})
            raise ToolError(f"no team {team!r}; teams: {', '.join(teams)}") from None
        raise ToolError(f"no list {list!r}") from None
    known, _ = sources.names(cache)
    found = []
    for entry in entries:
        letter = (known.get(entry["name"].lower()) or [None, ""])[1] or ""
        reasons, failing = _reasons(entry, letter)
        if kind == "any" and not _needs_attention(entry, letter):
            continue
        if kind not in ("any", "all") and kind not in reasons:
            continue
        if platform:
            if kind == "failing":
                if not any(s.endswith(platform) for s in failing):
                    continue
            elif not _available(entry, platform):
                continue
        item = {"name": entry["name"], "why": reasons}
        if failing:
            item["failingOn"] = failing
        for key in (
            "nixVersion",
            "refVersion",
            "master",
            "failingSince",
            "outdatedSince",
            "updateFailingSince",
            "vuln",
            "backport",
            "markedBroken",
            "markedInsecure",
            "set",
        ):
            if entry.get(key) not in (None, False, [], {}):
                item[key] = entry[key]
        update = entry.get("update") or {}
        if entry.get("updateFailure"):
            item["update"] = update
        for key in ("openPR", "masterPR", "dropPR"):
            if entry.get(key):
                item[key] = entry[key].get("url") or (
                    sources.PR_URL + str(entry[key]["number"])
                )
        if pr := entry.get("stagingPR"):
            # Merged into staging or staging-next, on its way to master.
            item["stagingPR"] = {
                "on": pr.get("on"),
                "to": pr.get("to"),
                "url": pr.get("url") or sources.PR_URL + str(pr.get("number")),
            }
        if breaks := entry.get("stagingNextBreaks"):
            item["breaksOnStagingNext"] = {
                "systems": sorted({b["system"] for b in breaks.get("builds") or []}),
                "evaluatedAt": breaks.get("evaluatedAt"),
            }
        found.append(item)

    def rank(item):
        worst = min((ORDER.index(w) for w in item["why"] if w in ORDER), default=99)
        return (worst, item["name"].lower())

    found.sort(key=rank)
    counts = {}
    for item in found:
        for why in item["why"]:
            counts[why] = counts.get(why, 0) + 1
    return {
        "view": path,
        "matches": len(found),
        "counts": counts,
        "packages": found[:limit],
        "readFrom": {"dashboard": read_from(file)},
        "note": "Each package's full state: the package tool.",
    }


def overview(ctx):
    idx, file = sources.index(ctx.cache)
    causes = idx.get("causes") or {}
    return {
        "syncedAt": idx.get("checkedAt"),
        "nixkeeperVersion": idx.get("version"),
        "packages": idx.get("packageCount"),
        "counts": idx.get("counts"),
        "highlights": idx.get("highlights"),
        "blockers": {
            **{k: v for k, v in (idx.get("blockers") or {}).items() if k != "top"},
            "top": [
                {"name": t[0], "packages": t[2], "builds": t[3]}
                for t in (idx.get("blockers") or {}).get("top") or []
            ],
        },
        "buildFailureCauses": [
            {k: g.get(k) for k in ("title", "about", "reason", "count", "line")}
            for g in causes.get("builds") or []
        ],
        "updateBotFailureCauses": causes.get("bot"),
        "fixed": idx.get("fixed"),
        "sources": {k: v.get("at") for k, v in (idx.get("sources") or {}).items()},
        "readFrom": {"dashboard": read_from(file)},
    }


BUILD_STATUSES = ("failed", "dependency", "unfinished", "queued", "notOk")
SYSTEMS = ("x86_64-linux", "aarch64-linux", "aarch64-darwin")


def _matches_package(attr, package):
    a, p = attr.lower(), sources.package_key(package)
    return a == p or a.startswith(p + ".") or a == package.lower()


def build_failures(
    ctx,
    package=None,
    search=None,
    system=None,
    status="failed",
    reason=None,
    blocked_by=None,
    since=None,
    sort="newest",
    limit=50,
):
    builds, file = sources.builds(ctx.cache)
    meta, _ = sources.meta(ctx.cache, "builds")
    since = since_time(since, ctx.now()) if since else None
    found = []
    for b in builds.not_ok:
        if status != "notOk" and b.get("status") != status:
            continue
        if package and not _matches_package(b["attr"], package):
            continue
        if search and search.lower() not in b["attr"].lower():
            continue
        if system and b.get("system") != system:
            continue
        if reason and b.get("failedBecause") != reason:
            continue
        if blocked_by and not any(
            blocked_by.lower() == x.lower() for x in b.get("blockedBy") or []
        ):
            continue
        if not is_since(b.get("finished"), since):
            continue
        found.append(b)
    if sort == "longestFailing":
        # Never succeeded first, then by the last success, oldest first.
        found.sort(
            key=lambda b: (
                b.get("lastSuccessAt") != "never",
                b.get("lastSuccessAt") or "9",
            )
        )
    else:
        found.sort(key=lambda b: b.get("finished") or "", reverse=True)
    return {
        "matches": len(found),
        "builds": found[:limit],
        "evaluation": {
            "eval": meta.get("eval"),
            "revision": meta.get("revision"),
            "readByDigestAt": meta.get("fetchedAt"),
        },
        "readFrom": {"builds": read_from(file)},
    }


MERGE_BOT = ("ready", "eligible")
PR_STATES = ("superseded", "overtaken", "downgrade", "snapshotToRelease", "preRelease")


def pull_requests(
    ctx,
    package=None,
    search=None,
    author=None,
    bucket=None,
    base=None,
    merge_bot=None,
    state=None,
    blocks_bot=False,
    drafts=True,
    sort="updated",
    limit=30,
):
    data, file = sources.prs(ctx.cache)
    key = sources.package_key(package) if package else None
    found = []
    for pr in data["prs"]:
        if key and key not in pr["_keys"]:
            continue
        if search and search.lower() not in pr.get("title", "").lower():
            continue
        if author and pr.get("author", "").lower() != author.lstrip("@").lower():
            continue
        if bucket and bucket not in pr.get("buckets", []):
            continue
        if base and pr.get("base") != base:
            continue
        if not drafts and pr.get("draft"):
            continue
        mb = pr.get("mergeBot") or {}
        if merge_bot == "eligible" and not mb:
            continue
        if merge_bot == "ready" and not mb.get("ready"):
            continue
        if state and pr.get("state") != state:
            continue
        if blocks_bot and not pr.get("blocksBot"):
            continue
        found.append({k: v for k, v in pr.items() if k != "_keys"})
    found.sort(key=lambda pr: pr.get(sort) or "", reverse=True)
    return {
        "matches": len(found),
        "prs": found[:limit],
        "readFrom": {"prs": read_from(file, generatedAt=data.get("generatedAt"))},
    }


def _words(text):
    return set(re.findall(r"[a-z0-9_]+", (text or "").lower()))


def issues(ctx, package=None, search=None, kind=None, verdict=None, limit=30):
    data, file = sources.issues(ctx.cache)
    key = sources.package_key(package) if package else None
    found = []
    for issue in data["issues"]:
        hydra, update = issue.get("hydra"), issue.get("update")
        if kind == "build" and not hydra:
            continue
        if kind == "update" and not update:
            continue
        if verdict and verdict not in (
            (hydra or {}).get("verdict"),
            (update or {}).get("verdict"),
        ):
            continue
        if key:
            named = {
                sources.package_key(x)
                for x in (
                    (hydra or {}).get("package"),
                    (hydra or {}).get("checkedAs"),
                    (update or {}).get("package"),
                )
                if x
            }
            # Else by the words of its title, as nixkeeper counts a
            # package's issues: every word of the package's name.
            if key not in named and not _words(package) <= _words(issue["title"]):
                continue
        if search and search.lower() not in issue["title"].lower():
            continue
        found.append({**issue, "url": sources.ISSUE_URL + str(issue["n"])})
    found.sort(key=lambda i: i["n"], reverse=True)
    return {
        "matches": len(found),
        "issues": found[:limit],
        "readFrom": {"prs": read_from(file, generatedAt=data.get("generatedAt"))},
    }


UPDATE_OUTCOMES = (
    "prOpened",
    "prExists",
    "branchExists",
    "noChange",
    "cantUpdate",
    "skipped",
    "failed",
    "other",
)


def _queued(queue, attr):
    entry = (queue.get("queue") or {}).get(attr)
    if not entry:
        return None
    found = {"position": entry.get("position"), "candidates": entry.get("candidates")}
    if entry.get("script"):
        found["script"] = True
    try:
        share = entry["position"] / queue["positions"]
        by = parse_time(queue["updatedAt"]) + timedelta(days=share * queue["cycleDays"])
        found["expectedBy"] = by.date().isoformat()
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    return found


def update_attempts(
    ctx, package=None, search=None, outcome=None, reason=None, since=None, limit=30
):
    attempts, file = sources.attempts(ctx.cache)
    queue, queue_file = sources.queue(ctx.cache)
    read = {
        "updates": read_from(file),
        "queue": read_from(queue_file, updatedAt=queue.get("updatedAt")),
    }
    if package:
        entry = attempts.get(package)
        if entry is None:
            lower = {sources.package_key(k): k for k in attempts}
            entry = attempts.get(lower.get(sources.package_key(package), ""))
        if entry is None:
            raise ToolError(f"the update bot has no attempt at {package!r}")
        return {
            **entry,
            "queued": _queued(queue, entry["attr"]),
            "readFrom": read,
        }
    since = since_time(since, ctx.now()) if since else None
    found = []
    for entry in attempts.entries():
        attempt = entry.get("attempt") or {}
        if search and search.lower() not in entry["attr"].lower():
            continue
        if outcome and attempt.get("outcome") != outcome:
            continue
        if reason and attempt.get("failedBecause") != reason:
            continue
        if not is_since(attempt.get("date"), since):
            continue
        found.append(entry)
    found.sort(key=lambda e: (e.get("attempt") or {}).get("started") or 0, reverse=True)
    return {"matches": len(found), "attempts": found[:limit], "readFrom": read}


SEVERITIES = ("critical", "high", "moderate", "medium", "low")


def _suggestion(data, sid):
    tracker = data["tracker"]
    found = dict(tracker["suggestions"].get(sid) or {})
    found["id"] = sid
    issue = found.get("issue")
    if issue and issue in tracker["issues"]:
        found["issueStatus"] = tracker["issues"][issue].get("status")
        found["github"] = tracker["issues"][issue].get("github")
    return found


def vulnerabilities(ctx, package=None, cve=None, severity=None, limit=30):
    data, file = sources.vulnerabilities(ctx.cache)
    tracker, osv = data["tracker"], data["osv"]
    read = {"vulnerabilities": read_from(file)}
    note = (
        "As the NixOS security tracker last evaluated each package, and OSV's "
        "advisories matching nixpkgs' version. nixkeeper's verdict against "
        "nixpkgs' version now (fixed, patched, to backport): the package tool."
    )
    if package:
        attr = package
        if attr not in tracker["packages"] and attr not in osv["packages"]:
            lower = {
                sources.package_key(k): k
                for k in [*tracker["packages"], *osv["packages"]]
            }
            attr = lower.get(sources.package_key(package), package)
        found = []
        for s in tracker["packages"].get(attr, []):
            suggestion = _suggestion(data, s["suggestion"])
            # This package's status (on every branch), not the others'.
            mine = (suggestion.pop("packages", None) or {}).get(attr) or s
            found.append({**suggestion, "status": mine})
        if severity:
            found = [s for s in found if s.get("severity") == severity]
        advisories = [
            {"id": a, **osv["advisories"].get(a, {})}
            for a in osv["packages"].get(attr, [])
        ]
        return {
            "package": attr,
            "tracker": found[:limit],
            "osv": advisories[:limit],
            "note": note,
            "readFrom": read,
        }
    if cve:
        want = cve.upper()
        found = [
            _suggestion(data, sid)
            for sid, s in tracker["suggestions"].items()
            if (s.get("cve") or "").upper() == want
            or (s.get("issue") or "").upper() == want
        ]
        advisories = [
            {"id": aid, **a}
            for aid, a in osv["advisories"].items()
            if aid.upper() == want
            or want in (x.upper() for x in [*a.get("cves", []), *a.get("aliases", [])])
        ]
        return {
            "cve": cve,
            "tracker": found[:limit],
            "osv": advisories[:limit],
            "note": note,
            "readFrom": read,
        }
    # Neither: the tracker's CVEs affecting some package now, worst first.
    found = []
    for sid, s in tracker["suggestions"].items():
        if severity and s.get("severity") != severity:
            continue
        affected = [
            name
            for name, p in (s.get("packages") or {}).items()
            if p.get("status") == "affected"
        ]
        if affected:
            found.append({**_suggestion(data, sid), "affectedPackages": affected})
    found.sort(key=lambda s: s.get("score") or 0, reverse=True)
    for s in found:
        s.pop("packages", None)  # the names are in affectedPackages
    return {
        "matches": len(found),
        "tracker": found[:limit],
        "note": note,
        "readFrom": read,
    }


def data_status(ctx):
    cache = ctx.cache
    found = {}
    try:
        idx, file = sources.index(cache)
        found["dashboard"] = {
            "syncedAt": idx.get("checkedAt"),
            "nixkeeperVersion": idx.get("version"),
            "sources": {k: v.get("at") for k, v in (idx.get("sources") or {}).items()},
            **read_from(file),
        }
    except Exception as e:  # each source on its own: one down says so
        found["dashboard"] = {"error": str(e)}
    for name in sources.METAS:
        try:
            meta, file = sources.meta(cache, name)
            found[name] = {"meta": meta, **read_from(file)}
        except Exception as e:
            found[name] = {"error": str(e)}
    files = cache.files()
    found["cache"] = {
        "directory": cache.directory,
        "ttlMinutes": cache.ttl / 60,
        "offline": cache.offline,
        "files": len(files),
        "bytes": sum(size for _, size, _ in files),
    }
    return found


# The tools' descriptions and arguments, as listed to the assistant.


def _s(description, **more):
    return {"type": "string", "description": description, **more}


def _limit(default):
    return {
        "type": "integer",
        "description": f"At most this many results (default {default}).",
        "minimum": 1,
        "maximum": 500,
    }


def _since():
    return _s('Only since then: "24h", "7d", "2w", or a day or time (ISO 8601).')


TOOLS = [
    {
        "name": "package",
        "title": "A package's state",
        "description": (
            "Everything nixkeeper knows about one nixpkgs package: its nixpkgs "
            "version against upstream's (Repology, nixkeeper's own update "
            "checks), master's version, Hydra's latest builds on each platform "
            "with why a failure failed and when it last built, the update "
            "bot's (nixpkgs-update, r-ryantm) latest attempt and when it tries "
            "next, open update PRs and other PRs and issues, CVEs and "
            "advisories with nixkeeper's verdict against nixpkgs' version, "
            "maintainers and teams; an update merged into staging or "
            "staging-next on its way to master (stagingPR, and how it builds "
            "there), and whether staging-next breaks the package "
            "(stagingNextBreaks: a forecast). newerInDigests: what the "
            "hourly digests have that's newer than the dashboard's last sync."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": _s(
                    "Its attribute (wesnoth, python313Packages.requests); "
                    "python3Packages works too."
                ),
                "repology": {
                    "type": "boolean",
                    "description": "Every repository's version from Repology, "
                    "not only nixpkgs' and the newest.",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "run": package,
    },
    {
        "name": "find_packages",
        "title": "Find packages",
        "description": (
            "Find nixpkgs packages by name (exact, then starting with, then "
            "containing the query), each with its status: failed, outdated, "
            "up to date, vulnerable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": _s("Part of a name."), "limit": _limit(20)},
            "required": ["query"],
            "additionalProperties": False,
        },
        "run": find_packages,
    },
    {
        "name": "needs_attention",
        "title": "Packages needing attention",
        "description": (
            "Packages that need attention, as nixkeeper's dashboard counts "
            "them: a build failing on Hydra, outdated, vulnerable, or a CVE "
            "fix to backport; optionally only one maintainer's (GitHub "
            "handle), one team's or one list's, one kind, one platform. "
            "Without maintainer, team or list: all of nixpkgs (thousands: "
            "narrow with kind)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "maintainer": _s("A maintainer's GitHub handle."),
                "team": _s("A nixpkgs team (Gaming, Qt-KDE, ...)."),
                "list": _s("One of the dashboard's lists."),
                "kind": _s(
                    "any (default): what the dashboard says needs attention; "
                    "failing (a build of its own fails), updateFailing (the "
                    "update bot fails), outdated, waiting (updated on master, "
                    "waiting for the channel), vulnerable, backport, broken; "
                    "stagingNext: builds on master but fails its own build on "
                    "staging-next (a forecast: it fails on master when "
                    "staging-next is merged, unless fixed; not in any); "
                    "all: every package of the maintainer/team/list.",
                    enum=list(ATTENTION_KINDS),
                ),
                "platform": _s(
                    "linux or darwin: available there (for failing: failing there).",
                    enum=["linux", "darwin"],
                ),
                "limit": _limit(50),
            },
            "additionalProperties": False,
        },
        "run": needs_attention,
    },
    {
        "name": "overview",
        "title": "nixpkgs overview",
        "description": (
            "All of nixpkgs at a glance, from nixkeeper's dashboard: how many "
            "packages are outdated, failing to build, failing their update "
            "attempts, vulnerable, broken; the newest and longest-standing of "
            "each; the failing dependencies blocking the most builds; why "
            "builds and the update bot fail, grouped; what was fixed in the "
            "last week."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False},
        "run": overview,
    },
    {
        "name": "build_failures",
        "title": "Hydra build failures",
        "description": (
            "Search Hydra's builds of nixpkgs master (the builds digest, "
            "hourly) that aren't ok: failed (the package's own failure, with "
            "why from its log and an excerpt), dependency (blockedBy: which "
            "dependency failed), unfinished, queued. Newest first, or longest "
            "failing first. With the last success of each."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": _s(
                    "An attribute, or a set's prefix (python313Packages): its "
                    "builds and its members'."
                ),
                "search": _s("Part of an attribute."),
                "system": _s("A Hydra system.", enum=list(SYSTEMS)),
                "status": _s(
                    "failed (default), dependency, unfinished, queued, or "
                    "notOk for all of them.",
                    enum=list(BUILD_STATUSES),
                ),
                "reason": _s(
                    "Why a failed build failed: compile, tests, link, header, "
                    "cmake4, cmake, boost, pythonImport, pythonDeps, "
                    "pythonBuild, pythonMetadata, haskellDeps, npm, lisp, home, "
                    "download, hash, patch, substitute, missingFile, symlinks, "
                    "patchelf, autotools, disk, other, noLog."
                ),
                "blocked_by": _s(
                    "Dependency failures blocked by this attribute (status dependency)."
                ),
                "since": _since(),
                "sort": _s(
                    "newest (default: finished most recently) or "
                    "longestFailing (never succeeded, then oldest last "
                    "success).",
                    enum=["newest", "longestFailing"],
                ),
                "limit": _limit(50),
            },
            "additionalProperties": False,
        },
        "run": build_failures,
    },
    {
        "name": "pull_requests",
        "title": "Open nixpkgs PRs",
        "description": (
            "Search nixpkgs' open pull requests (the PR digest, hourly), with "
            "what the digest makes of each: its buckets (update, init, drop, "
            "tiny, bot, python, ...), the update it makes and how it compares "
            "with nixpkgs now (state), whether a maintainer can merge it with "
            "the merge bot, whether it blocks the update bot, duplicates, and "
            "packages it touches that fail on Hydra (maybe its fix)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": _s(
                    'PRs touching it: by its title ("foo: 1.0 -> 1.1"), '
                    "its update, or its pkgs/by-name directory."
                ),
                "search": _s("Part of the title."),
                "author": _s("The author's GitHub login."),
                "bucket": _s(
                    "update, init, drop, by-name, tiny, bot, ci-bot, python, "
                    "haskell, node, nixos, lib, ci, docs, treewide, "
                    "version-only, cve."
                ),
                "base": _s("The branch it targets (master, staging, ...)."),
                "merge_bot": _s(
                    "eligible: a maintainer can merge it with the merge bot; "
                    "ready: and its CI is green.",
                    enum=list(MERGE_BOT),
                ),
                "state": _s(
                    "superseded (nixpkgs already has it: close it), overtaken, "
                    "downgrade, snapshotToRelease, preRelease.",
                    enum=list(PR_STATES),
                ),
                "blocks_bot": {
                    "type": "boolean",
                    "description": "Only those stopping the update bot's next update.",
                },
                "drafts": {
                    "type": "boolean",
                    "description": "Include drafts (default true).",
                },
                "sort": _s(
                    "updated (default) or created, newest first.",
                    enum=["updated", "created"],
                ),
                "limit": _limit(30),
            },
            "additionalProperties": False,
        },
        "run": pull_requests,
    },
    {
        "name": "issues",
        "title": "Open nixpkgs issues",
        "description": (
            "Search nixpkgs' open issues by title (the PR digest, hourly). "
            "Build-failure issues have hydra: what Hydra builds now say "
            "(builds: a candidate to close; failing; waiting; removed; ...); "
            "update requests have update: whether nixpkgs has the version "
            "asked (done, partly, open) and the update bot's plans."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": _s(
                    "Issues about it: the package a build failure or update "
                    "request names, or every word of its name in the title."
                ),
                "search": _s("Part of the title."),
                "kind": _s(
                    "build (build failures) or update (update requests).",
                    enum=["build", "update"],
                ),
                "verdict": _s(
                    "The digest's verdict: builds, failing, waiting, variant, "
                    "noJob, platformNotBuilt, removed, renamed, unfree, "
                    "markedBroken, notForHydra (build); done, partly, open, "
                    "notFound, notVersion (update)."
                ),
                "limit": _limit(30),
            },
            "additionalProperties": False,
        },
        "run": issues,
    },
    {
        "name": "update_attempts",
        "title": "Update bot attempts",
        "description": (
            "nixpkgs-update's (r-ryantm) latest attempt at packages (the "
            "update-bot digest, every 3 hours): its outcome, versions, PR, "
            "why it failed with a log excerpt; for one package, also its "
            "place in the bot's queue and when it's expected to try again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": _s("One attribute, as the bot names it."),
                "search": _s("Part of an attribute."),
                "outcome": _s(
                    "prOpened, prExists, branchExists, noChange, cantUpdate, "
                    "skipped, failed, other.",
                    enum=list(UPDATE_OUTCOMES),
                ),
                "reason": _s(
                    "Why a failed attempt failed: bot, unavailable, patch, "
                    "dependency, hash, source, updateScript, tests, noLog, "
                    "build, request, other."
                ),
                "since": _since(),
                "limit": _limit(30),
            },
            "additionalProperties": False,
        },
        "run": update_attempts,
    },
    {
        "name": "vulnerabilities",
        "title": "Vulnerabilities",
        "description": (
            "CVEs from the NixOS security tracker (with its issue, severity, "
            "affected versions, status on master and the release branches) "
            "and OSV advisories for language packages (the vulnerabilities "
            "digest, hourly): one package's, one CVE's (or NIXPKGS-..., or an "
            "advisory id), or else the CVEs affecting some package now, worst "
            "first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": _s("An attribute."),
                "cve": _s("CVE-..., NIXPKGS-..., GHSA-..., PYSEC-..."),
                "severity": _s(
                    "critical, high, moderate/medium, low.", enum=list(SEVERITIES)
                ),
                "limit": _limit(30),
            },
            "additionalProperties": False,
        },
        "run": vulnerabilities,
    },
    {
        "name": "data_status",
        "title": "Data freshness",
        "description": (
            "When each digest and the dashboard were last made and read "
            "(their meta.json files), and what this server has cached."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False},
        "run": data_status,
    },
]

BY_NAME = {tool["name"]: tool for tool in TOOLS}


# Every tool only reads public data from outside (the dashboard, the
# digests), and changes nothing: a client may run them without asking.
ANNOTATIONS = {"readOnlyHint": True, "openWorldHint": True}


def listed():
    """The tools as tools/list gives them."""
    return [
        {**{k: v for k, v in t.items() if k != "run"}, "annotations": ANNOTATIONS}
        for t in TOOLS
    ]


def call(ctx, name, args):
    """Run a tool: its answer (JSON-able), or ToolError."""
    tool = BY_NAME[name]
    check_arguments(tool["inputSchema"], args or {})
    return tool["run"](ctx, **(args or {}))
