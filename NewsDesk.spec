# Both executables share one Qt/Python runtime directory.
from pathlib import Path

a = Analysis(['run.py'], pathex=[], binaries=[], datas=[('newsdesk/resources/openclaw_bootstrap.cjs', 'newsdesk/resources')], hiddenimports=[],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                       'PySide6.QtQml', 'PySide6.QtQuick', 'tkinter'], noarchive=False)
pyz = PYZ(a.pure)
icon = 'build/newsdesk.ico'
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NewsDesk',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, icon=icon)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NewsDesk-CLI',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, icon=icon)
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name='NewsDesk')
