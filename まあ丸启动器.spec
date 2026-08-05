# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_submodules

maa_datas, maa_binaries, maa_hidden = collect_all('maa')
webview_datas, webview_binaries, webview_hidden = collect_all('webview')

datas = [
    ('panel/static', 'panel/static'),
    ('panel/panel_config.example.json', 'panel'),
    ('panel/expedition_schedule.json', 'panel'),
    ('touken_config.json', '.'),
    ('touken/data', 'touken/data'),
    ('resource', 'resource'),
    ('profiles', 'profiles'),
] + maa_datas + webview_datas

binaries = maa_binaries + webview_binaries

hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops.auto',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on',
] + collect_submodules('uvicorn') + maa_hidden + webview_hidden

a = Analysis(
    ['maamaru_launcher.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='まあ丸启动器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
