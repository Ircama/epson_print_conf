{
  fetchFromGitHub,
  lib,
  makeWrapper,
  stdenvNoCC,
  pythonWithPackages,
}:
stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "epson_print_conf";
  version = "7.1.0";

  src = fetchFromGitHub {
    owner = "Ircama";
    repo = finalAttrs.pname;
    tag = "v${finalAttrs.version}";
    hash = "sha256-kyNg/JwK0gnjOG9ppThipcyOoQlA90zeJTfWbMPmars=";
  };

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
    cp {epson_print_conf,ui,find_printers,parse_devices}.py $out/lib/${pythonWithPackages.sitePackages}/

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
