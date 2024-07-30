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
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

