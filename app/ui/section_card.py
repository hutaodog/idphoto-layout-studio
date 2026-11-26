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

import time

from PySide6.QtCore import (QAbstractAnimation, QEvent, QPointF, QSignalBlocker,
                            QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import style
from .corners import apply_surface, continuous_path
from .motion import REVEAL_CLOSE, REVEAL_OPEN, spring_state

HEAD_H = 44          # 标题行高度
RADIUS = style.PANEL_RADIUS
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
        p.drawPath(continuous_path(QRectF(x + w * 0.06, y + h * 0.20, w * 0.88, h * 0.60), 2.5))
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
                p.drawPath(continuous_path(QRectF(x + w * 0.14 + i * (s + w * 0.18),
                                                 y + h * 0.14 + j * (s + h * 0.18), s, s), 2))
    elif name == "printer":
        p.drawPath(continuous_path(QRectF(x + w * 0.16, y + h * 0.38, w * 0.68, h * 0.40), 2.5))
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
        self._reveal = 1.0
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
        self.set_reveal(1.0 if on else 0.0)

    def set_reveal(self, value: float) -> None:
        if value != self._reveal:
            self._reveal = value
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
            p.drawPath(continuous_path(QRectF(self.rect()).adjusted(6, 4, -6, -4), 8))

        # 图标：浅色圆角底 + 线性图标
        box = QRectF(PAD, (self.height() - 18) / 2.0, 18, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(style.PRIMARY_SOFT))
        p.drawPath(continuous_path(box.adjusted(-5, -5, 5, 5), 7))
        # 图标要画在标题左边，所以这里把标题行整体右移：用 layout 的 spacing 实现，
        # 这里只负责把图标画在预留的位置上。
        paint_icon(p, self._icon, box, QColor(style.PRIMARY))

        # 折叠箭头
        ax = self.width() - PAD - 12
        ay = self.height() / 2.0
        p.setPen(QPen(QColor(style.MUTED), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.translate(ax + 5, ay)
        p.rotate(180.0 * (1.0 - self._reveal))
        p.drawPolyline([QPointF(-5, -2.5), QPointF(0, 3), QPointF(5, -2.5)])


class _Reveal(QWidget):
    """只改变可见高度，内容始终按自然尺寸排版，防止回弹挤压文字和控件。"""

    metricsChanged = Signal()

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body = QWidget(self)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(PAD, 0, PAD, PAD)
        layout.setSpacing(0)
        layout.addWidget(content)
        self._metrics_pending = False
        self.body.installEventFilter(self)

    def natural_height(self) -> int:
        layout = self.body.layout()
        height = layout.heightForWidth(max(1, self.width()))
        return max(0, height if height >= 0 else layout.sizeHint().height())

    def expanded_size_hint(self) -> QSize:
        return QSize(self.body.minimumSizeHint().width(), self.natural_height())

    def set_body_height(self, height: int) -> None:
        """只在内容或宽度变化时排版，动画帧只裁切这个固定尺寸的正文。"""
        self.body.setGeometry(0, 0, self.width(), height)

    def set_reveal_height(self, value: float) -> None:
        height = max(0, round(value))
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def _notify_metrics(self) -> None:
        self._metrics_pending = False
        self.metricsChanged.emit()

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.LayoutRequest and not self._metrics_pending:
            self._metrics_pending = True
            QTimer.singleShot(0, self._notify_metrics)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.metricsChanged.emit()


class SectionCard(QWidget):
    """白卡片 + 可折叠标题行。内容就是传进来的控件。"""

    heightAboutToChange = Signal()

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
        apply_surface(self, style.CARD, style.BORDER, RADIUS)
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
        self._wrap = _Reveal(content, self)
        v.addWidget(self._wrap)
        self._expanded = expanded
        self._open_height = self._wrap.natural_height()
        self._height = float(self._open_height if expanded else 0)
        self._velocity = 0.0
        self._start_height = self._height
        self._start_velocity = 0.0
        self._target_height = self._height
        self._started_at = time.perf_counter()
        self._damping = REVEAL_OPEN.damping
        self._frequency = REVEAL_OPEN.frequency
        # Qt's shared animation clock drives all cards. Values are only ticks: the
        # spring below retains both position and speed when the user reverses it.
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(1000)
        self._animation.valueChanged.connect(self._tick_transition)
        self._animation.finished.connect(self._finish_transition)
        self._wrap.metricsChanged.connect(self._sync_content_height)
        self.set_expanded(expanded, animate=False)

    # ------------------------------------------------------------------ 状态
    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def _apply_height(self, value: float) -> None:
        self._height = max(0.0, float(value))
        if round(self._height) != self._wrap.minimumHeight():
            # A scroll host must reserve its current viewport before Qt shrinks
            # the content minimum and clamps the scrollbar in the next layout.
            self.heightAboutToChange.emit()
        self._wrap.set_reveal_height(self._height)
        self.header.set_reveal(min(1.0, self._height / max(1, self._open_height)))

    def _spring_state(self, elapsed: float) -> tuple[float, float]:
        height, speed = spring_state(
            self._start_height, self._start_velocity, self._target_height, elapsed,
            frequency=self._frequency, damping=self._damping)
        if height <= 0.0:
            return 0.0, max(0.0, speed)
        return height, speed

    def _tick_transition(self, _value=None) -> None:
        if self._animation.state() != QAbstractAnimation.Running:
            return
        self._height, self._velocity = self._spring_state(time.perf_counter() - self._started_at)
        self._apply_height(self._height)
        if (abs(self._height - self._target_height) < 0.25
                and abs(self._velocity) < 4.0):
            self._finish_transition()

    def _finish_transition(self) -> None:
        self._animation.stop()
        self._velocity = self._start_velocity = 0.0
        self._start_height = self._target_height = float(self._open_height if self._expanded else 0)
        self._apply_height(self._target_height)
        self._wrap.setVisible(self._expanded)
        self.header.set_expanded(self._expanded)

    def _start_transition(self, target: float) -> None:
        # Use the last rendered position/speed, including for a click that lands
        # between frames. Sampling the old trajectory here would jump pixels.
        self._start_height = self._height
        self._start_velocity = self._velocity
        self._target_height = float(target)
        profile = REVEAL_OPEN if self._expanded else REVEAL_CLOSE
        self._damping = profile.damping
        self._frequency = profile.frequency
        self._started_at = time.perf_counter()
        # Qt can emit old interpolated values while resetting its clock. Block
        # setup and the synchronous start tick so neither becomes a frame.
        with QSignalBlocker(self._animation):
            self._animation.stop()
            self._animation.setCurrentTime(0)
            self._animation.start()
        # A hidden body receives its current width on show. Its synchronous
        # metrics signal must see a running transition so it retargets rather
        # than settling the card at full height during the initiating click.
        self._wrap.show()

    def _sync_content_height(self) -> None:
        height = self._wrap.natural_height()
        self._wrap.set_body_height(height)
        if height == self._open_height:
            return
        running = self._animation.state() == QAbstractAnimation.Running
        self._open_height = height
        if self._expanded and running:
            self._start_transition(height)
        elif self._expanded:
            self._finish_transition()

    def set_expanded(self, on: bool, animate: bool = True) -> None:
        on = bool(on)
        running = self._animation.state() == QAbstractAnimation.Running
        if on == self._expanded and running and animate:
            return
        if not on:
            focused = QApplication.focusWidget()
            if focused is not None and self._wrap.isAncestorOf(focused):
                # Hiding a focused editor otherwise transfers focus to a later
                # card; QScrollArea then scrolls that new editor into view.
                focused.clearFocus()
        self._expanded = on
        self._open_height = self._wrap.natural_height()
        self._wrap.set_body_height(self._open_height)
        target = self._open_height if on else 0
        if (not animate or not self.isVisible() or not self.isEnabled()
                or (abs(self._height - target) < 0.25 and abs(self._velocity) < 4.0)):
            self._finish_transition()
            return
        self._start_transition(target)

    def expanded_size_hint(self) -> QSize:
        """折叠时也可量完整内容宽度，不切换状态或打断正在运行的动画。"""
        hint = self._wrap.expanded_size_hint()
        return QSize(max(hint.width(), self.header.minimumSizeHint().width()),
                     HEAD_H + hint.height())

    def hideEvent(self, event):  # noqa: N802
        self._finish_transition()
        super().hideEvent(event)

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.EnabledChange and not self.isEnabled():
            self._finish_transition()
        super().changeEvent(event)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_summary(self, text: str) -> None:
        self.header.lbl_summary.setText(text)

    def set_sub(self, text: str) -> None:
        self.header.lbl_sub.setText(text)
