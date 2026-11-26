# -*- coding: utf-8 -*-
"""工作台（按用户给的参考图重做）：左边一列参数卡片，右边一整块大预览。

对着参考图来的：
* 左列是若干**白色卡片**，每张一行「图标 + 标题 + 摘要 + 折叠箭头」，点标题行折叠；
  最下面一张是**日志**（跟着状态栏消息走）。
* 右边是**一整块大预览卡**，右上角一个**胶囊切换钮**在「证件照预览 / 排版预览」之间切。
* 配色沿用项目原有令牌（白卡片 #ffffff / 浅底 #f3f4f7 / 细描边 #e7e9ee），
  和参考图是同一路的浅色干净风格。

功能全部复用 MainWindow 上的面板构造函数，所以和别的界面完全等价。
"""
from __future__ import annotations

import os
import time
from typing import List

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import style
from ..corners import apply_surface, continuous_path
from ..panel_stage import strip_group
from ..section_card import SectionCard
from ..segmented import SegmentedControl

NAME = "工作台"
DESC = "左列参数卡片 + 右侧大预览，右上角胶囊切换预览模式"

LEFT_W = 344          # 左列宽度下限
LEFT_W_MAX = 440      # 左列宽度上限（再宽就把预览挤没了）

_IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def _is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMG_EXT


class DropArea(QFrame):
    """能接住拖进来的图片的预览区。

    拖进来时描一圈虚线并给个浅色底，松手就导入 —— 用户要求"直接把图片拖进来就能导入"。
    """

    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._hot = False

    def dragEnterEvent(self, e):                           # noqa: N802
        md = e.mimeData()
        if md.hasUrls() and any(_is_image(u.toLocalFile()) for u in md.urls()):
            e.acceptProposedAction()
            self._hot = True
            self.update()
            return
        super().dragEnterEvent(e)

    def dragLeaveEvent(self, e):                           # noqa: N802
        self._hot = False
        self.update()
        super().dragLeaveEvent(e)

    def dragMoveEvent(self, e):                            # noqa: N802
        # **必须有**：Qt 的默认实现直接 ignore，drag 过程中被 ignore 之后
        # 松手不会产生 drop 事件 —— 现象就是"拖到窗口上没有任何反应"。
        md = e.mimeData()
        if md.hasUrls() and any(_is_image(u.toLocalFile()) for u in md.urls()):
            e.acceptProposedAction()
            return
        super().dragMoveEvent(e)

    def dropEvent(self, e):                                # noqa: N802
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if _is_image(u.toLocalFile())]
        self._hot = False
        self.update()
        if paths:
            e.acceptProposedAction()
            self.filesDropped.emit(paths)
            return
        super().dropEvent(e)

    def paintEvent(self, e):                               # noqa: N802
        super().paintEvent(e)
        if not self._hot:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect().adjusted(3, 3, -3, -3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(47, 111, 208, 22))
        p.drawPath(continuous_path(QRectF(r), 12))
        pen = QPen(QColor(style.PRIMARY), 2, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(continuous_path(QRectF(r), 12))
        p.setPen(QColor(style.PRIMARY))
        f = p.font()
        f.setPointSizeF(11.5)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, "松手即可导入照片")


def build(win) -> QWidget:
    root = QWidget()
    h = QHBoxLayout(root)
    h.setContentsMargins(12, 10, 12, 10)
    h.setSpacing(12)
    h.addWidget(_left_column(win))
    h.addWidget(_preview_area(win), 1)
    win.split = None
    return root


# ====================================================================== 左列
class _CardScrollArea(QScrollArea):
    """Keep a visible header anchored while card heights change above/below it.

    Shrinking a bottom-scrolled widget normally clamps its scroll value on
    every layout. The existing bottom stretch instead retains only the space
    needed by the current viewport. Scrolling up releases it; expanding cards
    absorbs it. It is never added to the previous retained height.
    """

    def __init__(self, cards):
        super().__init__()
        self._cards = cards
        self._anchor = None
        self._adjusting_scroll = False
        self.verticalScrollBar().valueChanged.connect(self._scroll_changed)
        for card in cards:
            card.heightAboutToChange.connect(self._before_height_change)

    def _retain_viewport(self, value):
        inner = self.widget()
        # An explicit QWidget minimum overrides QScrollArea's size-hint
        # minimum, so never let this floor squeeze the cards' natural layout.
        natural = inner.layout().minimumSize().height()
        inner.setMinimumHeight(max(natural, self.viewport().height() + value) if value > 0 else 0)

    def _before_height_change(self):
        inner = self.widget()
        if inner is None or not inner.isVisible():
            return
        value = self.verticalScrollBar().value()
        if self._anchor is None:
            # A card above the viewport can also be collapsing. Follow the
            # first reachable header, rather than leaving the entire view blank.
            headers = [c.header for c in self._cards if c.isVisible()]
            header = next((h for h in headers if h.mapTo(inner, QPoint()).y() + h.height() > value), None)
            if header is not None:
                self._anchor = (header, header.mapTo(inner, QPoint()).y() - value)
        self._retain_viewport(value)

    def _scroll_changed(self, value):
        if self._adjusting_scroll:
            return
        self._anchor = None
        inner = self.widget()
        if inner is not None and inner.minimumHeight():
            natural = inner.layout().minimumSize().height()
            if natural >= self.viewport().height() + value:
                inner.setMinimumHeight(0)
            else:
                self._retain_viewport(value)

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.widget() and event.type() == QEvent.LayoutRequest:
            anchor, self._anchor = self._anchor, None
            self._adjusting_scroll = True
            try:
                # Grow before activating: a spring can cross the old floor by
                # just one pixel. Measuring its header in a squeezed layout
                # would otherwise turn that temporary squeeze into scroll drift.
                natural = watched.layout().minimumSize().height()
                watched.setMinimumHeight(max(watched.minimumHeight(), natural))
                watched.layout().activate()
                result = super().eventFilter(watched, event)
                if anchor is not None:
                    header, top = anchor
                    value = max(0, header.mapTo(watched, QPoint()).y() - top)
                    self._retain_viewport(value)
                    self.verticalScrollBar().setValue(value)
                # Remove redundant retention as soon as opening content fills it.
                if watched.layout().minimumSize().height() >= watched.minimumHeight():
                    watched.setMinimumHeight(0)
                return result
            finally:
                self._adjusting_scroll = False
        return super().eventFilter(watched, event)


def _left_column(win) -> QWidget:
    inner = QWidget()
    v = QVBoxLayout(inner)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(10)

    # 顺序按用户在截图上标的号：
    #   ① 证件照规格 ② 背景底色 ③ 构图微调 ④ 相纸与排版（v1.5.4 反馈：相纸与排版提到第 4 位）
    # 其余（输出设置 / 日志）跟在后面。
    # 「相纸与排版」默认也展开（用户 v1.5.6 反馈："把这四个默认设为展开状态"）。
    # v1.6.6：**去掉「照片列表」**（用户："去掉照片列表那个功能，拖新的一张就把前一张覆盖了"）。
    cards = [
        SectionCard("证件照规格", strip_group(win._group_spec()), icon="id",
                    summary="一寸"),
        SectionCard("背景底色", strip_group(win._group_bg()), icon="palette",
                    summary="白色"),
        SectionCard("构图微调", strip_group(win._group_adjust()), icon="sliders",
                    summary="自动构图"),
        SectionCard("相纸与排版", strip_group(win._group_layout()), icon="grid",
                    summary="6寸 · 12 张", expanded=True),
        SectionCard("输出设置", strip_group(win._group_output()),
                    icon="printer", summary="300 dpi", expanded=False),
    ]
    # 摘要不再是写死的：MainWindow._refresh_card_summaries() 会按当前状态刷新它们
    # 注意：没有 "photos" 了（v1.6.6 去掉了照片列表）
    win.card_summaries = {
        "spec": cards[0], "bg": cards[1], "adjust": cards[2],
        "layout": cards[3], "output": cards[4],
    }
    for c in cards:
        v.addWidget(c)

    log = _LogView(win)
    log_card = SectionCard("日志", log, icon="log", expanded=False)
    v.addWidget(log_card)
    v.addStretch(1)

    scroll = _CardScrollArea(cards + [log_card])
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    # 用户要求"把左列那个滚动条去掉"：条不显示，但**滚轮照样能滚**（ScrollBarAlwaysOff
    # 只是不画滑块，不影响 wheel 事件）。
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

    def refit() -> None:
        """按全部内容的自然宽度量列宽，折叠或回弹中也无需切换卡片状态。"""
        need = max(c.expanded_size_hint().width() for c in cards) + 16
        scroll.setFixedWidth(max(LEFT_W, min(LEFT_W_MAX, need)))

    # 展开只改变高度；列宽已按全部正文量过，点击时无需再次遍历布局。
    refit()
    win.left_refit = refit          # 便于测试和窗口尺寸变化时重算
    return scroll


def _photos(win) -> QWidget:
    """（已停用）以前这里的「照片列表」卡片。

    v1.6.6 起工作台不再有照片列表：一张照片进来就顶掉上一张，`MainWindow.add_photos()`
    用的是"覆盖"语义。函数留着是因为别的实验布局还在用它。
    """
    panel = win._build_left_panel()
    panel.setMaximumWidth(16777215)
    panel.setMinimumWidth(0)
    if getattr(win, "lbl_photos_title", None) is not None:
        win.lbl_photos_title.hide()
    if getattr(win, "lst_photos", None) is not None:
        win.lst_photos.setMinimumHeight(120)
    return panel


class _LogView(QPlainTextEdit):
    """跟着状态栏消息走的日志（参考图左下角那块）。"""

    MAX_LINES = 300

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFixedHeight(148)
        self.setStyleSheet(
            "QPlainTextEdit{background:#fafbfc;border:1px solid %s;border-radius:8px;"
            "color:%s;font-size:11px;padding:6px;}" % (style.BORDER, style.MUTED_STRONG))
        apply_surface(self, "#fafbfc", style.BORDER, 8)
        self._append("就绪")
        try:
            win.status.messageChanged.connect(self._on_status)
        except Exception:                                  # noqa: BLE001
            pass

    def _on_status(self, text: str) -> None:
        if text:
            self._append(text)

    def _append(self, text: str) -> None:
        self.appendPlainText("%s  %s" % (time.strftime("%H:%M:%S"), text))
        doc = self.document()
        if doc.blockCount() > self.MAX_LINES:
            cur = self.textCursor()
            cur.movePosition(cur.Start)
            cur.select(cur.BlockUnderCursor)
            cur.removeSelectedText()
            cur.deleteChar()
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ====================================================================== 右列
def _preview_area(win) -> QWidget:
    holder = win._build_center_panel()          # 建出 canvas / 两个单选 / 信息标签
    inner = holder.findChild(QWidget, "previewCard")

    canvas = win.canvas
    info = win.lbl_preview_info
    radios = [win.rb_photo, win.rb_layout]
    if inner is not None:
        for w in (canvas, info) + tuple(radios):
            w.setParent(None)
        holder.setParent(None)
        holder.deleteLater()
    else:
        canvas.setParent(None)
        info.setParent(None)

    card = DropArea()
    card.setObjectName("previewCard")
    card.setAttribute(Qt.WA_StyledBackground, True)
    card.setStyleSheet(
        "QFrame#previewCard{background:%s;border:1px solid %s;border-radius:%dpx;}"
        % (style.CARD, style.BORDER, style.PANEL_RADIUS))
    apply_surface(card, style.CARD, style.BORDER, style.PANEL_RADIUS)
    card.filesDropped.connect(win.add_photos)      # 拖进来就导入
    v = QVBoxLayout(card)
    v.setContentsMargins(16, 12, 16, 16)
    v.setSpacing(10)

    head = QHBoxLayout()
    head.setSpacing(12)
    info.setStyleSheet("font-size:12px;color:%s;" % style.MUTED)
    info.setParent(card)
    head.addWidget(info)
    head.addStretch(1)

    # 右上角胶囊：切换「证件照预览 / 排版预览」
    seg = SegmentedControl(["证件照预览", "排版预览"], current=0)
    seg.setParent(card)
    head.addWidget(seg)
    v.addLayout(head)
    v.addWidget(canvas, 1)

    # 真正的状态源还是那两个单选按钮（业务逻辑连的是它们），只是藏起来让胶囊当脸面。
    for rb in radios:
        rb.setParent(card)
        rb.hide()

    seg.currentChanged.connect(
        lambda i: (win.rb_photo if i == 0 else win.rb_layout).setChecked(True))
    def sync_preview_toggle(on):
        index = 0 if on else 1
        # A radio echo of the same click must not snap the moving capsule.
        if seg.current() != index:
            seg.set_current(index, animate=False)

    win.rb_photo.toggled.connect(sync_preview_toggle)
    win.preview_toggle = seg          # 方便外部/测试取用
    return card
