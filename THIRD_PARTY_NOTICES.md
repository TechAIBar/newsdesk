# Third-party components

NewsDesk uses Python, Qt for Python (PySide6 / Shiboken6), Qt Core/Gui/Widgets/Network and PyInstaller's bootloader.

- Python: Python Software Foundation license. https://www.python.org/downloads/source/
- PySide6 / Shiboken6 6.11.2: package metadata declares `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt 6.11.2 libraries: https://code.qt.io/cgit/qt/qtbase.git/ and https://www.qt.io/licensing/open-source-lgpl-obligations
- PyInstaller 6.22.3 bootloader: GPL with a bootloader exception. https://pyinstaller.org/en/stable/license.html
- Cryptography 48.0.1, CFFI, pycparser: used by the optional OpenClaw host component for creating its TLS certificate. Original package license files are included in `licenses/`.

The build copies component metadata and license files into `licenses/`. Qt DLLs are dynamically loaded from `_internal/PySide6`, not statically linked. NewsDesk source and its build instructions are included in `source/`. Qt and Python source are available from their upstream projects at the addresses above. No third-party website articles are bundled in release packages.
