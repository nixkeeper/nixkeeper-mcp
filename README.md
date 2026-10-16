# nixkeeper-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant
answer questions about nixpkgs packages from
[nixkeeper](https://github.com/nixkeeper/nixkeeper)'s data: is a package
outdated, does it build on Hydra, what did the update bot make of it, which
PRs and issues touch it, which CVEs affect it, and what needs attention for
a maintainer or a team. It runs on your computer over stdio, downloads only
public files, and needs no account or token.

## Using it

With Claude Code:

```bash
claude mcp add --scope user nixkeeper -- nix run github:nixkeeper/nixkeeper-mcp
```

Then ask: "what's wrong with wesnoth?", "which of iedame's packages need
attention?", "what broke on Darwin in the last day?", "which open PRs
could the merge bot merge for the Gaming team's packages?", "which of my
packages break when staging-next is merged?"

Any MCP client that starts a server on stdio works the same way, with the
command `nix run github:nixkeeper/nixkeeper-mcp` (or `nixkeeper-mcp`, from
the flake's `packages.default`). Without Nix: `python3 -m nixkeeper_mcp`
in a checkout (Python 3.11 or later, standard library only).

## The tools

| Tool | Answers | From |
|---|---|---|
| `package` | Everything about one package: nixpkgs' version against upstream's, master's, Hydra's builds on each platform (why a failure failed, when it last built), the update bot's latest attempt and when it tries next, its update PR and other PRs and issues, CVEs with nixkeeper's verdict against nixpkgs' version, maintainers and teams; an update merged into staging or staging-next on its way to master, and whether staging-next breaks the package; and what the hourly digests have that's newer than the dashboard's last sync | the dashboard's row, the builds and update-bot digests |
| `find_packages` | Packages by name, with their status | the dashboard |
| `needs_attention` | What needs attention (failing, outdated, vulnerable, a fix to backport), all of nixpkgs or one maintainer's, team's or list's, by kind and platform, worst first; or what breaks on staging-next (a forecast, its own kind) | the dashboard's views |
| `overview` | All of nixpkgs: counts and trends' latest, the newest and longest-standing failures, the dependencies blocking the most builds, why builds and the bot fail, what was fixed this week | the dashboard |
| `build_failures` | Hydra builds of master that aren't ok: by package or set, system, reason, the dependency that blocked them, since when; newest or longest failing first | digest-builds |
| `pull_requests` | Open nixpkgs PRs: touching a package, by author, bucket, base branch; ready for the merge bot, blocking the update bot, superseded | digest-prs |
| `issues` | Open nixpkgs issues about a package; build failures that build now, update requests already done | digest-prs |
| `update_attempts` | The update bot's latest attempts: one package's with its place in the queue, or by outcome, reason, since when | digest-update-bot |
| `vulnerabilities` | One package's CVEs and advisories, one CVE's packages, or the worst affecting something now | digest-vulnerabilities |
| `data_status` | When each source was last made and read, and what's cached | every `meta.json` |

Every answer says when its data was read (`readFrom`, times in UTC), and
says so when a source couldn't be reached and the answer comes from what
was cached. nixkeeper's checks (an issue that looks done, a PR ready for the
merge bot, an attempt that looks superseded, a package staging-next will
break) are hints for a person to check, not decisions: the server only
reads, and never comments on, closes or merges anything. Its tools say so
to the client (`readOnlyHint`), which may then run them without asking.

## Where the data comes from

- **[nixkeeper.com](https://nixkeeper.com/)'s data** (`/data/`, the
  community dashboard: every nixpkgs package, synced every 3 hours): each
  package's row, with everything nixkeeper joined from the digests and its
  verdicts (outdated, failing, vulnerable, to backport), so a package's
  state reads as the page shows it. Its format:
  [nixkeeper's docs/data.md](https://github.com/nixkeeper/nixkeeper/blob/main/docs/data.md).
- **The digests** (the `data` branch of each repository, each README
  saying its format), fresher and searchable across nixpkgs:
  [digest-builds](https://github.com/nixkeeper/digest-builds) (Hydra,
  hourly), [digest-prs](https://github.com/nixkeeper/digest-prs) (open PRs
  and issues, hourly),
  [digest-update-bot](https://github.com/nixkeeper/digest-update-bot)
  (nixpkgs-update, every 3 hours),
  [digest-vulnerabilities](https://github.com/nixkeeper/digest-vulnerabilities)
  (the NixOS security tracker and OSV, hourly), and
  [digest-versions](https://github.com/nixkeeper/digest-versions)' metadata
  (Repology's versions are in the dashboard's rows).

A file is downloaded the first time a tool needs it, so a question about one
package fetches that package's shard of the dashboard (about 90 KB) and the
two digests it's compared with, not all of nixpkgs. Files are kept in
`$XDG_CACHE_HOME/nixkeeper-mcp` (`~/.cache/nixkeeper-mcp` by default; about
35 MB with every source) and used for 15 minutes; after that, the server
asks whether a file changed (its ETag: an unchanged file isn't downloaded
again). If a source can't be reached, the cached file is used and the
answer says so. Parsed files stay in memory while the server runs: up to
about 400 MB with every source loaded at once (Hydra's 217,000 builds are
kept as text and searched, not parsed: parsed, they alone would take that
much). Every request names this repository in its
User-Agent.

## Options

```text
nixkeeper-mcp [--cache-dir DIR] [--ttl MINUTES] [--offline] [--call TOOL [JSON]]
```

- `--cache-dir` (or `NIXKEEPER_MCP_CACHE`): where files are kept.
- `--ttl`: minutes a file is used before asking whether it changed
  (default 15).
- `--offline`: never download; answer from the cache.
- `--call TOOL '{"name": "wesnoth"}'`: run one tool and print its answer,
  to try them without an assistant.

`NIXKEEPER_MCP_DASHBOARD` (default `https://nixkeeper.com/data/`) and
`NIXKEEPER_MCP_DIGEST_OWNER` (default `nixkeeper`) point it at another
instance's data, a fork's; the answers link to the page beside the
dashboard's data (`https://nixkeeper.com/`), or `NIXKEEPER_MCP_PAGE`.

With Claude Code, options go after the command:
`claude mcp add nixkeeper -- nix run github:nixkeeper/nixkeeper-mcp -- --ttl 60`.

## The protocol

The server speaks MCP over stdio, both its current revision (2026-07-28:
no handshake, each request carrying its version in `_meta`, and
`server/discover`) and the earlier ones (2025-11-25 back to 2024-11-05,
with `initialize`), whichever the client opens with. Tools only: no
resources or prompts. It's written with the standard library alone
(`nixkeeper_mcp/protocol.py`), like the digests, so it runs with any
Python 3.11 or later and has nothing to install.

## Development

`nix flake check` runs the tests (which never ask the real sources), lint
and the formatting check; `nix fmt` formats; `nix develop` has the tools.

## AI & automation disclosure

This server's code and documentation are written with the assistance of an
AI (Claude, by Anthropic), with a person in the loop: nixkeeper's maintainer
decides what to build, and reviews and tests every change before it's
merged. It reads public data only, and never comments on, closes or merges
anything in nixpkgs.

## License

MIT
