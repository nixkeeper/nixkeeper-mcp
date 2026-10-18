{
  description = "An MCP server answering questions about nixpkgs packages from nixkeeper's digests and dashboard.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      treefmt-nix,
    }:
    {
      # Home Manager: `programs.nixkeeper-mcp.enable = true;` (README).
      homeModules.default = import ./nix/home-manager-module.nix self;
      # The same, under the name older Home Manager setups look for.
      homeManagerModules.default = self.homeModules.default;
    }
    // flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        inherit (pkgs) lib;

        # The code: the standard library only, so it needs no Python packages.
        code = lib.fileset.toSource {
          root = ./.;
          fileset = ./nixkeeper_mcp;
        };
        # The code and its tests (and pyproject.toml, whose version they check).
        src = lib.fileset.toSource {
          root = ./.;
          fileset = lib.fileset.unions [
            ./nixkeeper_mcp
            ./tests
            ./pyproject.toml
          ];
        };

        # `nixkeeper-mcp`: the server on stdio, for an assistant to start.
        nixkeeper-mcp = pkgs.writeShellApplication {
          name = "nixkeeper-mcp";
          derivationArgs.version = (lib.importTOML ./pyproject.toml).project.version;
          text = ''
            PYTHONPATH=${code} exec ${lib.getExe pkgs.python3} -m nixkeeper_mcp "$@"
          '';
          meta = {
            description = "An MCP server answering questions about nixpkgs packages from nixkeeper's data";
            license = lib.licenses.mit;
            mainProgram = "nixkeeper-mcp";
          };
        };

        # `nix fmt` formats everything; checks.formatting fails on anything
        # unformatted. ruff's settings live in pyproject.toml.
        treefmt = treefmt-nix.lib.evalModule pkgs {
          projectRootFile = "flake.nix";
          programs = {
            nixfmt.enable = true;
            ruff-format.enable = true;
            ruff-check.enable = true; # safe auto-fixes, e.g. import order
          };
        };

        # The Home Manager module, evaluated against a stand-in for Home
        # Manager's programs.mcp (its two options): what it puts in the
        # shared servers, by default and with every option set.
        homeManagerServers =
          settings:
          (lib.evalModules {
            modules = [
              self.homeModules.default
              {
                options.programs.mcp = {
                  enable = lib.mkEnableOption "mcp";
                  servers = lib.mkOption {
                    type = lib.types.attrsOf lib.types.anything;
                    default = { };
                  };
                };
                config = {
                  _module.args.pkgs = pkgs;
                  programs.nixkeeper-mcp = settings;
                };
              }
            ];
          }).config.programs.mcp;
        expectHomeManager =
          settings: expected:
          let
            found = homeManagerServers settings;
          in
          lib.assertMsg (found == expected)
            "home-manager module with ${builtins.toJSON settings}: ${builtins.toJSON found}, not ${builtins.toJSON expected}";

        linters = with pkgs; [
          ruff
          deadnix
          statix
          actionlint
        ];
      in
      {
        formatter = treefmt.config.build.wrapper;

        packages.default = nixkeeper-mcp;

        # `nix run`: the server on stdio (-- --help for its options).
        apps.default = {
          type = "app";
          program = lib.getExe nixkeeper-mcp;
          meta.description = "The nixkeeper MCP server, on stdio";
        };

        checks = {
          inherit nixkeeper-mcp;
          tests =
            pkgs.runCommand "nixkeeper-mcp-tests"
              {
                nativeBuildInputs = [ pkgs.python3 ];
              }
              ''
                cd ${src}
                python3 -m unittest discover -s tests -t . -v
                touch $out
              '';
          home-manager-module =
            assert expectHomeManager { } {
              enable = false;
              servers = { };
            };
            assert expectHomeManager { enable = true; } {
              enable = true;
              servers.nixkeeper = {
                command = lib.getExe nixkeeper-mcp;
                args = [ ];
                env = { };
              };
            };
            assert expectHomeManager
              {
                enable = true;
                name = "nk";
                ttl = 60;
                offline = true;
                cacheDir = "/tmp/nk";
                dashboard = "https://example.org/data/";
                digestOwner = "someone";
                page = "https://example.org/";
              }
              {
                enable = true;
                servers.nk = {
                  command = lib.getExe nixkeeper-mcp;
                  args = [
                    "--ttl"
                    "60"
                    "--offline"
                    "--cache-dir"
                    "/tmp/nk"
                  ];
                  env = {
                    NIXKEEPER_MCP_DASHBOARD = "https://example.org/data/";
                    NIXKEEPER_MCP_DIGEST_OWNER = "someone";
                    NIXKEEPER_MCP_PAGE = "https://example.org/";
                  };
                };
              };
            pkgs.writeText "nixkeeper-mcp-home-manager-module" "ok";
          formatting = treefmt.config.build.check self;
          lint = pkgs.runCommand "nixkeeper-mcp-lint" { nativeBuildInputs = linters; } ''
            cd ${self}
            export HOME=$TMPDIR
            ruff check --no-cache .
            deadnix --fail .
            statix check .
            # Named explicitly: on its own actionlint looks for .git, which the
            # flake source (CI's view of the repo) doesn't include.
            actionlint .github/workflows/*.yml
            touch $out
          '';
        };

        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.python3
            treefmt.config.build.wrapper
          ]
          ++ linters;
        };
      }
    );
}
