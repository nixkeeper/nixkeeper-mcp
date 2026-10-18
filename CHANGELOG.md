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

[Unreleased]: https://github.com/nixkeeper/nixkeeper-mcp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nixkeeper/nixkeeper-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/nixkeeper/nixkeeper-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nixkeeper/nixkeeper-mcp/releases/tag/v0.1.0
