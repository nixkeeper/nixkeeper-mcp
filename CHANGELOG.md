# Changelog

Notable changes to nixkeeper-mcp. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a minor bump means new
features).

The version lives in `pyproject.toml` (and `nixkeeper_mcp/__init__.py`, which
the tests check against it); `flake.nix` reads it from there. Pushing a tag
`vX.Y.Z` publishes a GitHub Release with that version's section below as its
notes (`.github/workflows/release.yml`).

## [Unreleased]

## [0.4.1] - 2026-10-23

### Fixed

- As nixkeeper 0.22.0 counts them:
  - `issues` with a package: the issues with its name whole in their
    title, besides those the digest says are about it, not every title
    with its name's words ("pkg": 8 issues, not 27 with "pkgs/..." and
    "pkg-config" in them; "go": 21, not 39).
  - `package`: an older version kept on purpose beside a newer one says so
    ("older version kept beside firefox 158.0.1"), rather than "can't be
    compared". The dashboard's own fixes (firefox-esr's `esr` suffix,
    thunderbird-153 behind in its own series, PR and issue counts about the
    package, `searchShowsMore`) come through as they are.

## [0.4.0] - 2026-10-19

### Added

- What nixkeeper 0.20.0 added, for an assistant too:
  - `package`: `notBuiltWhereListed`, the platforms nixpkgs lists the
    package for but Hydra doesn't build it on (the page's struck platform
    tags); the row it returns already has its update PR's `behind` and
    `vulnerable`, the CVE issue checks (`cveFixed`: a candidate to close)
    and the bot's expected day (`queued.by`).
  - `needs_attention`: each package's `notBuiltWhereListed` and
    `botExpectedBy`; and in `canMerge`, each PR's `behind` and `vulnerable`
    (from the dashboard's merge list), those for a vulnerable package right
    after the maintainer's own, as on the page.
  - `overview`: `numbers` (Hydra's builds by kind, update PRs behind
    upstream, packages without a maintainer), `mergeBot` (the PRs waiting
    for their own maintainers) and `notBuiltWhereListed` (how many), the
    page's "nixpkgs in numbers".

## [0.3.0] - 2026-10-18

### Added

- "Which PRs can I merge?": `needs_attention` with a maintainer or a team
  adds `canMerge`, the open PRs they can merge now with nixpkgs' merge bot
  (ready, not a draft, no conflict, no changes requested, and they maintain
  every package it touches; a maintainer's own first, then the longest
  waiting; for a team, the packages nixpkgs lists under it, not those a
  list of its name adds), with the comment to post. `pull_requests` takes
  `can_merge` (a handle) for all of them. As nixkeeper's "You can merge
  these". The merge bot also asks for @NixOS/nixpkgs-maintainers, which
  isn't public: the answers say so.
- `pull_requests` passes on `noPRFailures`, nixpkgs CI's own verdict (the
  `no PR failures` status) the merge bot goes by, beside `ci`, every
  check's state (which ofborg's queued checks keep pending).

## [0.2.0] - 2026-10-18

### Added

- A Home Manager module (`homeModules.default`, also
  `homeManagerModules.default`): `programs.nixkeeper-mcp.enable = true;`
  adds the server to Home Manager's shared MCP servers
  (`programs.mcp.servers`), which Claude Code, GitHub Copilot CLI and other
  assistants Home Manager configures read with their
  `enableMcpIntegration`. Options for the server's: `ttl`, `offline`,
  `cacheDir`, `dashboard`, `digestOwner`, `page`; and `name`, `package`.
- This changelog, and releases published from a version tag.

### Changed

- The README installs it once (`nix profile install`, or the Home Manager
  module) instead of `nix run` on every start: `nix run` fetches the flake
  each time, and its first start, a download and a build, can take longer
  than an assistant waits for a server (30 seconds in Claude Code). `nix
  run` stays as the way to try it.

## [0.1.0] - 2026-10-16

### Added

- The MCP server on stdio, for the protocol's current revision
  (2026-07-28: no handshake, `server/discover`) and the earlier ones
  (2025-11-25 back to 2024-11-05, with `initialize`), with the standard
  library alone.
- The tools: `package`, `find_packages`, `needs_attention`, `overview`,
  `build_failures`, `pull_requests`, `issues`, `update_attempts`,
  `vulnerabilities` and `data_status`, from nixkeeper's dashboard data and
  its digests (builds, versions, update bot, vulnerabilities, PRs).
- A disk cache with ETags (`--ttl`, `--cache-dir`, `--offline`), and
  `--call` to run one tool by hand; another instance's data with
  `NIXKEEPER_MCP_DASHBOARD`, `NIXKEEPER_MCP_DIGEST_OWNER` and
  `NIXKEEPER_MCP_PAGE`.

[Unreleased]: https://github.com/nixkeeper/nixkeeper-mcp/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/nixkeeper/nixkeeper-mcp/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/nixkeeper/nixkeeper-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/nixkeeper/nixkeeper-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/nixkeeper/nixkeeper-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nixkeeper/nixkeeper-mcp/releases/tag/v0.1.0
