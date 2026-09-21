import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from newsdesk.config import Config
from newsdesk.controller import Controller
from newsdesk.feeds import FeedResult, item_for
from newsdesk.storage import Store
from newsdesk.ui import Panel, Settings


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'cache.sqlite3')
        self.controller = Controller(Config(), self.store)
        self.panel = Panel(self.controller)

    def tearDown(self):
        self.controller.shutdown()
        self.panel.hide()
        self.panel.deleteLater()
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()

    def test_three_sections_and_search_with_real_widgets(self):
        source = self.controller.config.sources[0]
        item = item_for(source, 'Attention research', 'https://huggingface.co/papers/2609.12345')
        self.controller.feeds = {'hf': FeedResult('hf', [item], day='2026-09-18')}
        self.panel.show()
        self.app.processEvents()
        self.panel.render()
        self.assertEqual([c.ident for c in self.panel.columns], ['papers','news','social'])
        self.assertEqual(self.panel.columns[0].count.text(), '1')
        self.panel.search.setText('nonexistent')
        self.assertEqual(self.panel.columns[0].count.text(), '0')
        self.panel.pin.setChecked(True)
        self.assertTrue(self.panel.pinned)

    def test_settings_cannot_enable_unauthorized_ai(self):
        dialog = Settings(Config())
        self.assertFalse(dialog.ai_enabled.isEnabled())
        self.assertEqual(dialog.table.rowCount(), 6)
        dialog.deleteLater()

    def test_settings_generates_and_copies_one_line_command(self):
        from newsdesk.bootstrap import make_command
        dialog = Settings(Config())
        dialog.host_address.setText('192.168.1.25')
        dialog.host_port.setValue(18880)
        command = dialog.authorization_command.toPlainText()
        self.assertEqual(command, make_command('192.168.1.25', 18880))
        self.assertNotIn('\n', command)
        dialog.copy_authorization_command()
        self.assertEqual(self.app.clipboard().text(), command)
        dialog.host_mode.setCurrentIndex(1)
        self.assertEqual(dialog.authorization_command.toPlainText(), make_command('192.168.1.25', 18880, mode='local'))
        dialog.host_autostart.setChecked(False)
        self.assertEqual(dialog.authorization_command.toPlainText(), make_command('192.168.1.25', 18880, mode='local', autostart=False))
        from newsdesk.bootstrap import make_service_command
        dialog.copy_service_command('stop')
        self.assertEqual(self.app.clipboard().text(), make_service_command('stop'))
        dialog.host_address.setText('invalid')
        self.assertFalse(dialog.copy_command_button.isEnabled())
        self.assertEqual(dialog.authorization_command.toPlainText(), '')
        dialog.deleteLater()

    def test_lan_pairing_runs_off_ui_thread_and_enables_ai(self):
        import copy
        from PySide6.QtTest import QTest
        result = copy.deepcopy(self.controller.config)
        result.ai_authorized = result.ai_enabled = True
        result.ai_mode = 'lan'
        result.ai_lan_url = 'https://192.168.1.20:18790'
        dialog = Settings(Config())
        dialog.pair_code.setText('test-code')
        with patch('newsdesk.lan.pair', return_value=result):
            dialog.start_pairing()
            self.assertFalse(dialog.bottom_buttons.isEnabled())
            for _ in range(100):
                QTest.qWait(10)
                if dialog.pair_job is None:
                    break
        self.assertIsNone(dialog.pair_job)
        self.assertTrue(dialog.ai_enabled.isEnabled())
        self.assertTrue(dialog.ai_enabled.isChecked())
        self.assertEqual(dialog.original.ai_lan_url, result.ai_lan_url)
        dialog.deleteLater()

    def test_refresh_skips_running_sources(self):
        self.controller.busy = {'hf'}
        with patch.object(self.controller.pool, 'start') as start:
            self.controller.refresh('papers')
            start.assert_not_called()

    def test_disabled_sources_are_not_displayed(self):
        source = self.controller.config.sources[0]
        item = item_for(source, 'Cached', 'https://example.com/p')
        self.controller.feeds = {'hf': FeedResult('hf', [item])}
        source.enabled = False
        self.assertEqual(self.controller.items(), [])

    def test_source_reconfigured_during_request_discards_old_response(self):
        import copy
        original = copy.deepcopy(self.controller.config.sources[0])
        self.controller.config.sources[0].url = 'https://example.com/changed'
        self.controller.received((original, FeedResult('hf', [])))
        self.assertNotIn('hf', self.controller.feeds)
        self.assertEqual(self.controller.next_due['hf'], 0)

    def test_daily_digest_never_uses_failed_or_yesterdays_sources(self):
        self.controller.config.quiet_start = self.controller.config.quiet_end = 0
        self.controller.config.digest_time = '00:00'
        source = self.controller.config.sources[0]
        item = item_for(source, 'Yesterday', 'https://example.com/p')
        self.controller.feeds = {'hf': FeedResult('hf', [item], day='2000-01-01')}
        notices = []
        self.controller.notice.connect(lambda a,b: notices.append(a))
        self.controller.daily_notice()
        self.assertEqual(notices, [])

    def test_inflight_ai_does_not_attach_old_summary_to_edited_article(self):
        import copy
        source = self.controller.config.sources[0]
        old = item_for(source, 'Original', 'https://example.com/p')
        current = copy.deepcopy(old)
        current.summary = 'Revised body'
        self.controller.feeds = {'hf': FeedResult('hf', [current])}
        self.controller.ai_received(([old], {old.id: 'Old AI summary'}))
        self.assertEqual(current.ai_summary, '')

    def test_notification_baseline_and_dedup(self):
        from datetime import datetime
        self.controller.config.quiet_start = self.controller.config.quiet_end = 0
        self.controller.config.daily_digest = False
        source = self.controller.config.sources[0]
        today = datetime.now().date().isoformat()
        first = item_for(source, 'First', 'https://example.com/first')
        new = item_for(source, 'New', 'https://example.com/new')
        notices = []
        self.controller.notice.connect(lambda a,b: notices.append(a))
        self.controller.received(FeedResult('hf',[first],today+'T12:00:00',today))
        self.controller.flush_notices()
        self.assertEqual(notices, [])
        self.controller.received(FeedResult('hf',[first,new],today+'T12:10:00',today))
        self.controller.flush_notices()
        self.assertEqual(len(notices), 1)
        self.controller.received(FeedResult('hf',[first,new],today+'T12:20:00',today))
        self.controller.flush_notices()
        self.assertEqual(len(notices), 1)


if __name__ == '__main__':
    unittest.main()
