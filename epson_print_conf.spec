# -*- mode: python ; coding: utf-8 -*-

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--default", action="store_true")
options = parser.parse_args()

PROGRAM = [ 'gui.py' ]
DATAS = [('printer_conf.pickle', '.')]

if options.default:
    PROGRAM = [ 'ui.py' ]
    DATAS = []

a = Analysis(
    PROGRAM,
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=['babel.numbers'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='epson_print_conf',
    debug=False,  # Setting to True gives you progress messages from the executable (for console=False there will be annoying MessageBoxes on Windows).
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    # console=False,  # On Windows or Mac OS governs whether to use the console executable or the windowed executable. Always True on Linux/Unix (always console executable - it does not matter there).
    disable_windowed_traceback=False,  # Disable traceback dump of unhandled exception in windowed (noconsole) mode (Windows and macOS only)
    # hide_console='hide-early', # Windows only. In console-enabled executable, hide or minimize the console window ('hide-early', 'minimize-early', 'hide-late', 'minimize-late')
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

