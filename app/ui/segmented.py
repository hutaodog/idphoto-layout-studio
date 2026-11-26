# -*- coding: utf-8 -*-
"""胶囊分段控件（参考图右上角那个「单个 / 排版」切换）。

自绘一个圆角胶囊：底是浅灰，选中项是一块白色滑块（带极淡投影），
点击左半/右半切换。**不含任何符号字形**（字体里没有的符号会变豆腐块），
全部用 QPainter 画。
"""
from __future__ import annotations

import time
from typing import List

from PySide6.QtCore import (Property, QAbstractAnimation, QEvent, QRectF,
                            QSignalBlocker, Qt, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import style
from .corners import capsule_path
from .motion import SELECTION, spring_state

H = 36              # 胶囊高度（v1.5.3：用户反馈"太扁了"，从 30 加到 36）
PAD = 4             # 滑块与胶囊边的间距


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
        self._velocity = 0.0
        self._start_pos = self._pos
        self._start_velocity = 0.0
        self._target_pos = self._pos
        self._started_at = time.perf_counter()
        # Keep Qt's shared animation clock and its inspectable running state;
        # the values are ticks, while the spring retains momentum on retarget.
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1000)
        self._anim.valueChanged.connect(self._tick_transition)
        self._anim.finished.connect(self._finish_transition)

    # ------------------------------------------------------------------ 动画
    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, v: float) -> None:
        self._pos = max(0.0, min(float(max(0, len(self._items) - 1)), float(v)))
        self.update()

    sliderPos = Property(float, _get_pos, _set_pos)

    def _spring_state(self, elapsed: float) -> tuple[float, float]:
        position, velocity = spring_state(
            self._start_pos, self._start_velocity, self._target_pos, elapsed,
            frequency=SELECTION.frequency, damping=SELECTION.damping)
        # Numerical guards keep the selected capsule inside its shell, even if
        # a caller set sliderPos directly before starting a transition.
        end = float(max(0, len(self._items) - 1))
        if position <= 0.0:
            return 0.0, max(0.0, velocity)
        if position >= end:
            return end, min(0.0, velocity)
        return position, velocity

    def _tick_transition(self, _value=None) -> None:
        if self._anim.state() != QAbstractAnimation.Running:
            return
        position, self._velocity = self._spring_state(time.perf_counter() - self._started_at)
        self._set_pos(position)
        segment_width = self._seg_rect(0).width()
        if (abs(self._pos - self._target_pos) * segment_width < 0.05
                and abs(self._velocity) * segment_width < 0.5):
            self._finish_transition()

    def _finish_transition(self) -> None:
        self._anim.stop()
        self._velocity = self._start_velocity = 0.0
        self._start_pos = self._target_pos = float(self._current)
        self._set_pos(self._target_pos)

    def _start_transition(self) -> None:
        # Retarget the last rendered state. Sampling the old curve here would
        # move the capsule synchronously between animation frames on a click.
        self._start_pos = self._pos
        self._start_velocity = self._velocity
        self._target_pos = float(self._current)
        self._started_at = time.perf_counter()
        # Resetting Qt's clock at its old currentTime can emit stale values.
        # Starting is blocked too, so setup cannot produce a visible frame.
        with QSignalBlocker(self._anim):
            self._anim.stop()
            self._anim.setCurrentTime(0)
            self._anim.start()

    # ------------------------------------------------------------------ 数据
    def current(self) -> int:
        return self._current

    def set_current(self, i: int, animate: bool = True) -> None:
        if not (0 <= i < len(self._items)):
            return
        changed = i != self._current
        if not changed and animate:
            return
        self._current = i
        if (animate and self.isVisible() and self.isEnabled()
                and (self._pos != float(i) or self._velocity != 0.0)):
            self._start_transition()
        else:
            # An explicit snap also cancels an animation to this same index.
            self._finish_transition()
        if changed:
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

    def hideEvent(self, event):                            # noqa: N802
        self._finish_transition()
        super().hideEvent(event)

    def changeEvent(self, event):                          # noqa: N802
        if event.type() == QEvent.EnabledChange and not self.isEnabled():
            self._finish_transition()
        super().changeEvent(event)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, e):                               # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 胶囊底
        p.setPen(QPen(QColor(style.BORDER_STRONG), 1))
        p.setBrush(QColor("#eceef2"))
        p.drawPath(capsule_path(r))

        # 选中滑块（位置带小数 → 动画时停在两段之间）
        sel = self._seg_rect(self._pos)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(12, 18, 32, 18))
        p.drawPath(capsule_path(sel.adjusted(0, 1.5, 0, 2.5)))
        p.setPen(QPen(QColor(style.BORDER), 1))
        p.setBrush(QColor(style.CARD))
        p.drawPath(capsule_path(sel))

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
