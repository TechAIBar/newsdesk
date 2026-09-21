import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from newsdesk.ui import make_icon

app = QApplication([])
Path('build').mkdir(exist_ok=True)
if not make_icon().pixmap(64, 64).save('build/newsdesk.ico', 'ICO'):
    raise RuntimeError('Could not save icon')
