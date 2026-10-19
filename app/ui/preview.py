# -*- coding: utf-8 -*-
"""图像工具：numpy <-> Qt 的转换，以及自适应缩放的预览画布。"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget


def bgr_to_qimage(img: np.ndarray) -> QImage:
    """OpenCV 的 BGR/BGRA ndarray -> QImage。"""
    if img is None:
        return QImage()
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        h, w = img.shape
        return QImage(img.data, w, h, w, QImage.Format_Grayscale8).copy()
    if img.shape[2] == 4:
        rgba = np.ascontiguousarray(img[:, :, [2, 1, 0, 3]])
        h, w, _ = rgba.shape
        return QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()


def bgr_to_pixmap(img: np.ndarray) -> QPixmap:
    return QPixmap.fromImage(bgr_to_qimage(img))


class PreviewCanvas(QWidget):
    """自适应缩放的预览区。

    - 拖动 = **平移视图**（看细节用；按住 Ctrl 拖动才是挪照片构图）
    - 滚轮 = **放大视图**（看细节用），**不改任何参数**
    - 双击 = 复位视图（缩放 + 平移归位；手动微调模式下同时复位构图）

    这两条都改过，别再改回去：
    1. v1.5.1 之前滚轮改的是"照片缩放"参数（等于替你调了图），用户要求改成放大查看细节；
    2. v1.5.3 之前拖动是"挪照片"（会改上下/左右位置参数），用户又反馈
       "怎么还是拖拽里面的图片呢？不应该是拖拽预览图左右那个查看" —— 所以拖动也改成平移视图。
       构图仍然可以调：精确走「构图微调」里的滑块，或者 Ctrl+拖动。
    """

    panned = Signal(float, float)      # dx, dy（归一化，相对当前显示尺寸）—— Ctrl+拖动才发
    zoomed = Signal(float)             # 历史遗留：滚轮不再发这个信号，参数不受影响
    doubleClicked = Signal()

    VIEW_ZOOM_MAX = 8.0                # 视图最多放大 8 倍
    PAN_KEEP = 0                       # 平移时图与外框之间不留缝（标准看图手感）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._caption = ""
        self._hint = "导入一张照片开始\n（也可以把图片直接拖进来）"
        self._guides: List[Tuple[float, float, float, float, str]] = []
        self._frame_ratio: Optional[float] = None   # 宽/高，用于画证件照取景框
        self._drag_origin: Optional[QPoint] = None
        self._drag_photo = False           # True = 这一拖是 Ctrl+拖动（挪照片构图）
        self._view_zoom = 1.0
        self._view_pan = QPointF(0.0, 0.0)
        self.setMinimumSize(360, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("拖动 = 平移视图　滚轮 = 放大视图　双击 = 复位视图\n"
                        "按住 Ctrl 拖动 = 挪照片构图（也可以直接用「构图微调」的滑块）")
        # 中性浅灰：衬托白色相纸，同时比卡片底色略深一点点，边界看得出来
        self._bg = QColor("#e9ebef")
        self.setStyleSheet("background:#e9ebef;border-radius:10px;")

    # ---------- 数据 ----------
    def set_image(self, img: Optional[np.ndarray], caption: str = "") -> None:
        self._pixmap = bgr_to_pixmap(img) if img is not None else None
        self._caption = caption
        self.update()

    def set_pixmap(self, pm: Optional[QPixmap], caption: str = "") -> None:
        self._pixmap = pm
        self._caption = caption
        self.update()

    def set_guides(self, guides: List[Tuple[float, float, float, float, str]]) -> None:
        """guides: [(x, y, w, h, label)] 全部是 0~1 归一化坐标。"""
        self._guides = guides or []
        self.update()

    def set_frame_ratio(self, ratio: Optional[float]) -> None:
        self._frame_ratio = ratio
        self.update()

    def set_hint(self, text: str) -> None:
        self._hint = text
        self.update()

    @property
    def has_image(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    # ---------- 绘制 ----------
    def _base_rect(self):
        """自适应铺满的基准矩形（不含视图缩放）。"""
        if not self.has_image:
            return None
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw <= 0 or ph <= 0:
            return None
        avail_w = max(1, self.width() - 24)
        avail_h = max(1, self.height() - 24)
        scale = min(avail_w / pw, avail_h / ph)
        w, h = int(pw * scale), int(ph * scale)
        return ((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def _target_rect(self):
        """基准矩形再套上视图缩放（以画布中心为基准，加上光标锚点带来的平移）。"""
        base = self._base_rect()
        if base is None:
            return None
        z = self._view_zoom
        if z == 1.0 and self._view_pan.isNull():
            return base
        x, y, w, h = base
        cx, cy = self.width() / 2.0, self.height() / 2.0
        x2 = cx + (x - cx) * z + self._view_pan.x()
        y2 = cy + (y - cy) * z + self._view_pan.y()
        return (int(x2), int(y2), int(w * z), int(h * z))

    # ---------- 视图缩放 / 平移 ----------
    def view_zoom(self) -> float:
        return self._view_zoom

    def view_pan(self):
        return QPointF(self._view_pan)

    def _clamp_pan(self, pan: QPointF) -> QPointF:
        """限制平移量：图比视口小就最多挪到贴边，比视口大就不许露出空档。"""
        base = self._base_rect()
        if base is None:
            return QPointF(0.0, 0.0)
        z = self._view_zoom
        w, h = base[2] * z, base[3] * z
        vw, vh = float(self.width()), float(self.height())

        def lim(size, view):
            if size <= view:
                return max(0.0, (view - size) / 2.0)
            return max(0.0, (size - view) / 2.0 + self.PAN_KEEP)

        lx, ly = lim(w, vw), lim(h, vh)
        return QPointF(max(-lx, min(lx, pan.x())), max(-ly, min(ly, pan.y())))

    def pan_view(self, dx: float, dy: float) -> None:
        """平移**视图**（不动照片参数）——拖动走这里。"""
        new = self._clamp_pan(QPointF(self._view_pan.x() + dx, self._view_pan.y() + dy))
        if new != self._view_pan:
            self._view_pan = new
            self.update()

    def reset_view(self) -> None:
        if self._view_zoom != 1.0 or not self._view_pan.isNull():
            self._view_zoom = 1.0
            self._view_pan = QPointF(0.0, 0.0)
            self.update()

    def zoom_view(self, steps: float, anchor: Optional[QPoint] = None) -> None:
        """放大/缩小**视图**（不改任何照片参数）。anchor 是光标位置，缩放时那里不动。"""
        if not self.has_image:
            return
        z0 = self._view_zoom
        z1 = max(1.0, min(self.VIEW_ZOOM_MAX, z0 * (1.18 ** steps)))
        if abs(z1 - z0) < 1e-6:
            return
        a = anchor or QPoint(self.width() // 2, self.height() // 2)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        k = z1 / z0
        # 让光标底下的内容在缩放前后停在原地：P' = (a-C) - (a-C-P)*k
        self._view_zoom = z1
        self._view_pan = self._clamp_pan(QPointF(
            (a.x() - cx) - (a.x() - cx - self._view_pan.x()) * k,
            (a.y() - cy) - (a.y() - cy - self._view_pan.y()) * k))
        if z1 <= 1.0:
            self._view_zoom = 1.0
            self._view_pan = QPointF(0.0, 0.0)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)
        rect = self._target_rect()
        if rect is None:
            p.setPen(QColor("#8b919c"))
            p.drawText(self.rect(), Qt.AlignCenter, self._hint)
            return

        x, y, w, h = rect
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(x, y, w, h, self._pixmap)

        # 证件照取景框（按规格宽高比）：中性深色虚线，比橙色克制
        if self._frame_ratio:
            fw = w
            fh = int(w / self._frame_ratio)
            if fh > h:
                fh = h
                fw = int(h * self._frame_ratio)
            fx = x + (w - fw) // 2
            fy = y + (h - fh) // 2
            p.setPen(QPen(QColor(28, 34, 46, 170), 1, Qt.DashLine))
            p.drawRect(fx, fy, fw, fh)

        # 参考框（人脸位置等）：细一点，标签做成小胶囊
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        metrics = p.fontMetrics()
        for (gx, gy, gw, gh, label) in self._guides:
            rx, ry = x + int(gx * w), y + int(gy * h)
            rw, rh = int(gw * w), int(gh * h)
            p.setPen(QPen(QColor(47, 111, 208, 230), 2))
            p.drawRect(rx, ry, rw, rh)
            if label:
                tw = metrics.horizontalAdvance(label) + 12
                th = metrics.height() + 5
                lx = min(rx, x + w - tw)
                ly = max(y + 2, ry - th - 3)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(47, 111, 208, 225))
                p.drawRoundedRect(lx, ly, tw, th, 4, 4)
                p.setBrush(Qt.NoBrush)
                p.setPen(QColor("#ffffff"))
                p.drawText(lx + 6, ly + th - 5, label)

        if self._caption:
            # 做成左上角的小胶囊：贴边画会被裁掉，压在照片上又难看
            tw = metrics.horizontalAdvance(self._caption) + 14
            th = metrics.height() + 6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 214))
            p.drawRoundedRect(8, 8, tw, th, 5, 5)
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor("#5c636e"))
            p.drawText(15, 8 + th - 6, self._caption)

        # 视图放大时右下角给个倍率角标，否则用户会以为是照片被改了
        if self._view_zoom > 1.01:
            text = "视图 ×%.1f　拖动看四周　双击复位" % self._view_zoom
            tw = metrics.horizontalAdvance(text) + 16
            th = metrics.height() + 8
            bx = self.width() - tw - 10
            by = self.height() - th - 10
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(28, 34, 46, 190))
            p.drawRoundedRect(bx, by, tw, th, 6, 6)
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor("#ffffff"))
            p.drawText(bx + 8, by + th - 7, text)

    # ---------- 交互 ----------
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton and self.has_image:
            self._drag_origin = e.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            self._drag_photo = bool(e.modifiers() & Qt.ControlModifier)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag_origin is None or not self.has_image:
            return
        pt = e.position().toPoint()
        dx = pt.x() - self._drag_origin.x()
        dy = pt.y() - self._drag_origin.y()
        self._drag_origin = pt
        if getattr(self, "_drag_photo", False):
            # Ctrl+拖动：保留"挪照片构图"这条老路（精确调整还是用「构图微调」的滑块）
            rect = self._target_rect()
            if not rect:
                return
            _, _, w, h = rect
            self.panned.emit(dx / max(1, w), dy / max(1, h))
            return
        # 默认：拖动 = 平移**视图**（看细节），一个参数都不改
        self.pan_view(dx, dy)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag_origin = None
        self._drag_photo = False
        self.unsetCursor()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self.reset_view()                # 视图缩放归位
        self.doubleClicked.emit()

    def wheelEvent(self, e):  # noqa: N802
        """滚轮 = 放大/缩小**视图**（看细节），不发参数、不改照片。

        用户反馈："为什么滚轮直接调整图片缩放？改成不调节缩放，是放大这个模板照片、
        放大查看细节用的。"
        """
        if not self.has_image:
            return
        e.accept()
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.zoom_view(steps, e.position().toPoint())
