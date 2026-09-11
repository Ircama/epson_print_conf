{
  babel,
  buildPythonPackage,
  colorama,
  fetchFromGitHub,
  fetchPypi,
  pillow,
  pysnmp,
  pyyaml,
  setuptools,
}:
rec {
  pysnmp-sync-adapter = buildPythonPackage (finalAttrs: {
    pname = "pysnmp_sync_adapter";
    version = "1.1.0";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-iesBgyHfAEapXABOuPD+xKWext7jwsS8nGyqSILtbVM=";
    };

    dependencies = [ pysnmp ];

    pyproject = true;
    build-system = [ setuptools ];
  });

  text-console = buildPythonPackage (finalAttrs: {
    pname = "text_console";
    version = "2.1.0";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-7y4NY8ThgTz8nQvzY9UzKSnfzLzWClN/rDHQSStAfGM=";
    };

    pyproject = true;
    build-system = [ setuptools ];
  });

  tk-date-entry = buildPythonPackage (finalAttrs: {
    pname = "tk_date_entry";
    version = "1.0.0";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="; # TODO: update after first PyPI release
    };

    pyproject = true;
    build-system = [ setuptools ];
  });

  hexdump2 = buildPythonPackage (finalAttrs: {
    pname = "hexdump2";
    version = "1.2.2";

    # source archive not published to pypi, use github source instead
    src = fetchFromGitHub {
      owner = "HGrooms";
      repo = finalAttrs.pname;
      tag = "v${finalAttrs.version}";
      hash = "sha256-ah0hqTu9zDoTQB7+HVtnbI+fw33OS7wXJLCMnjbpKUk=";
    };

    dependencies = [
      colorama
    ];

    pyproject = true;
    build-system = [ setuptools ];
  });

  pyprintlpr = buildPythonPackage (finalAttrs: {
    pname = "pyprintlpr";
    version = "1.1.1";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-EDfZ5//Hn9I5Iv9mMQQB86mp70gzruX4iQmUm5trZBg=";
    };

    dependencies = [
      hexdump2
      pyyaml
    ];

    pyproject = true;
    build-system = [ setuptools ];
  });

  epson-escp2 = buildPythonPackage (finalAttrs: {
    pname = "epson_escp2";
    version = "1.0.4";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-mmus3ho4UvS2csyYP+dH1DkRaSFdfFSluwcKelJcnLk=";
    };

    dependencies = [
      pillow
      hexdump2
    ];

    pyproject = true;
    build-system = [ setuptools ];
  });
}
