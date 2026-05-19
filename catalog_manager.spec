# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Catalog Manager.
# Build:  pyinstaller catalog_manager.spec --clean
#
# Note: the runtime `data/` and `logs/` folders are intentionally NOT bundled
# into the executable — they are created on first launch by
# settings.ensure_dirs(). Bundling them would freeze a user's catalog into
# the binary, which is the opposite of what we want.

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('app', 'app'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
        'sqlalchemy.dialects.sqlite',
        'pydantic_settings',
        'loguru',
        'fitz',
        'reportlab',
        'openpyxl',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'numpy.testing', 'pandas', 'pdfplumber'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CatalogManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,       # No console window
    # icon='icon.ico',   # Uncomment after placing icon.ico in the repo root
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CatalogManager',
)
