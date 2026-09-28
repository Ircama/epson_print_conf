{
  src,
  lib,
  makeWrapper,
  stdenvNoCC,
  pythonWithPackages,
}:

let
  #: The version is kept in `ui.py` -- the file the program actually runs --
  #: and nowhere else. The release workflow rewrites that one line from the git
  #: tag, so the tag, the GUI and this package cannot drift apart. Reading it
  #: here instead of repeating it is what keeps `nix build` and the program in
  #: step: a second literal in this file was the copy that went stale.
  versionLine = lib.findFirst
    (line: lib.hasPrefix "VERSION = " (lib.removeSuffix "\r" line))
    (throw "package.nix: no 'VERSION = \"...\"' line in ui.py")
    (lib.splitString "\n" (builtins.readFile ./ui.py));
  # `\r` goes first, so that a checkout with Windows line endings -- which is
  # what a build from a dirty tree sees -- is read like one with Unix ones.
  versionMatch = builtins.match "VERSION = \"([0-9][^\"]*)\""
    (lib.trim (lib.removeSuffix "\r" versionLine));
  version =
    if versionMatch == null then
      throw "package.nix: ui.py must contain a line 'VERSION = \"x.y.z\"'"
    else
      builtins.head versionMatch;
in
stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "epson_print_conf";
  inherit version;

  # The source is the repository itself, handed over by flake.nix (`src = self`).
  # The package is built from the tree being evaluated, so there is no tag to
  # fetch and no source hash to refresh when a release is cut -- the hash this
  # used to carry was, twice, the copy nobody remembered to bump.
  inherit src;

  nativeBuildInputs = [
    makeWrapper
  ];

  installPhase = ''
    # create wrapper to run the script from the python environment
    wrap_script() {
      makeWrapper ${pythonWithPackages.interpreter} "$out/bin/$2" \
        --add-flags "-m $1" \
        --prefix PYTHONPATH : "$out/lib/${pythonWithPackages.sitePackages}"
    }

    # put the scripts as modules under site packages and create wrapper scripts to setup python environment
    mkdir -p $out/bin $out/lib/${pythonWithPackages.sitePackages}
    # epson_usb_bridge.py is imported by epson_print_conf.py (it carries the USB
    # transport): without it here, `--usb` cannot be selected in this package,
    # whatever the Python environment below provides.
    cp {epson_print_conf,epson_usb_bridge,ui,find_printers,parse_devices}.py $out/lib/${pythonWithPackages.sitePackages}/

    # prefix the name of the scripts with epson_print_conf
    wrap_script epson_print_conf epson_print_conf
    wrap_script ui epson_print_conf_ui
    wrap_script find_printers epson_print_conf_find_printers
    wrap_script parse_devices epson_print_conf_parse_devices
  '';

  meta = {
    description = "Epson Printer Configuration tool and waste ink counter resetter";
    descriptionLong = ''
      The Epson Printer Configuration Tool provides an interface for the configuration and monitoring of Epson printers connected via Wi-Fi using the SNMP protocol. A range of features are offered for both end-users and developers.

      The software also includes a configurable printer dictionary, which can be easily extended. In addition, it is possible to import and convert external Epson printer configuration databases.
    '';
    homepage = "https://github.com/Ircama/epson_print_conf";
    license = lib.licenses.eupl12;
    platforms = lib.platforms.all;
    mainProgram = "epson_print_conf";
  };
})
