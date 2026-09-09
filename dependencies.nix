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
    version = "1.0.8";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-uNd8MOxwOsbMLG9PkFzLchi8rG/RIPX1dK+U3ar1aPY=";
    };

    dependencies = [ pysnmp ];

    pyproject = true;
    build-system = [ setuptools ];
  });

  text-console = buildPythonPackage (finalAttrs: {
    pname = "text_console";
    version = "2.0.7";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-DmhLZOaklqLa/7evJCxZ5m/JSsRkGgSmjFC0XtVT4BM=";
    };

    pyproject = true;
    build-system = [ setuptools ];
  });

  tkcalendar = buildPythonPackage (finalAttrs: {
    pname = "tkcalendar";
    version = "1.6.1";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-Xt+VjApZQp6QMJ6bgFsuIpGSu8q5UkYCRyBNcDDupc8=";
    };

    dependencies = [ babel ];

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
    version = "1.0.3";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-zcGftwTo+g+fsNdIwKUgwJ1yxyxYIA7dPofuMY9olPs=";
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
    version = "1.0.2";

    src = fetchPypi {
      inherit (finalAttrs) pname version;
      hash = "sha256-p+Plp030tuydO3kqh5RfbwdOFRRFjOpzLreIUK3olg8=";
    };

    dependencies = [
      pillow
      hexdump2
    ];

    pyproject = true;
    build-system = [ setuptools ];
  });
}
