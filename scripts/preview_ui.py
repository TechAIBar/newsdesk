"""Capture native Windows rendering from a read-only cache snapshot; no network or AI calls."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ['QT_QPA_PLATFORM'] = 'windows'

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QTabWidget
from newsdesk.config import Config
from newsdesk.controller import Controller
from newsdesk.storage import Store
from newsdesk.ui import ClampedLabel, Panel, Settings

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, default=root/'build/qa-data/cache.sqlite3')
args = parser.parse_args()
output = root/'build'
output.mkdir(exist_ok=True)
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
report = {}

with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'cache.sqlite3')) as store:
    if args.data.exists():
        source = sqlite3.connect(args.data.resolve().as_uri()+'?mode=ro', uri=True)
        source.backup(store.db)
        source.close()
    controller = Controller(Config(), store)
    panel = Panel(controller)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()

    def capture(name, width=1180, height=800):
        panel.resize(width, height)
        panel.render()
        for _ in range(3):
            app.processEvents()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert panel.width() == width, (name, 'minimum width overflow', panel.width())
        assert panel.height() == height, (name, 'minimum height overflow', panel.height())
        assert panel.grab().save(str(output/name))
        for column in panel.columns:
            assert column.scroll.width() > 180
        clipped = []
        for child in panel.findChildren(ClampedLabel):
            if child.isVisible() and child.height() + 1 < child.heightForWidth(child.width()):
                clipped.append(child.objectName())
        assert not clipped, (name, clipped)
        report[name] = [panel.width(), panel.height()]
        report['text_font'] = [(child.objectName(), child.font().family(), child.fontInfo().family()) for child in panel.findChildren(ClampedLabel)[:3]]

    capture('design-preview.png')
    capture('design-compact.png', 960, 650)
    paper = next(iter(controller.items('papers')), None)
    if paper:
        paper.ai_summary = '样式示例：中文摘要在独立色块中呈现，快速了解研究重点。悬停可查看完整摘要，点击卡片打开原文。'
        controller.ai_status = '摘要样式预览 · 此条为示例文案'
        capture('design-ai-preview.png')
    dialog = Settings(Config())
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    app.processEvents()
    assert dialog.grab().save(str(output/'design-settings.png'))
    dialog.findChild(QTabWidget).setCurrentIndex(2)
    app.processEvents()
    assert dialog.grab().save(str(output/'design-openclaw.png'))
    dialog.close()
    controller.feeds = {}
    controller.ai_status = 'AI 摘要未启用'
    capture('design-empty.png')
    panel.hide()
    controller.shutdown()

(output/'design-qa.json').write_text(json.dumps(report, indent=2), encoding='utf8')
print(json.dumps(report))
