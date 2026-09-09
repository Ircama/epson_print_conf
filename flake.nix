{
  description = "Nix Flake for epson_print_conf (Epson Printer Config)";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs =
    {
      self,
      nixpkgs,
    }:
    let
      inherit (nixpkgs) lib;
      forEachSupportedSystem =
        f: lib.genAttrs lib.systems.flakeExposed (system: f (import nixpkgs { inherit system; }));

      mkEpsonPrintConf =
        pkgs:
        let
          # modules not in nixpkgs
          dependencyPackages = ps: ps.callPackage ./dependencies.nix { };

          # python environment with all dependencies in python path
          pythonWithPackages = pkgs.python3.withPackages (
            ps:
            (with ps; [
              black
              pyperclip
              pysnmp
              pyyaml
              tkinter
              tomli
            ])
            ++ (builtins.attrValues (dependencyPackages ps))
          );
        in
        pythonWithPackages.pkgs.callPackage ./package.nix {
          inherit pythonWithPackages;
        };
    in
    {
      # note that the executable scripts are prefixed with epson_print_conf (epson_print_conf, epson_print_conf_ui, epson_print_conf_parse_devices, epson_print_conf_find_printers)
      packages = forEachSupportedSystem (pkgs: rec {
        epson-print-conf = mkEpsonPrintConf pkgs;
        default = epson-print-conf;
      });

      # for nix run (e.g., nix run .#ui)
      apps = forEachSupportedSystem (
        pkgs:
        let
          mkApp = name: {
            type = "app";
            program = lib.getExe' (mkEpsonPrintConf pkgs) name;
          };
        in
        {
          epson_print_conf = mkApp "epson_print_conf";
          ui = mkApp "epson_print_conf_ui";
          find_printers = mkApp "epson_print_conf_find_printers";
          parse_devices = mkApp "epson_print_conf_parse_devices";
        }
      );

      devShells = forEachSupportedSystem (
        pkgs:
        pkgs.mkShellNoCC {
          buildInputs = [ (mkEpsonPrintConf pkgs) ];
        }
      );
    };
}
