from __future__ import annotations

import copy
import math
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTime, Signal, QUrl, QThreadPool, Slot
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPen, QPalette, QLinearGradient, QRadialGradient, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QPlainTextEdit,
    QScrollArea, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QTimeEdit, QVBoxLayout, QWidget, QStyle, QStyleOptionButton,
)

from .config import Config, Source, http_url
from .feeds import Item
from .theme import ACCENTS, STYLE, line_icon, make_icon


def label(text="", name="", wrap=False):
    obj = QLabel(text)
    obj.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        obj.setObjectName(name)
    obj.setWordWrap(wrap)
    return obj


class ClampedLabel(QLabel):
    """Wrap naturally in Chinese or English, with an ellipsis on the final visible line."""
    def __init__(self, text, name, lines=3):
        super().__init__(text)
        self.max_lines = lines
        self.setObjectName(name)
        self.setTextFormat(Qt.TextFormat.PlainText)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumWidth(0)

    def text_lines(self, width):
        text = " ".join(self.text().split())
        layout = QTextLayout(text, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        lines = []
        layout.beginLayout()
        for i in range(self.max_lines):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width))
            start, length = line.textStart(), line.textLength()
            # QTextLayout offsets are UTF-16, including surrogate pairs in source titles.
            encoded = text.encode('utf-16-le')
            rest = encoded[start * 2:].decode('utf-16-le')
            if i == self.max_lines - 1:
                lines.append(self.fontMetrics().elidedText(rest, Qt.TextElideMode.ElideRight, max(1, width)))
            else:
                lines.append(encoded[start * 2:(start + length) * 2].decode('utf-16-le').rstrip())
        layout.endLayout()
        return lines or [""]

    def heightForWidth(self, width):
        return len(self.text_lines(width)) * math.ceil(self.fontMetrics().height() * 1.22)

    def hasHeightForWidth(self):
        return True

    def sizeHint(self):
        return QSize(240, self.heightForWidth(240))

    def minimumSizeHint(self):
        return QSize(32, self.fontMetrics().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        height = self.heightForWidth(self.width())
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def setText(self, text):
        super().setText(text)
        if hasattr(self, "max_lines"):
            self.setFixedHeight(self.heightForWidth(self.width()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.setFont(self.font())
        step = math.ceil(self.fontMetrics().height() * 1.22)
        for i, text in enumerate(self.text_lines(self.width())):
            painter.drawText(QPointF(0, self.fontMetrics().ascent() + i * step), text)


def icon_label(kind, color, size=18):
    obj = QLabel()
    obj.setPixmap(line_icon(kind, color, size).pixmap(QSize(size, size), 2))
    obj.setFixedSize(size, size)
    return obj


class SelectBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#91A8C7" if self.isEnabled() else "#536985"), 1.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        x, y = self.width() - 14, self.height() / 2
        painter.drawLine(QPointF(x - 4, y - 2), QPointF(x, y + 2))
        painter.drawLine(QPointF(x, y + 2), QPointF(x + 4, y - 2))


class CheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isChecked():
            option = QStyleOptionButton()
            self.initStyleOption(option)
            rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#123B39"), 1.8, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x, y = rect.x(), rect.y()
            painter.drawLine(QPointF(x + 3, y + 7), QPointF(x + 6, y + 10))
            painter.drawLine(QPointF(x + 6, y + 10), QPointF(x + 11, y + 4))


class Card(QFrame):
    opened = Signal(object)

    def __init__(self, item: Item):
        super().__init__()
        self.item = item
        self.setObjectName("Card")
        self.setProperty("read", item.read)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("打开原文：" + item.title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(10)
        meta = QHBoxLayout()
        meta.setSpacing(7)
        if item.rank:
            meta.addWidget(label(f"{item.rank:02d}", "Rank"))
        meta.addWidget(label(item.source, "SourcePill"))
        meta.addStretch()
        meta.addWidget(label("已读" if item.read else (item.published[5:10] if item.published else ""), "Badge"))
        meta.addWidget(icon_label("arrow", "#6E87A8", 14))
        layout.addLayout(meta)
        layout.addWidget(ClampedLabel(item.title, "CardTitle", 2 if item.section == "social" else 3))
        summary = item.ai_summary or item.summary
        if summary:
            if item.ai_summary:
                well = QFrame()
                well.setObjectName("SummaryWell")
                well.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                body = QVBoxLayout(well)
                body.setContentsMargins(10, 9, 10, 10)
                body.setSpacing(5)
                tag = QHBoxLayout()
                tag.setSpacing(5)
                tag.addWidget(icon_label("spark", "#77D6C6", 12))
                tag.addWidget(label("AI 中文摘要", "AITag"))
                tag.addStretch()
                body.addLayout(tag)
                body.addWidget(ClampedLabel(summary, "AISummary", 4))
                layout.addWidget(well)
            else:
                layout.addWidget(ClampedLabel(summary, "Summary", 3))
        if item.score:
            layout.addWidget(label(item.score, "Badge"))
        self.setToolTip((item.ai_summary or item.summary or item.title)[:1800] + "\n\n" + item.url)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.opened.emit(self.item)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.opened.emit(self.item)
        else:
            super().keyPressEvent(event)


class Column(QFrame):
    refresh = Signal(str)
    opened = Signal(object)

    def __init__(self, ident, title, subtitle, color):
        super().__init__()
        self.ident = ident
        self.signature = None
        self.setObjectName("Column")
        self.setMinimumWidth(0)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 16, 13, 12)
        outer.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        mark = icon_label(ident, color, 19)
        mark.setFixedSize(30, 30)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet("background:#203047; border-radius:8px;")
        row.addWidget(mark)
        row.addWidget(label(title, "SectionTitle"))
        self.count = label("0", "Count")
        row.addWidget(self.count)
        row.addStretch()
        self.button = QPushButton()
        self.button.setIcon(line_icon("refresh", "#9AB1CD", 16))
        self.button.setFixedSize(29, 29)
        self.button.setToolTip("刷新" + title)
        self.button.setAccessibleName("刷新" + title)
        self.button.setObjectName("Small")
        self.button.clicked.connect(lambda: self.refresh.emit(ident))
        row.addWidget(self.button)
        outer.addLayout(row)
        outer.addWidget(label(subtitle, "Eyebrow"))
        self.status = label("等待首次更新", "Status", True)
        self.source_filter = SelectBox()
        self.source_filter.setObjectName("SourceFilter")
        self.source_filter.setMinimumWidth(0)
        self.source_filter.setFixedHeight(31)
        self.source_filter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.source_filter.addItem("全部来源", "")
        outer.addWidget(self.source_filter)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("ScrollBody")
        self.cards = QVBoxLayout(self.body)
        self.cards.setContentsMargins(0, 0, 3, 0)
        self.cards.setSpacing(10)
        self.cards.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        line = QFrame()
        line.setObjectName("Hairline")
        line.setFixedHeight(1)
        outer.addWidget(line)
        outer.addWidget(self.status)

    def update_content(self, controller, query):
        sources = [s for s in controller.enabled() if s.section == self.ident]
        options = [(self.source_filter.itemText(i), self.source_filter.itemData(i)) for i in range(self.source_filter.count())]
        wanted = [("全部来源", "")] + [(s.name, s.id) for s in sources]
        if options != wanted:
            selected = self.source_filter.currentData()
            self.source_filter.blockSignals(True)
            self.source_filter.clear()
            for name, ident in wanted:
                self.source_filter.addItem(name, ident)
            self.source_filter.setCurrentIndex(max(0, self.source_filter.findData(selected)))
            self.source_filter.blockSignals(False)
        self.source_filter.setEnabled(len(sources) > 1)
        selected = self.source_filter.currentData()
        if selected:
            sources = [s for s in sources if s.id == selected]
        items = controller.items(self.ident)
        if selected:
            items = [i for i in items if i.source_id == selected]
        shown = [i for i in items if query in (i.title + " " + i.source + " " + i.summary + " " + i.ai_summary).lower()]
        busy = any(s.id in controller.busy for s in sources)
        self.button.setDisabled(busy)
        self.button.setToolTip("正在更新…" if busy else "刷新此板块")
        self.count.setText(str(len(shown)))
        feeds = [controller.feeds[s.id] for s in sources if s.id in controller.feeds]
        stamps = [f.fetched_at for f in feeds if f.fetched_at]
        errors = [f for f in feeds if f.error]
        today = datetime.now().astimezone().date().isoformat()
        stale = any(f.day != today for f in feeds)
        status = "更新中…" if busy else ("最近获取 " + min(stamps)[5:16].replace("T", " ") if stamps else "等待首次更新")
        if errors:
            status += f" · {len(errors)} 个源暂不可用"
        if stale:
            status += " · 含往日缓存"
        self.status.setText(status)
        self.status.setToolTip(status)
        signature = (query, tuple((i.id, i.title, i.summary, i.published, i.rank, i.score, i.ai_summary, i.read) for i in shown),
                     tuple((f.source_id, f.error, f.note, f.day, f.fetched_at if f.error else "") for f in feeds), busy, tuple(s.id for s in sources))
        if signature == self.signature:
            return
        self.signature = signature
        scroll_value = self.scroll.verticalScrollBar().value()
        while self.cards.count():
            widget = self.cards.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        for s in sources:
            f = controller.feeds.get(s.id)
            if f and f.error:
                last = f"\n显示 {f.day} 的缓存" if f.items else "\n可在设置中更换数据源"
                notice = label(f"{s.name}暂不可用" + last, "Error", True)
                notice.setToolTip(f.error)
                self.cards.addWidget(notice)
            elif f and not f.items and f.note:
                self.cards.addWidget(label(f.note, "Empty", True))
        for item in shown:
            card = Card(item)
            card.opened.connect(self.opened)
            self.cards.addWidget(card)
        if not shown and not errors:
            self.cards.addWidget(label("没有匹配的内容" if query else ("正在整理最新内容…" if busy else "暂无内容，点击刷新试试"), "Empty", True))
        self.scroll.verticalScrollBar().setValue(scroll_value)


class Panel(QWidget):
    settings_requested = Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.pinned = False
        self.hover_mode = True
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("Window")
        self.setWindowTitle("知更 · NewsDesk")
        self.setWindowIcon(make_icon())
        self.setStyleSheet(STYLE)
        self.resize(1180, 800)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 27, 32, 25)
        layout.setSpacing(18)
        top = QHBoxLayout()
        top.setSpacing(11)
        logo = QLabel()
        logo.setPixmap(make_icon().pixmap(QSize(33, 33), 2))
        top.addWidget(logo)
        top.addWidget(label("知更", "Brand"))
        top.addWidget(label("NEWSDESK", "Wordmark"))
        top.addStretch()
        self.pin = QPushButton("固定窗口")
        self.pin.setIcon(line_icon("pin", size=16))
        self.pin.setObjectName("Ghost")
        self.pin.setCheckable(True)
        self.pin.toggled.connect(self.set_pinned)
        top.addWidget(self.pin)
        settings = QPushButton("设置")
        settings.setIcon(line_icon("settings", size=16))
        settings.setObjectName("Ghost")
        settings.clicked.connect(self.settings_requested)
        top.addWidget(settings)
        hide = QPushButton()
        hide.setIcon(line_icon("close"))
        hide.setObjectName("Ghost")
        hide.setFixedSize(31, 31)
        hide.setAccessibleName("收起到托盘")
        hide.setToolTip("收起到托盘；右键托盘图标可以退出")
        hide.clicked.connect(self.hide)
        top.addWidget(hide)
        layout.addLayout(top)
        hero = QHBoxLayout()
        headline = QVBoxLayout()
        headline.setSpacing(7)
        headline.addWidget(label("今日，值得一读。", "Hero"))
        self.date = label("", "Muted")
        headline.addWidget(self.date)
        hero.addLayout(headline)
        hero.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.addAction(line_icon("search", "#8198B9", 18), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setPlaceholderText("搜索标题、来源、摘要…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.render)
        hero.addWidget(self.search)
        self.refresh_all = QPushButton("全部更新")
        self.refresh_all.setIcon(line_icon("refresh", "#173937", 16))
        self.refresh_all.setObjectName("Primary")
        self.refresh_all.clicked.connect(lambda: controller.refresh())
        hero.addWidget(self.refresh_all)
        layout.addLayout(hero)
        content = QHBoxLayout()
        content.setSpacing(14)
        self.columns = []
        for spec in [("papers", "每日论文", "01 / RESEARCH", ACCENTS["papers"]),
                     ("news", "科技快讯", "02 / TECHNOLOGY", ACCENTS["news"]),
                     ("social", "社交热榜", "03 / TRENDING", ACCENTS["social"])]:
            col = Column(*spec)
            col.refresh.connect(controller.refresh)
            col.opened.connect(self.open_item)
            col.source_filter.currentIndexChanged.connect(self.render)
            content.addWidget(col, 1)
            self.columns.append(col)
        layout.addLayout(content, 1)
        footer_frame = QFrame()
        footer_frame.setObjectName("AIFooter")
        footer = QHBoxLayout(footer_frame)
        footer.setContentsMargins(16, 12, 16, 12)
        footer.setSpacing(12)
        footer.addWidget(icon_label("spark", "#83DDC9", 24))
        ai_copy = QVBoxLayout()
        ai_copy.setSpacing(4)
        ai_copy.addWidget(label("AI 阅读助手", "SectionTitle"))
        self.ai_state = ClampedLabel("", "Status", 2)
        ai_copy.addWidget(self.ai_state)
        footer.addLayout(ai_copy, 1)
        self.ai_hint = label("摘要将显示在对应卡片内", "Muted")
        footer.addWidget(self.ai_hint)
        self.ai = QPushButton("生成中文摘要")
        self.ai.setIcon(line_icon("spark", "#A8E8DB", 16))
        self.ai.setObjectName("AIButton")
        self.ai.clicked.connect(controller.generate_ai)
        footer.addWidget(self.ai)
        layout.addWidget(footer_frame)
        controller.changed.connect(self.render)
        self.render()

    def set_pinned(self, state):
        self.pinned = state
        self.pin.setText("已固定" if state else "固定窗口")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        # A painted shadow also works on Windows 10 without relying on DWM effects.
        p.setBrush(Qt.BrushStyle.NoBrush)
        for spread in range(7, 0, -1):
            p.setPen(QPen(QColor(0, 0, 0, 6 + (7 - spread) * 2), 2))
            p.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread), 20 + spread, 20 + spread)
        shape = QPainterPath()
        shape.addRoundedRect(rect, 20, 20)
        background = QLinearGradient(rect.topLeft(), rect.bottomRight())
        background.setColorAt(0, QColor("#122038"))
        background.setColorAt(0.55, QColor("#0C1526"))
        background.setColorAt(1, QColor("#101A2B"))
        p.fillPath(shape, background)
        p.save()
        p.setClipPath(shape)
        glow = QRadialGradient(QPointF(self.width() * 0.78, 0), self.width() * 0.65)
        glow.setColorAt(0, QColor(76, 147, 163, 35))
        glow.setColorAt(1, QColor(76, 147, 163, 0))
        p.fillRect(rect, glow)
        p.setPen(QPen(QColor(141, 190, 214, 18), 1))
        for x in range(max(30, self.width() - 380), self.width() - 30, 18):
            for y in range(28, 160, 18):
                p.drawPoint(x, y)
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#35445E"), 1))
        p.drawPath(shape)
        highlight = QLinearGradient(40, 8, self.width() - 40, 8)
        highlight.setColorAt(0, QColor(102, 206, 193, 0))
        highlight.setColorAt(0.45, QColor(144, 224, 210, 120))
        highlight.setColorAt(1, QColor(142, 174, 255, 0))
        p.setPen(QPen(highlight, 1))
        p.drawLine(QPointF(40, 8.5), QPointF(self.width() - 40, 8.5))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "ai_hint"):
            self.ai_hint.setVisible(self.width() >= 1050)
            self.search.setFixedWidth(240 if self.width() >= 1050 else 200)

    def render(self, *_):
        if not self.isVisible() and self.columns[0].signature is not None:
            return
        now = datetime.now().astimezone()
        self.date.setText(f"{now:%Y年%m月%d日}  ·  {['星期一','星期二','星期三','星期四','星期五','星期六','星期日'][now.weekday()]}  ·  按本机时区更新")
        query = self.search.text().strip().lower()
        for col in self.columns:
            col.update_content(self.controller, query)
        self.refresh_all.setDisabled(bool(self.controller.busy))
        self.refresh_all.setText("正在更新…" if self.controller.busy else "全部更新")
        self.ai.setDisabled(not self.controller.config.ai_enabled or self.controller.ai_busy)
        self.ai_state.setText(self.controller.ai_status)
        self.ai_state.setToolTip(self.controller.ai_status)

    def open_item(self, item):
        if http_url(item.url) and QDesktopServices.openUrl(QUrl(item.url)):
            self.controller.mark_read(item)
            self.render()

    def showEvent(self, event):
        super().showEvent(event)
        self.render()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


class Settings(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.original = config
        self.result_config = None
        self.pair_job = None
        self.setWindowTitle("知更 · 设置")
        self.setStyleSheet(STYLE)
        self.resize(1000, 570)
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        general = QWidget()
        general.setObjectName("SettingsPage")
        form = QFormLayout(general)
        form.setSpacing(16)
        self.notifications = CheckBox("发现新内容时显示 Windows 通知")
        self.notifications.setChecked(config.notifications)
        form.addRow("消息推送", self.notifications)
        self.digest = CheckBox("每天推送一次速览，离线后当日补发")
        self.digest.setChecked(config.daily_digest)
        form.addRow("每日速览", self.digest)
        self.digest_time = QTimeEdit(QTime.fromString(config.digest_time, "HH:mm"))
        self.digest_time.setDisplayFormat("HH:mm")
        form.addRow("速览时间", self.digest_time)
        quiet_row = QHBoxLayout()
        self.quiet_start = QSpinBox()
        self.quiet_end = QSpinBox()
        for spin, value in [(self.quiet_start, config.quiet_start), (self.quiet_end, config.quiet_end)]:
            spin.setRange(0, 23)
            spin.setValue(value)
            spin.setSuffix(" 时")
            quiet_row.addWidget(spin)
        quiet_row.addWidget(label("起止相同表示关闭；免打扰期间继续更新", "Muted"))
        form.addRow("免打扰", quiet_row)
        self.delay = QSpinBox()
        self.delay.setRange(100, 3000)
        self.delay.setSingleStep(50)
        self.delay.setSuffix(" 毫秒")
        self.delay.setValue(config.hover_delay_ms)
        form.addRow("悬停展开延迟", self.delay)
        self.max_items = QSpinBox()
        self.max_items.setRange(10, 200)
        self.max_items.setValue(config.max_items)
        form.addRow("每个源显示条数", self.max_items)
        form.addRow(label("论文始终获取当日完整列表。关闭窗口后继续驻留；右键托盘图标退出。", "Muted", True))
        tabs.addTab(general, "常规")
        source_tab = QWidget()
        source_tab.setObjectName("SettingsPage")
        source_layout = QVBoxLayout(source_tab)
        source_layout.addWidget(label("可编辑地址和刷新间隔。热榜使用第三方服务，源站受限时可换用自建 60s API 或 JSON / RSS 地址。", "Muted", True))
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "板块", "格式", "地址", "分钟", "备用地址", "ID"])
        self.table.setColumnHidden(7, True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for s in config.sources:
            self.add_source(s)
        source_layout.addWidget(self.table)
        buttons = QHBoxLayout()
        add = QPushButton("添加 RSS / JSON 源")
        add.clicked.connect(self.add_custom)
        remove = QPushButton("删除所选")
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        source_layout.addLayout(buttons)
        tabs.addTab(source_tab, "数据源")
        ai_tab = QWidget()
        ai_tab.setObjectName("SettingsPage")
        ai_layout = QVBoxLayout(ai_tab)
        self.connection_status = label(("已配对：" + config.ai_lan_url if config.ai_mode == "lan" else "已授权本机 OpenClaw") if config.ai_authorized else "连接局域网中的 OpenClaw", "SectionTitle", True)
        ai_layout.addWidget(self.connection_status)
        hint = label("复制下面的一句命令，在 OpenClaw 主机终端执行，再将返回的配对码粘贴回来。\n服务在后台运行，成功后可关闭终端。调用现有 main agent。Windows 用 PowerShell，WSL 安装用 WSL 终端。", "Summary", True)
        hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ai_layout.addWidget(hint)
        ai_layout.addWidget(label("1. 复制并执行授权命令", "SectionTitle"))
        command_options = QHBoxLayout()
        self.host_address = QLineEdit()
        self.host_address.setPlaceholderText("OpenClaw 主机 IP（留空自动识别）")
        command_options.addWidget(self.host_address, 1)
        command_options.addWidget(label("端口"))
        self.host_port = QSpinBox()
        self.host_port.setRange(1024, 65535)
        self.host_port.setValue(18790)
        self.host_port.setFixedWidth(110)
        command_options.addWidget(self.host_port)
        advanced_button = QPushButton("高级选项")
        advanced_button.setCheckable(True)
        command_options.addWidget(advanced_button)
        ai_layout.addLayout(command_options)
        advanced = QWidget()
        advanced.setObjectName("SettingsPage")
        advanced_form = QFormLayout(advanced)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        self.host_command = QLineEdit()
        self.host_command.setPlaceholderText("openclaw（非标准安装可填写主机上的完整路径）")
        advanced_form.addRow("OpenClaw 路径", self.host_command)
        self.host_mode = SelectBox()
        self.host_mode.addItem("通过正在运行的 Gateway（推荐）", "gateway")
        self.host_mode.addItem("本地独立运行（仅限未运行 Gateway 的主机）", "local")
        advanced_form.addRow("调用方式", self.host_mode)
        self.host_autostart = CheckBox("主机用户登录后自动启动摘要服务")
        self.host_autostart.setChecked(True)
        advanced_form.addRow("后台启动", self.host_autostart)
        self.rotate_pairing = CheckBox("重新授权时撤销旧配对码")
        advanced_form.addRow("访问权限", self.rotate_pairing)
        advanced.setVisible(False)
        advanced_button.toggled.connect(advanced.setVisible)
        ai_layout.addWidget(advanced)
        self.authorization_command = QPlainTextEdit()
        self.authorization_command.setReadOnly(True)
        self.authorization_command.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.authorization_command.setFixedHeight(66)
        self.authorization_command.setAccessibleName("在 OpenClaw 主机执行的单行授权命令")
        ai_layout.addWidget(self.authorization_command)
        command_actions = QHBoxLayout()
        self.copy_command_button = QPushButton("复制授权命令")
        self.copy_command_button.setObjectName("Primary")
        self.copy_command_button.clicked.connect(self.copy_authorization_command)
        command_actions.addWidget(self.copy_command_button)
        self.command_status = label("", "Status", True)
        command_actions.addWidget(self.command_status, 1)
        ai_layout.addLayout(command_actions)
        for widget in (self.host_address, self.host_command):
            widget.textChanged.connect(self.update_authorization_command)
        self.host_port.valueChanged.connect(self.update_authorization_command)
        self.host_mode.currentIndexChanged.connect(self.update_authorization_command)
        self.host_autostart.toggled.connect(self.update_authorization_command)
        self.rotate_pairing.toggled.connect(self.update_authorization_command)
        ai_layout.addWidget(label("首次从旧版升级，请先在旧配对终端按 Ctrl+C，再执行新命令。证书和配对码会保留；主机防火墙需允许所选端口。", "Muted", True))
        service_actions = QHBoxLayout()
        for title, action in [("复制启动命令", "start"), ("复制停止命令", "stop"), ("复制状态命令", "status")]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, value=action: self.copy_service_command(value))
            service_actions.addWidget(button)
        service_actions.addStretch()
        ai_layout.addLayout(service_actions)
        ai_layout.addWidget(label("2. 粘贴配对码", "SectionTitle"))
        pair_row = QHBoxLayout()
        self.pair_code = QLineEdit()
        self.pair_code.setPlaceholderText("粘贴主机生成的 ND1- 配对码")
        self.pair_code.setEchoMode(QLineEdit.EchoMode.Password)
        self.pair_button = QPushButton("验证配对")
        self.pair_button.clicked.connect(self.start_pairing)
        pair_row.addWidget(self.pair_code, 1)
        pair_row.addWidget(self.pair_button)
        ai_layout.addLayout(pair_row)
        self.ai_enabled = CheckBox("允许通过已配对的 OpenClaw 生成中文摘要")
        self.ai_enabled.setChecked(config.ai_enabled)
        self.ai_enabled.setEnabled(config.ai_authorized)
        ai_layout.addWidget(self.ai_enabled)
        ai_layout.addWidget(label("配对成功后点击「保存」。摘要按需生成，费用遵循主机上的模型配置。", "Muted", True))
        limit_row = QFormLayout()
        self.ai_limit = QSpinBox()
        self.ai_limit.setRange(1, 20)
        self.ai_limit.setValue(config.ai_limit)
        limit_row.addRow("每次摘要条数", self.ai_limit)
        ai_layout.addLayout(limit_row)
        ai_layout.addStretch()
        ai_scroll = QScrollArea()
        ai_scroll.setWidgetResizable(True)
        ai_scroll.setWidget(ai_tab)
        tabs.addTab(ai_scroll, "OpenClaw")
        bottom = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.bottom_buttons = bottom
        bottom.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        bottom.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bottom.accepted.connect(self.save)
        bottom.rejected.connect(self.reject)
        outer.addWidget(bottom)
        self.update_authorization_command()

    def update_authorization_command(self, *_):
        from .bootstrap import make_command
        try:
            command = make_command(self.host_address.text(), self.host_port.value(), self.host_command.text(), self.rotate_pairing.isChecked(), self.host_mode.currentData(), self.host_autostart.isChecked())
            self.authorization_command.setPlainText(command)
            self.copy_command_button.setEnabled(True)
            self.command_status.setText("命令已就绪，可直接复制执行")
        except (ValueError, OSError) as exc:
            self.authorization_command.clear()
            self.copy_command_button.setEnabled(False)
            self.command_status.setText(str(exc))

    def copy_authorization_command(self):
        command = self.authorization_command.toPlainText()
        if command:
            QApplication.clipboard().setText(command)
            self.command_status.setText("已复制，请在 OpenClaw 主机终端粘贴执行")

    def copy_service_command(self, action):
        from .bootstrap import make_service_command
        QApplication.clipboard().setText(make_service_command(action))
        self.command_status.setText("管理命令已复制，请在已完成授权的 OpenClaw 主机执行")

    def start_pairing(self):
        from .controller import Job
        from .lan import pair
        if self.pair_job:
            return
        code = self.pair_code.text().strip()
        self.pair_button.setDisabled(True)
        self.bottom_buttons.setDisabled(True)
        self.connection_status.setText("正在验证局域网连接和访问权限…")
        self.pair_job = Job(lambda: pair(self.original, code))
        self.pair_job.signals.done.connect(self.pair_finished)
        QThreadPool.globalInstance().start(self.pair_job)

    @Slot(object)
    def pair_finished(self, result):
        self.pair_job = None
        self.pair_button.setEnabled(True)
        self.bottom_buttons.setEnabled(True)
        if isinstance(result, Exception):
            message = str(result) if isinstance(result, ValueError) else "连接失败，请检查主机服务、IP 地址和防火墙"
            self.connection_status.setText("配对失败：" + message)
            return
        self.original = result
        self.ai_enabled.setEnabled(True)
        self.ai_enabled.setChecked(True)
        self.pair_code.clear()
        self.connection_status.setText("配对成功：" + result.ai_lan_url + " · 点击保存生效")

    def reject(self):
        if self.pair_job is None:
            super().reject()

    def add_custom(self):
        import uuid
        self.add_source(Source("custom_" + uuid.uuid4().hex[:8], "自定义源", "news", "rss", "https://"))

    def add_source(self, source):
        row = self.table.rowCount()
        self.table.insertRow(row)
        enabled = QTableWidgetItem()
        enabled.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        enabled.setCheckState(Qt.CheckState.Checked if source.enabled else Qt.CheckState.Unchecked)
        self.table.setItem(row, 0, enabled)
        for col, value in [(1, source.name), (4, source.url), (5, str(source.interval)), (6, source.fallback), (7, source.id)]:
            self.table.setItem(row, col, QTableWidgetItem(value))
        for col, options, value in [(2, [("论文", "papers"), ("科技", "news"), ("热榜", "social")], source.section),
                                    (3, [("RSS", "rss"), ("JSON 热榜", "hot"), ("Hugging Face", "hf"), ("微博直连", "weibo")], source.kind)]:
            box = SelectBox()
            for name, ident in options:
                box.addItem(name, ident)
            box.setCurrentIndex(box.findData(value))
            self.table.setCellWidget(row, col, box)

    def save(self):
        try:
            cfg = copy.deepcopy(self.original)
            cfg.sources = []
            for row in range(self.table.rowCount()):
                text = lambda c: self.table.item(row, c).text().strip()
                cfg.sources.append(Source(text(7), text(1), self.table.cellWidget(row, 2).currentData(),
                                          self.table.cellWidget(row, 3).currentData(), text(4), int(text(5)),
                                          self.table.item(row, 0).checkState() == Qt.CheckState.Checked, text(6)))
            cfg.notifications = self.notifications.isChecked()
            cfg.daily_digest = self.digest.isChecked()
            cfg.digest_time = self.digest_time.time().toString("HH:mm")
            cfg.quiet_start, cfg.quiet_end = self.quiet_start.value(), self.quiet_end.value()
            cfg.hover_delay_ms = self.delay.value()
            cfg.max_items = self.max_items.value()
            cfg.ai_enabled = self.ai_enabled.isChecked()
            cfg.ai_limit = self.ai_limit.value()
            cfg.save()
            self.result_config = cfg
            self.accept()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "设置未保存", str(exc))
