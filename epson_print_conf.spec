# -*- mode: python ; coding: utf-8 -*-

import argparse
import os
import os.path
from PIL import Image, ImageDraw, ImageFont
from PyInstaller.utils.hooks import collect_submodules, collect_data_files


def create_image(png_file, text):
    x_size = 800
    y_size = 150
    font_size = 30
    img = Image.new('RGB', (x_size, y_size), color='black')
    fnt = ImageFont.truetype('arialbd.ttf', font_size)
    d = ImageDraw.Draw(img)
    shadow_offset = 2
    bbox = d.textbbox((0, 0), text, font=fnt)
    x, y = (x_size-bbox[2])/2, (y_size-bbox[3])/2
    d.text((x+shadow_offset, y+shadow_offset), text, font=fnt, fill='gray')
    d.text((x, y), text, font=fnt, fill='#baf8f8')
    img.save(png_file, 'PNG')


parser = argparse.ArgumentParser()
parser.add_argument("--default", action="store_true")
parser.add_argument("--version", action="store", default=None)
options = parser.parse_args()

PROGRAM = [ 'gui.py' ]
BASENAME = 'epson_print_conf'

DATAS = [(BASENAME + '.pickle', '.')]
SPLASH_IMAGE = BASENAME + '.png'

version = (
    "ui.VERSION = '" + options.version.replace('v', '') + "'"
) if options.version else ""

create_image(
    SPLASH_IMAGE, 'Epson Printer Configuration tool loading...'
)

if not options.default and not os.path.isfile(DATAS[0][0]):
    print("\nMissing file", DATAS[0][0], "without using the default option.")
    quit()

gui_wrapper = """import pyi_splash
import pickle
import ui
from os import path

""" + version + """
path_to_pickle = path.abspath(
    path.join(path.dirname(__file__), '""" + DATAS[0][0] + """')
)
with open(path_to_pickle, 'rb') as fp:
    conf_dict = pickle.load(fp)
app = ui.EpsonPrinterUI(conf_dict=conf_dict, replace_conf=False)
pyi_splash.close()
app.mainloop()
"""

if options.default:
    DATAS = []
    gui_wrapper = """import pyi_splash
import pickle
import ui
from os import path

""" + version + """
app = ui.main()
pyi_splash.close()
app.mainloop()
"""

with open(PROGRAM[0], 'w') as file:
    file.write(gui_wrapper)

# black submodules: https://github.com/pyinstaller/pyinstaller/issues/8270
black_submodules = collect_submodules('black')
blib2to3_submodules = collect_submodules('blib2to3')

# "black" data files: https://github.com/pyinstaller/pyinstaller/issues/8270
blib2to3_data = collect_data_files('blib2to3')

a = Analysis(
    PROGRAM,
    pathex=[],
    binaries=[],
    datas=DATAS + blib2to3_data,  # the latter required by black
    hiddenimports=[
        'babel.numbers',
        # The following modules are needed by "black": https://github.com/pyinstaller/pyinstaller/issues/8270
        '30fcd23745efe32ce681__mypyc',
        '6b397dd64e00b5aff23d__mypyc', 'click', 'json', 'platform',
        'mypy_extensions', 'pathspec', '_black_version', 'platformdirs'
    ] + black_submodules + blib2to3_submodules,  # the last two required by black
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)
splash = Splash(
    SPLASH_IMAGE,
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name=BASENAME,
    debug=False,  # Setting to True gives you progress messages from the executable (for console=False there will be annoying MessageBoxes on Windows).
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=options.default,  # On Windows or Mac OS governs whether to use the console executable or the windowed executable. Always True on Linux/Unix (always console executable - it does not matter there).
    disable_windowed_traceback=False,  # Disable traceback dump of unhandled exception in windowed (noconsole) mode (Windows and macOS only)
    hide_console='hide-early', # Windows only. In console-enabled executable, hide or minimize the console window ('hide-early', 'minimize-early', 'hide-late', 'minimize-late')
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

os.remove(SPLASH_IMAGE)
os.remove(PROGRAM[0])
