# -*- coding: utf-8 -*-
"""参考图样式的白色卡片：一行「图标 + 标题 + 右侧摘要 + 折叠箭头」+ 内容。

外观对着用户给的那张参考图做的：
* 白底、1px 极浅描边、圆角 12px；
* 标题行 44px，左边一个小线性图标（自绘，不用字形），标题 13px 半粗；
* 右边可以显示一个灰色摘要（折叠时专门用来看"当前值"）；
* 点标题行整行折叠/展开，箭头自绘。

图标全部是 QPainter 画的短线/圆，**不依赖字体里的符号**（这个项目里字体缺字形会变豆腐块）。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import style

HEAD_H = 44          # 标题行高度
RADIUS = 12
PAD = 16             # 卡片左右内边距


def paint_icon(p: QPainter, name: str, r: QRectF, color: QColor) -> None:
    """画一个小线性图标（18×18 的方框里）。"""
    p.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    x, y, w, h = r.left(), r.top(), r.width(), r.height()
    cx, cy = x + w / 2.0, y + h / 2.0

    if name == "list":
        for i in range(3):
            yy = y + h * (0.25 + i * 0.25)
            p.drawLine(QPointF(x + w * 0.30, yy), QPointF(x + w * 0.92, yy))
            p.drawPoint(QPointF(x + w * 0.10, yy))
    elif name == "id":
        p.drawRoundedRect(QRectF(x + w * 0.06, y + h * 0.20, w * 0.88, h * 0.60), 2.5, 2.5)
        p.drawEllipse(QPointF(x + w * 0.33, cy - h * 0.02), w * 0.11, h * 0.11)
        p.drawLine(QPointF(x + w * 0.52, cy - h * 0.10), QPointF(x + w * 0.84, cy - h * 0.10))
        p.drawLine(QPointF(x + w * 0.52, cy + h * 0.10), QPointF(x + w * 0.78, cy + h * 0.10))
    elif name == "palette":
        p.drawEllipse(QPointF(cx, cy), w * 0.42, h * 0.42)
        for i in range(3):
            ang = -0.9 + i * 0.9
            p.drawPoint(QPointF(cx + w * 0.20 * __import__("math").cos(ang),
                                cy + h * 0.20 * __import__("math").sin(ang)))
    elif name == "sliders":
        for i, fy in enumerate((0.26, 0.50, 0.74)):
            yy = y + h * fy
            p.drawLine(QPointF(x + w * 0.08, yy), QPointF(x + w * 0.92, yy))
            kx = x + w * (0.34 if i != 1 else 0.64)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(kx, yy), w * 0.10, w * 0.10)
            p.setBrush(Qt.NoBrush)
    elif name == "grid":
        s = w * 0.34
        for i in range(2):
            for j in range(2):
                p.drawRoundedRect(QRectF(x + w * 0.14 + i * (s + w * 0.18),
                                         y + h * 0.14 + j * (s + h * 0.18), s, s), 2, 2)
    elif name == "printer":
        p.drawRoundedRect(QRectF(x + w * 0.16, y + h * 0.38, w * 0.68, h * 0.40), 2.5, 2.5)
        p.drawRect(QRectF(x + w * 0.28, y + h * 0.16, w * 0.44, h * 0.24))
        p.drawRect(QRectF(x + w * 0.28, y + h * 0.62, w * 0.44, h * 0.26))
    elif name == "log":
        for i in range(3):
            yy = y + h * (0.28 + i * 0.22)
            p.drawLine(QPointF(x + w * 0.10, yy), QPointF(x + w * (0.55 + i * 0.12), yy))


class _Header(QWidget):
    clicked = Signal()

    def __init__(self, title: str, icon: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(HEAD_H)
        self._icon = icon
        self._hover = False
        self._expanded = True
        h = QHBoxLayout(self)
        h.setContentsMargins(PAD, 0, PAD, 0)
        h.setSpacing(9)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "font-size:13px;font-weight:600;color:%s;background:transparent;" % style.TEXT)
        h.addWidget(self.lbl_title)

        self.lbl_sub = QLabel("")
        self.lbl_sub.setStyleSheet(
            "font-size:12px;color:%s;background:transparent;" % style.MUTED)
        h.addWidget(self.lbl_sub)
        h.addStretch(1)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(
            "font-size:12px;color:%s;background:transparent;" % style.MUTED)
        h.addWidget(self.lbl_summary)

    def set_expanded(self, on: bool) -> None:
        self._expanded = on
        self.update()

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
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#f6f7f9"))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(6, 4, -6, -4), 8, 8)

        # 图标：浅色圆角底 + 线性图标
        box = QRectF(PAD, (self.height() - 18) / 2.0, 18, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(style.PRIMARY_SOFT))
        p.drawRoundedRect(box.adjusted(-5, -5, 5, 5), 7, 7)
        # 图标要画在标题左边，所以这里把标题行整体右移：用 layout 的 spacing 实现，
        # 这里只负责把图标画在预留的位置上。
        paint_icon(p, self._icon, box, QColor(style.PRIMARY))

        # 折叠箭头
        ax = self.width() - PAD - 12
        ay = self.height() / 2.0
        p.setPen(QPen(QColor(style.MUTED), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self._expanded:
            p.drawPolyline([QPointF(ax, ay - 2.5), QPointF(ax + 5, ay + 3),
                            QPointF(ax + 10, ay - 2.5)])
        else:
            p.drawPolyline([QPointF(ax, ay + 3), QPointF(ax + 5, ay - 2.5),
                            QPointF(ax + 10, ay + 3)])


class SectionCard(QWidget):
    """白卡片 + 可折叠标题行。内容就是传进来的控件。"""

    def __init__(self, title: str, content: QWidget, icon: str = "sliders",
                 sub: str = "", summary: str = "", expanded: bool = True,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("sectionCard")
        # 普通 QWidget 默认不画样式表里的背景/描边，必须显式打开这个属性
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#sectionCard{background:%s;border:1px solid %s;border-radius:%dpx;}"
            % (style.CARD, style.BORDER, RADIUS))
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.header = _Header(title, icon)
        self.header.lbl_sub.setText(sub)
        self.header.lbl_summary.setText(summary)
        # 标题左边给图标留位置（图标在 _Header.paintEvent 里画）；右边给箭头留位置。
        # 这两个数别乱加：右边的摘要文字一旦被挤就会**硬裁**（"0 张"显示成"0"），
        # 不会自动省略号，很难看。
        self.header.layout().setContentsMargins(PAD + 26, 0, PAD + 20, 0)
        self.header.clicked.connect(self.toggle)
        v.addWidget(self.header)

        self.content = content
        content.setParent(self)
        wrap = QWidget()
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(PAD, 0, PAD, PAD)
        wv.setSpacing(0)
        wv.addWidget(content)
        self._wrap = wrap
        v.addWidget(wrap)
        wrap.setVisible(expanded)
        self.header.set_expanded(expanded)
        self._expanded = expanded

    # ------------------------------------------------------------------ 状态
    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, on: bool) -> None:
        self._expanded = on
        self._wrap.setVisible(on)
        self.header.set_expanded(on)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_summary(self, text: str) -> None:
        self.header.lbl_summary.setText(text)

    def set_sub(self, text: str) -> None:
        self.header.lbl_sub.setText(text)
