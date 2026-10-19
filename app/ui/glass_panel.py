# -*- coding: utf-8 -*-
"""玻璃卡片：像小窗口一样能拖动、能从四角和四边拉伸。

设计要点（对着用户的诉求来的）：
- **iOS 那种玻璃高光**：竖向渐变（上亮下暗）+ 1px 亮描边 + 顶部一条更亮的高光线
  + 外侧两层极淡的投影，让卡片"浮"在毛玻璃窗口上；
- **能像窗口一样拉伸**：四角 + 四边共 8 个方向，鼠标移到边缘会变光标，拖拽即改尺寸；
- **按住标题栏拖动**整张卡片；点一下卡片会置顶（raise）；
- 卡片自己有最小尺寸，不会被拖成一条线；
- 内容控件原样塞进来（复用 MainWindow 的面板构造函数），所以功能不受影响。

不用 Qt 的 QGraphicsView 之类的重家伙：卡片就是普通的 QWidget，绝对定位在
父容器上，手写 move/resize —— 这样最简单，也最好排版。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QVBoxLayout, QWidget)

from . import style

RADIUS = 14          # 卡片圆角
EDGE = 7             # 边缘感应宽度（用来拉伸）
TITLE_H = 32         # 标题行高度（也是拖动区）

GLASS_TOP = (255, 255, 255, 222)      # 玻璃渐变：上
GLASS_MID = (255, 255, 255, 196)
GLASS_BOT = (255, 255, 255, 172)
GLASS_BORDER = (255, 255, 255, 150)
GLASS_HILITE = (255, 255, 255, 225)


class GlassPanel(QWidget):
    """一张可拖动、可缩放的玻璃卡片。"""

    # 用户真的拖动/拉伸过这张卡片（**不是**程序排版时改的几何）。
    # 舞台靠它判断"要不要再自动排版"，不能用几何比较——那样任何窗口缩放
    # 都会被误判成"用户挪过"，于是窗口一小就再也不重新排版、卡片叠在一起。
    userChanged = Signal()

    def __init__(self, title: str, content: QWidget, parent=None,
                 min_w: int = 300, min_h: int = 180, subtitle: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._min_w = min_w
        self._min_h = min_h
        self._drag_off: QPoint | None = None
        self._resize_edges = None
        self._press_geo: QRect | None = None
        self._press_pos: QPoint | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 8, 14, 14)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "font-weight:600;font-size:12px;color:%s;background:transparent;"
            % style.MUTED_STRONG)
        head.addWidget(self.lbl_title)
        head.addStretch(1)
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setStyleSheet("font-size:11px;color:%s;background:transparent;"
                                   % style.MUTED)
        head.addWidget(self.lbl_sub)
        v.addLayout(head)

        self.content = content
        content.setParent(self)
        v.addWidget(content, 1)

    # ---------------- 玻璃外观 ----------------
    def paintEvent(self, e):                               # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        # 外投影：两层极淡，营造"浮起"
        p.setPen(Qt.NoPen)
        for grow, alpha in ((5, 16), (2, 26)):
            p.setBrush(QColor(12, 18, 32, alpha))
            p.drawRoundedRect(r.adjusted(-grow, -grow + 1, grow, grow + 1),
                              RADIUS + grow, RADIUS + grow)

        # 玻璃本体：竖向渐变
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, QColor(*GLASS_TOP))
        g.setColorAt(0.55, QColor(*GLASS_MID))
        g.setColorAt(1.0, QColor(*GLASS_BOT))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor(*GLASS_BORDER), 1))
        p.drawRoundedRect(r, RADIUS, RADIUS)

        # 顶部高光：贴着上边缘的一条亮线（iOS 玻璃的标志），两端随圆角淡出
        p.setPen(QPen(QColor(*GLASS_HILITE), 1))
        y = r.top() + 1.0
        p.drawLine(QRectF(r.left() + RADIUS * 0.75, y,
                          r.width() - RADIUS * 1.5, 0).topLeft(),
                   QRectF(r.left() + RADIUS * 0.75, y,
                          r.width() - RADIUS * 1.5, 0).topRight())

    # ---------------- 拖动 / 缩放 ----------------
    def _zone(self, pos: QPoint):
        """返回 Qt.Edges（拉伸方向）或 None。"""
        m = EDGE
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        left, right = x <= m, x >= w - m
        top, bottom = y <= m, y >= h - m
        edges = Qt.Edges()
        if left:
            edges |= Qt.LeftEdge
        if right:
            edges |= Qt.RightEdge
        if top:
            edges |= Qt.TopEdge
        if bottom:
            edges |= Qt.BottomEdge
        return edges if edges else None

    _CURSORS = {}

    def _cursor_for(self, edges):
        if not edges:
            return Qt.ArrowCursor
        # ⚠ 不要写 int(edges)：PySide6 的 Qt.Edges 是标志位枚举，
        # int(Qt.Edges) 会抛 `TypeError: int() argument must be a string, ... not 'Edge'`
        # —— 之前就是这么写的，鼠标一碰卡片边缘就弹"出错了"对话框。
        # 枚举本身可哈希，直接拿来当 dict 的 key。
        table = {
            Qt.LeftEdge | Qt.TopEdge: Qt.SizeFDiagCursor,
            Qt.RightEdge | Qt.BottomEdge: Qt.SizeFDiagCursor,
            Qt.RightEdge | Qt.TopEdge: Qt.SizeBDiagCursor,
            Qt.LeftEdge | Qt.BottomEdge: Qt.SizeBDiagCursor,
            Qt.LeftEdge: Qt.SizeHorCursor,
            Qt.RightEdge: Qt.SizeHorCursor,
            Qt.TopEdge: Qt.SizeVerCursor,
            Qt.BottomEdge: Qt.SizeVerCursor,
        }
        return table.get(edges, Qt.ArrowCursor)

    def mouseMoveEvent(self, e):                           # noqa: N802
        if self._drag_off is not None:
            pt = e.globalPosition().toPoint()
            self.move(pt - self._drag_off)
            e.accept()
            return
        if self._resize_edges is not None and self._press_geo is not None:
            self._do_resize(e.globalPosition().toPoint())
            e.accept()
            return
        self.setCursor(self._cursor_for(self._zone(e.position().toPoint())))
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):                          # noqa: N802
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        self.raise_()
        pos = e.position().toPoint()
        edges = self._zone(pos)
        if edges:
            self._resize_edges = edges
            self._press_geo = self.geometry()
            self._press_pos = e.globalPosition().toPoint()
            e.accept()
            return
        if pos.y() <= TITLE_H + 8:          # 标题带：整张卡片跟着走
            self._drag_off = e.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):                        # noqa: N802
        acted = (self._drag_off is not None) or (self._resize_edges is not None)
        self._drag_off = None
        self._resize_edges = None
        self._press_geo = None
        self._press_pos = None
        self.unsetCursor()
        super().mouseReleaseEvent(e)
        if acted:
            self.userChanged.emit()

    def _do_resize(self, global_pt: QPoint) -> None:
        d = global_pt - self._press_pos
        g = QRect(self._press_geo)
        edges = self._resize_edges
        if edges & Qt.LeftEdge:
            g.setLeft(min(g.left() + d.x(), g.right() - self._min_w))
        if edges & Qt.RightEdge:
            g.setRight(max(g.right() + d.x(), g.left() + self._min_w))
        if edges & Qt.TopEdge:
            g.setTop(min(g.top() + d.y(), g.bottom() - self._min_h))
        if edges & Qt.BottomEdge:
            g.setBottom(max(g.bottom() + d.y(), g.top() + self._min_h))
        self.setGeometry(g)

    @property
    def min_w(self) -> int:
        """这张卡片"内容还想看得见"所需的宽度（防重叠时用它判断能不能再缩）。"""
        return self._min_w

    @property
    def min_h(self) -> int:
        return self._min_h

    def fit_into(self, rect: QRect) -> None:
        """按给定矩形摆放，并**把最小尺寸压到不超过这个矩形**。

        卡片各自有最小尺寸（滑块/列表不能无限压），但窗口变小时格子会比分卡片
        的最小尺寸还小 —— 这时候如果还硬撑最小尺寸，卡片就会撑出自己的格子、
        和邻居叠在一起（实测窗口 1180×760 时「构图微调」压在「背景底色」上）。
        所以这里把最小尺寸按格子压下来，宁可内容挤一点，也绝不允许重叠。
        """
        self.setMinimumSize(min(self._min_w, rect.width()),
                            min(self._min_h, rect.height()))
        self.setGeometry(rect)

    def minimumSizeHint(self):                             # noqa: N802
        from PySide6.QtCore import QSize
        return QSize(self._min_w, self._min_h)

    def set_bounds(self, area: QRect) -> None:
        """把卡片约束在舞台范围内（拖动/缩放/窗口变小后调用）。"""
        g = self.geometry()
        w = max(self._min_w, min(g.width(), area.width()))
        h = max(self._min_h, min(g.height(), area.height()))
        x = max(area.left(), min(g.x(), area.right() - w + 1))
        y = max(area.top(), min(g.y(), area.bottom() - h + 1))
        self.setGeometry(x, y, w, h)
