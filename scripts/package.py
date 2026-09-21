"""Finish the release without including local caches, credentials, or build environments."""
import argparse
from importlib import metadata
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dist-root', type=Path, default=root / 'dist')
dist_root = parser.parse_args().dist_root.resolve()
if not dist_root.is_relative_to(root / 'dist'):
    raise ValueError('The release output must be inside the project dist directory')
release = dist_root / 'NewsDesk'
if not (release / 'NewsDesk.exe').is_file():
    raise RuntimeError('Build NewsDesk.spec first')
for name in ['Install.ps1', 'Uninstall.ps1']:
    shutil.copy2(root / 'scripts' / name, release / name)
for name in ['README.md', 'THIRD_PARTY_NOTICES.md']:
    shutil.copy2(root / name, release / name)
for dist_name in ['PySide6', 'PySide6_Essentials', 'shiboken6', 'pyinstaller', 'cryptography', 'cffi', 'pycparser']:
    distribution = metadata.distribution(dist_name)
    target = release / 'licenses' / dist_name
    target.mkdir(parents=True, exist_ok=True)
    (target / 'METADATA.txt').write_text(distribution.read_text('METADATA') or '', encoding='utf-8')
    for entry in distribution.files or []:
        if 'licenses' in entry.parts or entry.name.upper().startswith(('LICENSE','COPYING')):
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                shutil.copy2(source, target / entry.name)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.is_file():
    shutil.copy2(python_license, release / 'licenses' / 'Python-LICENSE.txt')
local_licenses = root / 'licenses'
if local_licenses.is_dir():
    shutil.copytree(local_licenses, release / 'licenses' / 'Qt', dirs_exist_ok=True)
source_dir = release / 'source'
for folder in ['newsdesk', 'tests', 'scripts']:
    shutil.copytree(root / folder, source_dir / folder, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for name in ['run.py', 'openclaw_lan.py', 'requirements.txt', 'requirements-build.txt', 'requirements-lan.txt', 'NewsDesk.spec', 'README.md', 'THIRD_PARTY_NOTICES.md']:
    shutil.copy2(root / name, source_dir / name)
if local_licenses.is_dir():
    shutil.copytree(local_licenses, source_dir / 'licenses', dirs_exist_ok=True)
zip_path = shutil.make_archive(str(dist_root / 'NewsDesk-windows-x64'), 'zip', dist_root, 'NewsDesk')
print(zip_path)
