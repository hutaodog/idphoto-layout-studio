# -*- coding: utf-8 -*-
"""布局之间共用的积木：左侧竖向图标栏、可折叠分组、卡片外壳。

不用任何符号字形（微软雅黑没有 ✔ ⚙ ✕ 这些码位，会渲染成豆腐块），
图标栏一律用**中文短标签 + 自绘条状指示器**，可折叠分组用**自绘三角**。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from .. import style


class RailButton(QAbstractButton):
    """图标栏里的一格：小标签 + 选中时的左侧蓝色指示条。"""

    def __init__(self, text: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self._tip = tooltip or text
        self.setToolTip(self._tip)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(56, 52)

    def sizeHint(self) -> QSize:                            # noqa: N802
        return QSize(56, 52)

    def paintEvent(self, e):                               # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        checked = self.isChecked()
        hovered = self.underMouse()
        body = QRectF(4, 4, self.width() - 8, self.height() - 8)
        if checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(style.PRIMARY_SOFT))
            p.drawRoundedRect(body, 9, 9)
        elif hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#f0f2f6"))
            p.drawRoundedRect(body, 9, 9)
        if checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(style.PRIMARY))
            p.drawRoundedRect(QRectF(0, 14, 3, self.height() - 28), 2, 2)
        p.setPen(QColor(style.PRIMARY if checked else style.MUTED_STRONG))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(body, Qt.AlignCenter, self.text())


class IconRail(QWidget):
    """竖向图标栏：点击某项 -> currentChanged(index)。

    底部可以再挂一条（设置），用 add_bottom()。
    """

    currentChanged = Signal(int)

    def __init__(self, items, width: int = 64, parent=None):
        super().__init__(parent)
        self.setFixedWidth(width)
        self.setObjectName("iconRail")
        self.setStyleSheet("QWidget#iconRail{background:%s;border-top-left-radius:0px;}"
                           % style.CARD)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 10, 4, 10)
        v.setSpacing(4)
        self._buttons = []
        for i, (text, tip) in enumerate(items):
            b = RailButton(text, tip)
            b.clicked.connect(lambda _=False, idx=i: self.set_current(idx))
            v.addWidget(b, 0, Qt.AlignHCenter)
            self._buttons.append(b)
        v.addStretch(1)
        self._bottom = []
        if self._buttons:
            self._buttons[0].setChecked(True)

    def add_bottom(self, text: str, tip: str = "") -> RailButton:
        lay = self.layout()
        b = RailButton(text, tip)
        lay.addWidget(b, 0, Qt.AlignHCenter)
        self._bottom.append(b)
        return b

    def set_current(self, idx: int) -> None:
        for i, b in enumerate(self._buttons):
            b.setChecked(i == idx)
        self.currentChanged.emit(idx)

    def current_index(self) -> int:
        for i, b in enumerate(self._buttons):
            if b.isChecked():
                return i
        return 0


class Chevron(QLabel):
    """自绘的展开/收起三角（不用 ▸ ▾ 这类字形）。"""

    def __init__(self, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._expanded = expanded
        self.setFixedSize(14, 14)

    def set_expanded(self, v: bool) -> None:
        self._expanded = v
        self.update()

    def paintEvent(self, e):                               # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(style.MUTED_STRONG))
        w = self.width()
        if self._expanded:
            pts = [QPointF(2, 4.5), QPointF(w - 2, 4.5), QPointF(w / 2, 10.5)]
        else:
            pts = [QPointF(4.5, 2), QPointF(10.5, self.height() / 2), QPointF(4.5, 12)]
        p.drawPolygon(QPolygonF(pts))


class _SectionHeader(QWidget):
    """可折叠分组的标题行。

    注意：**不能用 QToolButton 当容器再往里塞布局** —— QToolButton 是自绘控件，
    塞进去的子控件不会被排布（实测表现是标题文字整个不见）。这里用普通 QWidget
    自己处理点击与 hover。
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self._hover = False

    def enterEvent(self, e):                               # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e):                               # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, e):                          # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def paintEvent(self, e):                               # noqa: N802
        if self._hover:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#f1f3f7"))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, 0, -1), 7, 7)


class CollapsibleSection(QWidget):
    """可折叠分组：一行标题（三角 + 名字 + 右侧值摘要）+ 内容。

    内容就是传进来的 QGroupBox（复用 MainWindow 的 _group_* 构造函数），
    折叠时把内容 hide()，标题行右侧显示摘要（例如「自动构图」）。
    """

    def __init__(self, title: str, content: QWidget, summary: str = "",
                 expanded: bool = True, parent=None):
        super().__init__(parent)
        self._title = title
        self.content = content
        self._expanded = expanded
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        self.header = _SectionHeader()
        h = QHBoxLayout(self.header)
        h.setContentsMargins(6, 0, 8, 0)
        h.setSpacing(6)
        self.chev = Chevron(expanded)
        h.addWidget(self.chev, 0, Qt.AlignVCenter)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight:600;font-size:12px;color:%s;" % style.MUTED_STRONG)
        h.addWidget(lbl, 0, Qt.AlignVCenter)
        h.addStretch(1)
        self.lbl_summary = QLabel(summary)
        self.lbl_summary.setStyleSheet("color:%s;font-size:11px;" % style.MUTED)
        h.addWidget(self.lbl_summary, 0, Qt.AlignVCenter)
        self.header.clicked.connect(self.toggle)
        v.addWidget(self.header)

        content.setParent(self)
        v.addWidget(content)
        content.setVisible(expanded)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, on: bool) -> None:
        self._expanded = on
        self.chev.set_expanded(on)
        self.content.setVisible(on)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_summary(self, text: str) -> None:
        self.lbl_summary.setText(text)


def card(widget: QWidget, title: str = "", tools: QWidget = None) -> QFrame:
    """把任意控件包进一张卡片（标题行 + 内容）。"""
    f = QFrame()
    f.setObjectName("dashCard")
    f.setStyleSheet("QFrame#dashCard{background:%s;border:1px solid %s;border-radius:12px;}"
                    % (style.CARD, style.BORDER))
    v = QVBoxLayout(f)
    v.setContentsMargins(12, 10, 12, 12)
    v.setSpacing(8)
    if title or tools is not None:
        h = QHBoxLayout()
        h.setSpacing(8)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight:600;font-size:12px;color:%s;" % style.MUTED_STRONG)
        h.addWidget(lbl)
        h.addStretch(1)
        if tools is not None:
            h.addWidget(tools)
        v.addLayout(h)
    v.addWidget(widget, 1)
    return f
