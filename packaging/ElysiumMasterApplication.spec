# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for the Elysium Master Application (LLD section 13;
# docs/IMPLEMENTATION_PLAN.md phase 8). Replaces the bare-bones reference
# ElysiumCardLookup.spec -- this app has real hidden-import needs (keyring's
# Windows Credential Manager backend, argon2's cffi backend) that PyInstaller
# cannot always auto-detect.
#
# No data files are bundled: the local card database, Scryfall bulk
# download, and image caches are all created at runtime under
# %LOCALAPPDATA%\ElysiumMasterApp (elysium/local_card/paths.py), never
# relative to the install directory.
#
# Build from the repo root with:
#   pip install pyinstaller
#   pyinstaller packaging\ElysiumMasterApplication.spec --clean
# Output lands in dist\ElysiumMasterApplication\.

a = Analysis(
    ['..\\elysium\\main.py'],
    pathex=['..'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'keyring.backends.Windows',
        'win32ctypes.pywin32',
        'win32ctypes.core',
        'argon2',
        'argon2.low_level',
        '_cffi_backend',
        'pymongo',
        'bson',
        'dns',  # dnspython, used by pymongo for mongodb+srv:// URIs
    ],
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
    [],
    exclude_binaries=True,
    name='ElysiumMasterApplication',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ElysiumMasterApplication',
)
