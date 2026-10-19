# -*- coding: utf-8 -*-
"""胶囊分段控件（参考图右上角那个「单个 / 排版」切换）。

自绘一个圆角胶囊：底是浅灰，选中项是一块白色滑块（带极淡投影），
点击左半/右半切换。**不含任何符号字形**（字体里没有的符号会变豆腐块），
全部用 QPainter 画。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF,
                            Qt, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import style

H = 36              # 胶囊高度（v1.5.3：用户反馈"太扁了"，从 30 加到 36）
PAD = 4             # 滑块与胶囊边的间距
ANIM_MS = 170       # 切换时滑块滑过去的时长


class SegmentedControl(QWidget):
    """两段（或更多段）胶囊切换：切换时白色滑块**滑过去**，不是直接跳。"""

    currentChanged = Signal(int)

    def __init__(self, items: List[str], current: int = 0, parent=None):
        super().__init__(parent)
        self._items = list(items)
        self._current = current
        self._pos = float(current)      # 滑块当前位置（可以停在两段之间 → 动画中）
        self._hover = -1
        self.setMouseTracking(True)
        self.setFixedHeight(H)
        self.setCursor(Qt.PointingHandCursor)
        w = 12
        for t in self._items:
            w += self._text_w(t) + 26
        self.setFixedWidth(w)
        self._anim = QPropertyAnimation(self, b"sliderPos", self)
        self._anim.setDuration(ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    # ------------------------------------------------------------------ 动画
    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, v: float) -> None:
        self._pos = float(v)
        self.update()

    sliderPos = Property(float, _get_pos, _set_pos)

    # ------------------------------------------------------------------ 数据
    def current(self) -> int:
        return self._current

    def set_current(self, i: int, animate: bool = True) -> None:
        if not (0 <= i < len(self._items)) or i == self._current:
            return
        self._current = i
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(i))
            self._anim.start()
        else:
            self._set_pos(float(i))
        self.currentChanged.emit(i)

    def _text_w(self, text: str) -> int:
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setWeight(QFont.DemiBold)
        return self.fontMetrics().horizontalAdvance(text) + 4

    def _seg_rect(self, i: int) -> QRectF:
        n = max(1, len(self._items))
        w = (self.width() - 2 * PAD) / n
        return QRectF(PAD + i * w, PAD, w, self.height() - 2 * PAD)

    def _index_at(self, x: int) -> int:
        n = max(1, len(self._items))
        w = (self.width() - 2 * PAD) / n
        i = int((x - PAD) // w)
        return max(0, min(n - 1, i))

    # ------------------------------------------------------------------ 事件
    def mousePressEvent(self, e):                          # noqa: N802
        if e.button() == Qt.LeftButton:
            self.set_current(self._index_at(int(e.position().x())))
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):                           # noqa: N802
        i = self._index_at(int(e.position().x()))
        if i != self._hover:
            self._hover = i
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):                               # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, e):                               # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2.0

        # 胶囊底
        p.setPen(QPen(QColor(style.BORDER_STRONG), 1))
        p.setBrush(QColor("#eceef2"))
        p.drawRoundedRect(r, rad, rad)

        # 选中滑块（位置带小数 → 动画时停在两段之间）
        sel = self._seg_rect(self._pos)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(12, 18, 32, 18))
        p.drawRoundedRect(sel.adjusted(0, 1.5, 0, 2.5), sel.height() / 2, sel.height() / 2)
        p.setPen(QPen(QColor(style.BORDER), 1))
        p.setBrush(QColor(style.CARD))
        p.drawRoundedRect(sel, sel.height() / 2, sel.height() / 2)

        # 文字
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        for i, t in enumerate(self._items):
            seg = self._seg_rect(i)
            if i == self._current:
                p.setPen(QColor(style.TEXT))
            elif i == self._hover:
                p.setPen(QColor(style.MUTED_STRONG))
            else:
                p.setPen(QColor(style.MUTED))
            p.drawText(seg, Qt.AlignCenter, t)
