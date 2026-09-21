"""Desktop verification using the actual Windows tray geometry, with no cursor movement."""
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
root = Path(__file__).resolve().parents[1]
os.environ['NEWSDESK_DATA_DIR'] = str(root / 'build' / 'qa-data')

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QTabWidget
from newsdesk.app import Application
from newsdesk.config import Config
from newsdesk.ui import Settings

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
instance = Application(app, Config(), offline=True)
report = {}


def check():
    try:
        rect = instance.tray.geometry()
        report['tray_available'] = instance.tray.isSystemTrayAvailable()
        report['tray_rect'] = [rect.x(), rect.y(), rect.width(), rect.height()]
        assert not rect.isEmpty(), 'Windows tray icon geometry unavailable'
        # Feed the real icon position to the hover state machine without moving the user's mouse.
        with patch('newsdesk.app.QCursor.pos', return_value=rect.center()):
            instance.hover_start = time.monotonic() - 1
            instance.poll_hover()
            assert instance.panel.isVisible(), 'Hover did not open the panel'
            assert instance.panel.hover_mode
        with patch('newsdesk.app.QCursor.pos', return_value=QPoint(-10000, -10000)):
            instance.outside_start = time.monotonic() - 2
            instance.poll_hover()
            assert not instance.panel.isVisible(), 'Mouse leave did not hide panel'
        instance.show_panel(False)
        instance.panel.pin.setChecked(True)
        with patch('newsdesk.app.QCursor.pos', return_value=QPoint(-10000, -10000)):
            instance.outside_start = time.monotonic() - 2
            instance.poll_hover()
            assert instance.panel.isVisible(), 'Pinned panel incorrectly hidden'
        instance.panel.pin.setChecked(False)
        report['hover_open_leave_hide_pin'] = 'passed'
        instance.panel.grab().save(str(root / 'build' / 'preview.png'))
        news = instance.panel.columns[1]
        news.source_filter.setCurrentIndex(news.source_filter.findData('techcrunch'))
        app.processEvents()
        assert news.count.text() == '20'
        report['source_filter'] = 'passed'
        news.source_filter.setCurrentIndex(0)
        # Links are routed through the OS only when clicked; capture the actual request.
        item = instance.controller.items('papers')[0]
        with patch('newsdesk.ui.QDesktopServices.openUrl', return_value=True) as browser:
            instance.panel.open_item(item)
            assert browser.call_args.args[0].toString() == item.url
            assert item.read
        report['original_link_dispatch'] = 'passed'
        instance.dialog_open = True
        dialog = Settings(instance.controller.config)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(root / 'build' / 'settings-preview.png'))
        dialog.findChild(QTabWidget).setCurrentIndex(2)
        app.processEvents()
        dialog.grab().save(str(root / 'build' / 'pairing-preview.png'))
        dialog.hide()
        report['settings_render'] = 'passed'
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        (root / 'build' / 'windows-smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        instance.quit()


QTimer.singleShot(700, check)
app.exec()
instance.store.close()
print(json.dumps(report))
raise SystemExit(1 if report.get('error') else 0)
