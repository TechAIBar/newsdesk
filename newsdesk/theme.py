"""NewsDesk's native, resolution-independent visual system."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


ACCENTS = {"papers": "#8EAEFF", "news": "#6ADBCB", "social": "#C4A5FA"}

STYLE = """
QWidget { color:#DCE6F4; font-family:'Microsoft YaHei UI','Segoe UI'; font-size:12px; }
QLabel { background:transparent; border:0; }
QLabel#Brand { color:#F2F6FC; font-size:20px; font-weight:700; }
QLabel#Wordmark { color:#889BB7; font-family:'Segoe UI'; font-size:10px; letter-spacing:2px; }
QLabel#Hero { font-size:27px; font-weight:700; color:#F2F6FC; }
QLabel#Eyebrow { color:#7590B3; font-family:'Segoe UI'; font-size:10px; letter-spacing:2px; }
QLabel#Muted, QLabel#Status { color:#8A9DB9; font-size:11px; }
QLabel#SectionTitle { font-size:16px; font-weight:600; color:#EDF3FC; }
QLabel#Count { color:#9EAFCA; background:#1B2940; border-radius:7px; padding:2px 7px; font-family:'Consolas'; font-size:11px; }
QLabel#Badge { color:#9AAEC9; font-size:10px; }
QLabel#SourcePill { color:#BAC9DF; background:#202E45; border-radius:5px; padding:3px 6px; font-size:10px; }
QLabel#Rank { font-family:'Consolas'; font-size:20px; font-weight:700; color:#C4A5FA; }
QLabel#Error { color:#D9B57E; font-size:11px; background:#29261F; border:1px solid #42382B; border-radius:9px; padding:10px; }
QLabel#Empty { color:#8A9DB9; padding:30px 12px; }
QLabel#Summary { color:#A5B4CA; font-size:12px; }
QLabel#AISummary { color:#B7E7DC; font-size:12px; }
QLabel#AITag { color:#77D6C6; font-size:10px; font-weight:600; }
QLabel#CardTitle { font-size:14px; font-weight:600; color:#E5EDFA; }
QFrame#Column { background:#0F1829; border:1px solid #223049; border-radius:14px; }
QFrame#Card { background:#162136; border:1px solid #25344E; border-radius:11px; }
QFrame#Card:hover, QFrame#Card:focus { background:#1B2B44; border-color:#6C93C3; }
QFrame#Card[read="true"] { border-color:#1F2E45; }
QFrame#SummaryWell { background:#132F35; border:1px solid #21434A; border-radius:8px; }
QFrame#AIFooter { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #142B34,stop:1 #142034); border:1px solid #29404E; border-radius:12px; }
QFrame#Hairline { background:#233148; border:0; max-height:1px; }
QWidget#ScrollBody { background:transparent; }
QWidget#SettingsPage { background:#131F32; }
QPushButton { background:#1A283F; color:#D2DFF1; border:1px solid #30415C; border-radius:8px; padding:8px 13px; }
QPushButton:hover { background:#263A56; border-color:#6485AB; color:#F2F7FF; }
QPushButton:pressed, QPushButton:checked { background:#1F424E; color:#A2F1DE; border-color:#3C857F; }
QPushButton:focus { border-color:#8EAEFF; }
QPushButton:disabled { color:#7385A1; background:#152135; border-color:#26334A; }
QPushButton#Primary { background:#88DCCF; color:#102C30; border:1px solid #A6EEE2; font-weight:600; }
QPushButton#Primary:hover { background:#B1F1E4; border-color:#CDFBF2; }
QPushButton#Primary:disabled { color:#637F85; background:#263E49; border-color:#34505B; }
QPushButton#Ghost { background:transparent; border-color:transparent; color:#A6B8D0; padding:6px 10px; }
QPushButton#Ghost:hover { background:#21324C; border-color:#3A5070; }
QPushButton#Ghost:checked { background:#20403F; color:#91E7D5; border-color:#35635C; }
QPushButton#Small { font-size:11px; padding:4px 7px; background:transparent; border-color:transparent; }
QPushButton#Small:hover { background:#263954; border-color:#456081; }
QPushButton#AIButton { color:#B8F0E5; background:#224840; border-color:#366B62; font-weight:600; padding:9px 14px; }
QPushButton#AIButton:hover { background:#2B5B50; border-color:#69A393; }
QPushButton#AIButton:disabled { color:#7B9C99; background:#203A3C; border-color:#2B4A4C; }
QLineEdit, QSpinBox, QTimeEdit, QComboBox, QPlainTextEdit { background:#101B2E; color:#D4E0F2; border:1px solid #31415E; border-radius:7px; padding:7px 9px; selection-background-color:#365B87; }
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color:#76C9C5; }
QLineEdit#Search { background:#111E32; border:1px solid #344863; padding:10px 8px; }
QComboBox#SourceFilter { background:#131F32; border-color:#263750; font-size:11px; padding:5px 9px; }
QComboBox:disabled { color:#A2B4CD; }
QComboBox::drop-down { border:0; width:24px; }
QComboBox::down-arrow { width:0; height:0; }
QComboBox QAbstractItemView { background:#1B2B43; color:#DEEAF8; border:1px solid #476487; selection-background-color:#345775; outline:0; }
QPlainTextEdit { font-family:'Consolas'; font-size:12px; }
QCheckBox { spacing:8px; background:transparent; }
QCheckBox::indicator { width:14px; height:14px; border:1px solid #59738F; border-radius:4px; background:#152238; }
QCheckBox::indicator:checked { background:#74CFBE; border-color:#9AE1D2; }
QCheckBox:disabled { color:#71829D; }
QScrollArea { background:transparent; border:0; }
QScrollBar:vertical { background:transparent; width:5px; margin:3px 0; }
QScrollBar:horizontal { background:#111B2C; height:6px; margin:0 3px; }
QScrollBar::handle:vertical { background:#3C4D69; border-radius:2px; min-height:35px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background:#7491B2; }
QScrollBar::handle:horizontal { background:#3C4D69; border-radius:2px; min-width:35px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QDialog, QMessageBox { background:#0F192B; }
QTabWidget::pane { border:1px solid #2C3D58; border-radius:10px; background:#131F32; padding:12px; }
QTabBar::tab { color:#9FAFC8; padding:10px 20px; background:#111B2D; border-bottom:2px solid transparent; }
QTabBar::tab:selected { background:#1D2E45; color:#A3EFDD; border-bottom:2px solid #75CCB9; }
QTableWidget { background:#131F32; alternate-background-color:#19273C; gridline-color:#2A3B54; border:1px solid #344761; selection-background-color:#304E70; }
QTableWidget QLineEdit { padding:2px; }
QHeaderView::section { background:#20314A; color:#B3C4DB; padding:8px; border:0; border-right:1px solid #324762; }
QTableCornerButton::section { background:#20314A; border:0; }
QToolTip { color:#E0ECFB; background:#1A2941; border:1px solid #55708D; padding:10px; }
"""


def line_icon(kind: str, color: str = "#A8BCD5", size: int = 18) -> QIcon:
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(2)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24, size / 24)
    p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    if kind == "search":
        p.drawEllipse(QRectF(4, 4, 12, 12)); line(14, 14, 20, 20)
    elif kind == "refresh":
        p.drawArc(QRectF(5, 5, 14, 14), 40 * 16, 285 * 16)
        line(19, 4, 19, 10); line(19, 10, 13, 10)
    elif kind == "close":
        line(7, 7, 17, 17); line(17, 7, 7, 17)
    elif kind == "arrow":
        line(6, 18, 18, 6); line(10, 6, 18, 6); line(18, 6, 18, 14)
    elif kind == "pin":
        line(8, 4, 16, 4); line(9, 4, 9, 10); line(15, 4, 15, 10)
        line(9, 10, 6, 14); line(15, 10, 18, 14); line(6, 14, 18, 14); line(12, 14, 12, 21)
    elif kind == "settings":
        p.drawEllipse(QRectF(5, 5, 14, 14)); p.drawEllipse(QRectF(9, 9, 6, 6))
        for i in range(8):
            angle = i * math.pi / 4
            line(12 + math.cos(angle) * 7, 12 + math.sin(angle) * 7, 12 + math.cos(angle) * 10, 12 + math.sin(angle) * 10)
    elif kind == "papers":
        p.drawRoundedRect(QRectF(6, 3, 13, 16), 2, 2)
        line(9, 8, 16, 8); line(9, 12, 15, 12); line(3, 6, 3, 21); line(3, 21, 15, 21)
    elif kind == "news":
        path = QPainterPath(QPointF(3, 13))
        for point in [(7, 13), (10, 5), (14, 19), (17, 10), (21, 10)]:
            path.lineTo(*point)
        p.drawPath(path)
    elif kind == "social":
        line(4, 18, 10, 12); line(10, 12, 14, 14); line(14, 14, 21, 5)
        line(15, 5, 21, 5); line(21, 5, 21, 11)
    elif kind == "spark":
        path = QPainterPath(QPointF(12, 2))
        for point in [(15, 9), (22, 12), (15, 15), (12, 22), (9, 15), (2, 12), (9, 9)]:
            path.lineTo(*point)
        path.closeSubpath(); p.drawPath(path)
    p.end()
    return QIcon(pix)


def make_icon() -> QIcon:
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(4, 4, 60, 60)
    gradient.setColorAt(0, QColor("#BBF0E6"))
    gradient.setColorAt(1, QColor("#7C9DE8"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(2, 2, 60, 60, 17, 17)
    p.setPen(QPen(QColor("#102239"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(19, 20, 19, 44); p.drawLine(19, 20, 44, 44); p.drawLine(44, 20, 44, 44)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#E1FFF2"))
    p.drawEllipse(42, 11, 9, 9)
    p.end()
    return QIcon(pixmap)
