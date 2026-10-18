# Home Manager: `programs.nixkeeper-mcp.enable = true;` adds the server to
# Home Manager's shared MCP servers (programs.mcp.servers), which the
# assistants it configures read when their enableMcpIntegration is on
# (programs.claude-code, programs.github-copilot-cli, ...). The server is
# then the one the flake lock pins: nothing downloaded or built when an
# assistant starts it.
self:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.nixkeeper-mcp;
  inherit (lib) mkOption types;
  optionalString =
    description:
    mkOption {
      type = types.nullOr types.str;
      default = null;
      inherit description;
    };
in
{
  options.programs.nixkeeper-mcp = {
    enable = lib.mkEnableOption "nixkeeper-mcp, the MCP server answering questions about nixpkgs packages from nixkeeper's data, in Home Manager's shared MCP servers (programs.mcp.servers)";

    package = mkOption {
      type = types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      defaultText = lib.literalExpression "nixkeeper-mcp.packages.\${system}.default";
      description = "The nixkeeper-mcp package.";
    };

    name = mkOption {
      type = types.str;
      default = "nixkeeper";
      description = "The server's name in programs.mcp.servers: assistants name its tools after it.";
    };

    ttl = mkOption {
      type = types.nullOr types.ints.positive;
      default = null;
      example = 60;
      description = "Minutes a downloaded file is used before asking whether it changed (`--ttl`; the server's default, 15, when null).";
    };

    offline = mkOption {
      type = types.bool;
      default = false;
      description = "Never download: answer from what's cached (`--offline`).";
    };

    cacheDir = optionalString "Where downloaded files are kept (`--cache-dir`; the server's default, $XDG_CACHE_HOME/nixkeeper-mcp, when null).";

    dashboard = optionalString "Another instance's dashboard data, a fork's (NIXKEEPER_MCP_DASHBOARD; https://nixkeeper.com/data/ when null).";

    digestOwner = optionalString "The GitHub owner of the digests to read (NIXKEEPER_MCP_DIGEST_OWNER; nixkeeper when null).";

    page = optionalString "The page the answers link to (NIXKEEPER_MCP_PAGE; the one beside the dashboard's data when null).";
  };

  config = lib.mkIf cfg.enable {
    programs.mcp = {
      enable = lib.mkDefault true;
      servers.${cfg.name} = {
        command = lib.getExe cfg.package;
        args =
          lib.optionals (cfg.ttl != null) [
            "--ttl"
            (toString cfg.ttl)
          ]
          ++ lib.optional cfg.offline "--offline"
          ++ lib.optionals (cfg.cacheDir != null) [
            "--cache-dir"
            cfg.cacheDir
          ];
        env = lib.filterAttrs (_: value: value != null) {
          NIXKEEPER_MCP_DASHBOARD = cfg.dashboard;
          NIXKEEPER_MCP_DIGEST_OWNER = cfg.digestOwner;
          NIXKEEPER_MCP_PAGE = cfg.page;
        };
      };
    };
  };
}
