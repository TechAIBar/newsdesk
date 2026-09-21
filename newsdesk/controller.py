from __future__ import annotations

import copy
import logging
import time
from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from .ai import summarize
from .config import Config, is_quiet
from .feeds import FeedResult, fetch_source
from .storage import Store, fingerprint


class JobSignals(QObject):
    done = Signal(object)


class Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = JobSignals()

    def run(self):
        try:
            value = self.fn()
        except Exception as exc:
            value = exc
        self.signals.done.emit(value)


class Controller(QObject):
    changed = Signal()
    notice = Signal(str, str)

    def __init__(self, config: Config, store: Store):
        super().__init__()
        self.config, self.store = config, store
        self.feeds = store.feeds()
        self.busy = set()
        self.next_due = {}
        self.jobs = {}
        self.pending_news = []
        self.ai_busy = False
        self.ai_status = "OpenClaw 已连接" if config.ai_enabled else "AI 摘要未启用"
        self.closing = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(6)
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.tick)
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.flush_notices)

    def start(self):
        self.timer.start()
        self.refresh()

    def enabled(self):
        return [s for s in self.config.sources if s.enabled]

    def items(self, section: str | None = None):
        enabled = {s.id for s in self.enabled()}
        items = [i for s, feed in self.feeds.items() if s in enabled for i in feed.items if section is None or i.section == section]
        if section == "news":
            items.sort(key=lambda i: i.published, reverse=True)
            # Cross-feed duplicate links should only appear once.
            items = list({i.url: i for i in reversed(items)}.values())[::-1]
        return items

    def refresh(self, section: str | None = None):
        for source in self.enabled():
            if section is not None and source.section != section:
                continue
            if source.id in self.busy or self.closing:
                continue
            self.busy.add(source.id)
            job = Job(lambda s=copy.deepcopy(source): (s, fetch_source(s, self.config.max_items)))
            self.jobs[source.id] = job
            job.signals.done.connect(self.received)
            self.pool.start(job)
        self.changed.emit()

    @Slot(object)
    def received(self, result):
        if self.closing:
            return
        requested_source = None
        if isinstance(result, tuple):
            requested_source, result = result
        if not isinstance(result, FeedResult):
            logging.error("Unexpected feed worker error: %s", type(result).__name__)
            return
        source = next((s for s in self.config.sources if s.id == result.source_id), None)
        self.busy.discard(result.source_id)
        self.jobs.pop(result.source_id, None)
        self.next_due[result.source_id] = time.monotonic() + (source.interval * 60 if source else 1800)
        if source is None or not source.enabled:
            self.changed.emit()
            return
        if requested_source is not None and requested_source != source:
            self.next_due[result.source_id] = 0
            self.changed.emit()
            return
        merged, fresh = self.store.merge(result)
        self.feeds[result.source_id] = merged
        if result.error:
            logging.info("Source %s: %s", source.id, result.error)
        if self.config.notifications and not self.quiet():
            self.pending_news.extend(fresh)
            if fresh:
                self.notice_timer.start(2500)
        self.changed.emit()
        if not self.busy:
            self.daily_notice()

    def quiet(self):
        return is_quiet(datetime.now().hour, self.config.quiet_start, self.config.quiet_end)

    def tick(self):
        now = time.monotonic()
        for s in self.enabled():
            if s.id not in self.busy and now >= self.next_due.get(s.id, 0):
                # Refresh only this source, without issuing other sources again.
                self.busy.add(s.id)
                job = Job(lambda source=copy.deepcopy(s): (source, fetch_source(source, self.config.max_items)))
                self.jobs[s.id] = job
                job.signals.done.connect(self.received)
                self.pool.start(job)
        self.daily_notice()
        self.changed.emit()

    def flush_notices(self):
        items, self.pending_news = self.pending_news, []
        if items and self.config.notifications and not self.quiet():
            titles = "\n".join(i.title[:55] for i in items[:3])
            self.notice.emit(f"知更 · {len(items)} 条新内容", titles)

    def daily_notice(self):
        now = datetime.now().astimezone()
        day = now.date().isoformat()
        if not self.config.notifications or not self.config.daily_digest or self.quiet() or self.busy:
            return
        hh, mm = map(int, self.config.digest_time.split(":"))
        if (now.hour, now.minute) < (hh, mm) or self.store.get("digest_day") == day:
            return
        enabled = {s.id for s in self.enabled()}
        feeds = [f for sid, f in self.feeds.items() if sid in enabled and not f.error and f.day == day and f.items]
        if not feeds:
            return
        lines = [f"{f.items[0].source}：{f.items[0].title[:42]}" for f in feeds]
        self.notice.emit("知更 · 今日速览", "\n".join(lines)[:240])
        self.store.set("digest_day", day)

    def generate_ai(self):
        if self.ai_busy or not self.config.ai_enabled:
            return
        today = datetime.now().astimezone().date().isoformat()
        valid = {sid for sid, f in self.feeds.items() if not f.error and f.day == today}
        candidates = [i for i in self.items() if i.source_id in valid and not i.ai_summary][:self.config.ai_limit]
        if not candidates:
            self.ai_status = "当前内容已有摘要，或暂无今日可处理内容"
            self.changed.emit()
            return
        self.ai_busy = True
        self.ai_status = f"正在生成 {len(candidates)} 条中文摘要…"
        job = Job(lambda: (candidates, summarize(copy.deepcopy(self.config), candidates)))
        self.jobs["ai"] = job
        job.signals.done.connect(self.ai_received)
        self.pool.start(job)
        self.changed.emit()

    @Slot(object)
    def ai_received(self, value):
        if self.closing:
            return
        self.ai_busy = False
        self.jobs.pop("ai", None)
        if isinstance(value, Exception):
            self.ai_status = "AI 暂不可用：" + (str(value)[:100] if isinstance(value, (ValueError, RuntimeError)) else "调用超时或连接失败")
        else:
            items, summaries = value
            fingerprints = {i.id: fingerprint(i) for i in items}
            for i in items:
                if i.id in summaries:
                    self.store.save_summary(i, summaries[i.id])
            # A refresh may have replaced the original Item instances during generation.
            for current in self.items():
                if current.id in summaries and fingerprint(current) == fingerprints.get(current.id):
                    current.ai_summary = summaries[current.id]
            for f in self.feeds.values():
                self.store._save(f)
            self.ai_status = f"已生成 {len(summaries)} 条中文摘要 · 点击可继续下一批"
        self.changed.emit()

    def mark_read(self, item):
        item.read = True
        self.store.mark_read(item.id)

    def shutdown(self):
        self.closing = True
        self.timer.stop()
        self.notice_timer.stop()
        self.pool.clear()
        # Running network jobs have finite timeouts. Do not destroy their signal objects early.
