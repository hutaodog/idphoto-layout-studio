# -*- coding: utf-8 -*-
"""独立的进度小窗：**首次启动下载模型** 和 **更新版本** 共用同一个外观。

用户的要求（v1.6.3）：
* 便携版第一次双击时，别先进主界面再报"模型缺失"，而要先弹一个小框下载模型，
  框里要有「正在下载模型」、总量、速度 MB/s、还剩多少、进度条，下完**自动打开**程序；
* 更新时点完按钮就把主界面关了，另起一个同样的小框显示「更新了什么 + 下载进度 + 速度」，
  下载完显示「正在合并」，合并完显示「更新完成」，然后自动拉起新版本、小框自己消失。

所以这个类只做"长相"和状态切换，具体干活由外部线程驱动：
`set_status()` / `set_progress()` / `set_success()` / `set_error()`。

外观上跟主程序一套：白卡片 + 12px 圆角 + 1px 浅灰描边 + 主题蓝进度条 + 微软雅黑，
窗口无边框（但可拖动、Esc 不关闭、右上角不放关闭按钮 —— 下载中途关掉只会让人更困惑，
需要时的「取消」是显式的一个 ghost 按钮）。
"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ..core import weights as wcore
from . import style

RADIUS = 14
PAD = 26


def _round_tile(p: QPainter, size: int, color: QColor, radius: int = 10) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)


def _check_pixmap(size: int = 34) -> "QPixmap":
    """自绘对勾（字体里没有 ✔，本项目一律画）。"""
    from PySide6.QtGui import QPixmap

    pm = QPixmap(size, size)
    pm.setDevicePixelRatio(1.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    _round_tile(p, size, QColor(style.PRIMARY_SOFT))
    pen = QPen(QColor(style.PRIMARY))
    pen.setWidthF(max(2.0, size * 0.11))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(size * 0.28, size * 0.53)
    path.lineTo(size * 0.44, size * 0.68)
    path.lineTo(size * 0.73, size * 0.35)
    p.drawPath(path)
    p.end()
    return pm


def _warn_pixmap(size: int = 34) -> "QPixmap":
    """感叹号（错误态角标）。"""
    from PySide6.QtGui import QPixmap

    pm = QPixmap(size, size)
    pm.setDevicePixelRatio(1.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    _round_tile(p, size, QColor("#fdecea"))
    pen = QPen(QColor(style.DANGER))
    pen.setWidthF(max(2.0, size * 0.11))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(int(size * 0.5), int(size * 0.27), int(size * 0.5), int(size * 0.57))
    p.setBrush(QColor(style.DANGER))
    p.setPen(Qt.NoPen)
    r = size * 0.055
    p.drawEllipse(QRectF(size * 0.5 - r, size * 0.70 - r, r * 2, r * 2))
    p.end()
    return pm


class ProgressBar(QWidget):
    """自绘进度条（不用 QProgressBar：它那套 chunk 样式在圆角卡片里很丑）。

    `indeterminate=True` 时画一条来回跑的光带（连接中/准备中）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0                    # 0.0 ~ 1.0
        self._indeterminate = False
        self._phase = 0.0
        self.setFixedHeight(8)
        self.setMinimumWidth(200)

    def set_value(self, frac: float) -> None:
        self._value = max(0.0, min(1.0, float(frac)))
        self._indeterminate = False
        self.update()

    def set_indeterminate(self, on: bool) -> None:
        self._indeterminate = bool(on)
        self.update()

    def tick(self, step: float = 0.06) -> None:
        self._phase = (self._phase + step) % 1.0
        if self._indeterminate:
            self.update()

    def paintEvent(self, e):                                  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2.0
        # 轨道
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(style.BORDER))
        p.drawRoundedRect(r, radius, radius)
        # 已下载部分（或来回跑的光带）
        p.setBrush(QColor(style.PRIMARY))
        if self._indeterminate:
            span = r.width() * 0.30
            x = -span + (r.width() + span) * self._phase
            band = QRectF(max(0.0, x), 0.0, min(span, r.width()), r.height())
            path = QPainterPath()
            path.addRoundedRect(band, radius, radius)
            p.setClipRect(r)
            p.drawPath(path)
        elif self._value > 0:
            fill = QRectF(r.left(), r.top(), max(r.height(), r.width() * self._value),
                          r.height())
            path = QPainterPath()
            path.addRoundedRect(fill, radius, radius)
            p.drawPath(path)
        p.end()


class TaskWindow(QWidget):
    """无边框的进度卡片。"""

    cancel_requested = Signal()

    def __init__(self, title: str, subtitle: str = "", total: int = 0,
                 parent=None, width: int = 520, cancellable: bool = False):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(title)
        self.setFixedWidth(width)
        self._total = total
        self._done = 0
        self._meter = wcore.SpeedMeter()
        self._drag: Optional[QPoint] = None
        self._finished = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame(self)
        self.card.setObjectName("taskCard")
        outer.addWidget(self.card)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(PAD, PAD - 2, PAD, PAD - 4)
        v.setSpacing(10)

        # 标题行：小图标块 + 标题
        head = QHBoxLayout()
        head.setSpacing(12)
        self.badge = QLabel("")
        self.badge.setFixedSize(34, 34)
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setStyleSheet(
            "background:%s;border-radius:10px;color:%s;font-size:16px;font-weight:600;"
            % (style.PRIMARY_SOFT, style.PRIMARY))
        head.addWidget(self.badge, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.lbl_title = QLabel(title)
        f = self.lbl_title.font()
        f.setPointSizeF(f.pointSizeF() + 3.0)
        f.setBold(True)
        self.lbl_title.setFont(f)
        self.lbl_title.setStyleSheet("color:%s;" % style.TEXT)
        col.addWidget(self.lbl_title)
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setStyleSheet("color:%s;font-size:12px;" % style.MUTED_STRONG)
        self.lbl_sub.setVisible(bool(subtitle))
        col.addWidget(self.lbl_sub)
        head.addLayout(col, 1)
        v.addLayout(head)

        v.addSpacing(6)
        self.bar = ProgressBar(self.card)
        self.bar.set_indeterminate(True)
        v.addWidget(self.bar)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_status = QLabel("正在准备…")
        self.lbl_status.setStyleSheet("color:%s;font-size:12px;" % style.MUTED_STRONG)
        row.addWidget(self.lbl_status, 1)
        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet("color:%s;font-size:12px;" % style.MUTED)
        row.addWidget(self.lbl_stats, 0, Qt.AlignRight)
        v.addLayout(row)

        # 说明 / 更新内容
        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setVisible(False)
        self.lbl_note.setStyleSheet(
            "background:#fafbfc;border:1px solid %s;border-radius:8px;color:%s;"
            "font-size:12px;padding:8px 10px;" % (style.BORDER, style.MUTED_STRONG))
        v.addWidget(self.lbl_note)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("ghost")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_cancel.setVisible(bool(cancellable))
        btns.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("关闭")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self.close)
        self.btn_ok.setVisible(False)
        btns.addWidget(self.btn_ok)
        v.addLayout(btns)

        self.setStyleSheet(
            style.STYLESHEET +
            "QWidget#taskCard{background:%s;border:1px solid %s;border-radius:%dpx;}"
            % (style.CARD, style.BORDER_STRONG, RADIUS))

        # 光标：整窗可拖动
        self.setCursor(Qt.ArrowCursor)
        self._center()

    # ---------------------------------------------------------------- 位置
    def _center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        self.adjustSize()
        self.move(avail.center().x() - self.width() // 2,
                  avail.center().y() - self.height() // 2)

    def move_to(self, x: int, y: int) -> None:
        """更新交接时让新窗口出现在**同一个位置**，看起来是一个窗口没动。"""
        self.move(int(x), int(y))

    def bring_to_front(self) -> None:
        """把窗口拉到最前面。

        为什么要这么折腾：更新/引导窗口是由**后台进程**（或被隐藏的主窗口）拉起来的，
        Windows 的"前台锁"不允许它抢焦点，于是窗口会乖乖开在浏览器后面 ——
        用户只看到"程序关了、然后没反应"。这里用
        「先 HWND_TOPMOST 再 HWND_NOTOPMOST」的老办法强制提到最前，
        再用 SetForegroundWindow 拿焦点（配合父进程的 AllowSetForegroundWindow）。
        """
        self.show()
        self.raise_()
        self.activateWindow()
        if os.name != "nt":
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0040
            HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32.SetForegroundWindow(hwnd)
        except Exception:                                  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- 状态
    def set_title(self, text: str) -> None:
        self.lbl_title.setText(text)

    def set_badge(self, text: str) -> None:
        self.badge.setText(text)

    def set_note(self, text: str) -> None:
        self.lbl_note.setText(text)
        self.lbl_note.setVisible(bool(text))
        self._fit_wrap(self.lbl_note)
        self.adjustSize()

    def _fit_wrap(self, label: QLabel) -> None:
        """让自动换行的 QLabel 拿到**足够的高度**。

        QLabel + wordWrap 在"窗口固定宽度、高度自适应"的布局里会算错高度，
        文字会被裁掉一半（第一次渲染就踩到了：更新说明只显示了 1.5 行）。
        这里按实际可用宽度自己算一次。
        """
        label.setMinimumHeight(0)
        width = max(120, self.width() - 2 * PAD - 6)
        try:
            h = label.heightForWidth(width)
        except Exception:                                  # noqa: BLE001
            h = 0
        if h > 0:
            label.setMinimumHeight(h)
        else:                                              # 兜底：按字数估
            fm = label.fontMetrics()
            lines = max(1, int(len(label.text()) / max(10, width // fm.averageCharWidth())))
            label.setMinimumHeight(fm.lineSpacing() * lines + 4)

    def set_status(self, text: str, indeterminate: bool = False) -> None:
        self.lbl_status.setText(text)
        self.bar.set_indeterminate(indeterminate)

    def set_progress(self, done: int, total: int = 0, with_speed: bool = True) -> None:
        """更新进度条 + 右侧「已下/总量 · 速度 · 剩余」。"""
        self._done = int(done)
        if total > 0:
            self._total = int(total)
        self.bar.set_indeterminate(False)
        if self._total > 0:
            self.bar.set_value(self._done / float(self._total))
        if with_speed:
            speed, eta = self._meter.push(self._done, self._total)
            self.lbl_stats.setText(wcore.progress_text(self._done, self._total, speed, eta))
        else:
            self.lbl_stats.setText(wcore.progress_text(self._done, self._total))

    def set_stats_text(self, text: str) -> None:
        self.lbl_stats.setText(text)

    def set_success(self, status: str = "完成", detail: str = "") -> None:
        """完成态：进度条走满、按钮换成「关闭」、隐藏取消，角标换成自绘对勾。"""
        self._finished = True
        self.bar.set_indeterminate(False)
        self.bar.set_value(1.0)
        self.lbl_status.setText(status)
        self.lbl_status.setStyleSheet("color:%s;font-size:12px;font-weight:600;"
                                      % style.PRIMARY)
        if detail:
            self.lbl_stats.setText(detail)
        self.btn_cancel.setVisible(False)
        self.btn_ok.setVisible(True)
        self.badge.setText("")
        self.badge.setStyleSheet("background:transparent;")
        self.badge.setPixmap(_check_pixmap(34))

    def set_error(self, status: str, detail: str = "") -> None:
        self._finished = True
        self.bar.set_indeterminate(False)
        self.lbl_status.setText(status)
        self.lbl_status.setStyleSheet("color:%s;font-size:12px;font-weight:600;"
                                      % style.DANGER)
        if detail:
            self.lbl_note.setText(detail)
            self.lbl_note.setVisible(True)
            self._fit_wrap(self.lbl_note)
        self.btn_cancel.setVisible(False)
        self.btn_ok.setVisible(True)
        self.badge.setPixmap(_warn_pixmap(34))
        self.badge.setStyleSheet("background:transparent;")
        self.adjustSize()

    # ---------------------------------------------------------------- 交互
    def _on_cancel(self) -> None:
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText("正在取消…")
        self.cancel_requested.emit()

    def closeEvent(self, e):                                  # noqa: N802
        if not self._finished:
            # 下载/合并中途关窗口没有意义，直接忽略（取消请按「取消」）
            e.ignore()
            return
        super().closeEvent(e)

    def mousePressEvent(self, e):                             # noqa: N802
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):                              # noqa: N802
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):                           # noqa: N802
        self._drag = None
        super().mouseReleaseEvent(e)

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, e):                                  # noqa: N802
        """画一层很淡的外发光，让卡片从桌面上"浮"起来（不起透明像素点击穿透的坑）。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        for i, alpha in enumerate((10, 14, 20)):
            pen = QPen(QColor(24, 32, 48, alpha))
            pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            off = i + 1
            p.drawRoundedRect(rect.adjusted(-off, -off + 2, off, off + 2),
                              RADIUS + off, RADIUS + off)
        p.end()
