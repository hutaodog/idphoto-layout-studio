# -*- coding: utf-8 -*-
"""窗口外壳：自绘无边框圆角窗口 + 自绘标题栏。

为什么要自己画：设计稿是**无边框大圆角窗口 + 自绘标题栏**（左侧 logo/名字，
右侧圆形窗口按钮）。Qt 的常规做法是：

    setWindowFlags(Qt.FramelessWindowHint)
    setAttribute(Qt.WA_TranslucentBackground)      # 才能画出真圆角
    自己 paintEvent 画圆角矩形（顺带画一圈柔和外阴影）

窗口拖动用 `QWindow.startSystemMove()`、边缘缩放用 `startSystemResize()`
（Qt6 才有）。这两个 API 交给系统处理，比"记录鼠标位移自己 move()"可靠得多，
也自动带上系统的贴边吸附、最大化还原等行为。

**保底退路**：设环境变量 `IDPHOTO_FRAME=native` 就不套这层外壳，回到系统边框。
万一某台机器上无边框窗口表现异常（缩放/吸附不灵），用户还有一条退路。
"""
from __future__ import annotations

import ctypes
import os
from typing import Optional

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizeGrip,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import style

RADIUS = 12          # 窗口圆角（DWM 给圆角窗口的半径就在 8~12px 这档，画得跟它一致）
MARGIN = 10          # 外圈留给阴影/缩放的宽度（这圈属于 Frame 自己，鼠标事件能收到）
EDGE = 7             # 感应用的边缘宽度
MENUBAR_H = 28       # 标题栏里菜单栏的固定高度（让它和标题文字居中对齐，见 attach_menubar）

# ---------------------------------------------------------------- 原生缩放热区
# WM_NCHITTEST 的返回值（Windows SDK 里的 HT* 常量）
WM_NCHITTEST = 0x0084
HT_CLIENT = 1
HT_LEFT, HT_RIGHT, HT_TOP, HT_BOTTOM = 10, 11, 12, 15
HT_TOPLEFT, HT_TOPRIGHT, HT_BOTTOMLEFT, HT_BOTTOMRIGHT = 13, 14, 16, 17

EDGE_HIT = 6         # 边缘多宽算缩放热区（系统原生窗口一般 4~8px）

# 窗口能不能拖边缘改大小 —— **默认关掉**（用户 v1.5.6 拍板："改成窗口默认不可随意拉拽
# 调整窗口大小"；给了三选一，他选的是"完全固定"）。
# 经过：v1.5.3 用户说"无法随意拉动窗口大小"→ 做了原生缩放热区；用了两轮之后又要求固定，
# 因为 6px 的热区太容易误触（在窗口边上拖东西/拖标题栏会一下变成拉大小）。
# 改回 True 就能恢复缩放能力，别把下面那段判断删掉。
ALLOW_EDGE_RESIZE = False

try:                                                   # 非 Windows 上就别导入了
    import ctypes.wintypes as _wintypes
except Exception:                                      # noqa: BLE001
    _wintypes = None


def _msg_of(message):
    """把 PySide6 传给 nativeEvent 的 MSG 指针变成 MSG 结构。"""
    if _wintypes is None:
        return None
    try:
        addr = message if isinstance(message, int) else int(message)
        return ctypes.cast(addr, ctypes.POINTER(_wintypes.MSG)).contents
    except Exception:                                  # noqa: BLE001
        return None


def native_hit_test(window: QWidget, message, zone: int = EDGE_HIT) -> Optional[int]:
    """无边框窗口的**原生**边缘缩放：拦 WM_NCHITTEST，靠边就返回 HTLEFT/HTTOPLEFT…

    不在边上返回 None（让 Qt 自己按像素 alpha 判定，别把"点击穿透"那条逻辑顶掉）。

    为什么非做不可（用户反馈"无法随意拉动窗口大小"）：
    玻璃模式下 `Frame.margin` 只有 2px，窗口里其余部分全被内容控件盖住 ——
    Frame 自己**只能收到最外 2px 的鼠标事件**，那圈热区细得根本抓不住。
    交给系统处理还白得缩放光标、贴边吸附、最大化还原等行为，
    比"自绘热区 + startSystemResize"稳得多。
    """
    if _wintypes is None or window is None or not ALLOW_EDGE_RESIZE:
        return None
    if window.isMaximized() or window.isFullScreen():
        return None                                    # 最大化时不该能拖边框
    msg = _msg_of(message)
    if msg is None or msg.message != WM_NCHITTEST:
        return None
    try:
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        rc = _wintypes.RECT()
        user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rc))
        w, h = rc.right - rc.left, rc.bottom - rc.top
        if w <= 0 or h <= 0:
            # 离屏/尚未真正建窗口时 GetWindowRect 拿不到东西（测试就是这么跑的）：
            # 退回 Qt 的几何。真实显示时前者才是"物理像素"，高 DPI 下必须优先用它。
            g = window.frameGeometry()
            rc.left, rc.top, w, h = g.x(), g.y(), g.width(), g.height()
        sx = ctypes.c_short(msg.lParam & 0xFFFF).value
        sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        x, y = sx - rc.left, sy - rc.top
        if not (0 <= x < w and 0 <= y < h):
            return None
        left, right = x < zone, x >= w - zone
        top, bottom = y < zone, y >= h - zone
        if left and top:
            return HT_TOPLEFT
        if right and top:
            return HT_TOPRIGHT
        if left and bottom:
            return HT_BOTTOMLEFT
        if right and bottom:
            return HT_BOTTOMRIGHT
        if left:
            return HT_LEFT
        if right:
            return HT_RIGHT
        if top:
            return HT_TOP
        if bottom:
            return HT_BOTTOM
    except Exception:                                  # noqa: BLE001
        return None
    return None


def native_frame_forced() -> bool:
    """环境变量要求用系统边框时返回 True。"""
    return os.environ.get("IDPHOTO_FRAME", "").strip().lower() in ("native", "1", "system")


def app_icon() -> QIcon:
    """应用图标（打包后走 _MEIPASS，和 resources 的查找方式一致）。"""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "app", "resources", "icon.ico")
    else:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "resources", "icon.ico")
    return QIcon(p) if os.path.exists(p) else QIcon()


class WindowButton(QPushButton):
    """标题栏右侧的圆形小按钮（最小化 / 最大化 / 关闭）。"""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip({"min": "最小化", "max": "最大化", "close": "关闭"}.get(kind, ""))
        danger = kind == "close"
        self.setStyleSheet(
            "QPushButton{border:none;border-radius:15px;background:transparent;"
            "color:%s;font-size:13px;}"
            "QPushButton:hover{background:%s;color:%s;}"
            % (style.MUTED_STRONG,
               "#e03b3b" if danger else style.PRIMARY_SOFT,
               "#ffffff" if danger else style.PRIMARY))
        self.setText({"min": "\u2013", "max": "\u25a1", "close": "\u2715"}.get(kind, ""))
        # 这几个字形在微软雅黑里没有（会渲染成豆腐块），统一改用矢量绘制
        self.setText("")

    def paintEvent(self, e):                               # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        hovered = self.underMouse()
        col = QColor("#ffffff") if (hovered and self.kind == "close") else \
            QColor(style.TEXT if hovered and self.kind != "close" else style.MUTED_STRONG)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        if self.kind == "close":
            p.setPen(QColor(col))
            p.drawLine(w // 2 - 4, h // 2 - 4, w // 2 + 4, h // 2 + 4)
            p.drawLine(w // 2 + 4, h // 2 - 4, w // 2 - 4, h // 2 + 4)
        elif self.kind == "max":
            p.setPen(QColor(col))
            p.drawRect(w // 2 - 4, h // 2 - 4, 8, 8)
        else:
            p.setPen(QColor(col))
            p.drawLine(w // 2 - 5, h // 2 + 3, w // 2 + 5, h // 2 + 3)


class TitleBar(QWidget):
    """自绘标题栏：图标 + 名字 + 版本 + 菜单栏 + 右侧圆形按钮。

    按住空白处拖动窗口（交给 startSystemMove），双击最大化/还原。
    """

    HEIGHT = 44

    def __init__(self, window: QWidget, title: str, version: str = "", parent=None):
        super().__init__(parent)
        self._win = window
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("titleBar")
        self.setMouseTracking(True)

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 10, 0)
        h.setSpacing(8)

        self.icon = QLabel()
        ic = app_icon()
        if not ic.isNull():
            self.icon.setPixmap(ic.pixmap(QSize(22, 22)))
            self.icon.setFixedSize(24, 24)
            h.addWidget(self.icon)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("font-weight:600;font-size:13px;")
        h.addWidget(self.lbl_title)

        if version:
            self.lbl_ver = QLabel("v%s" % version)
            self.lbl_ver.setStyleSheet("color:%s;font-size:11px;padding-bottom:1px;"
                                       % style.MUTED)
            h.addWidget(self.lbl_ver)

        h.addSpacing(10)
        self.menu_host = QWidget()
        self._menu_layout = QHBoxLayout(self.menu_host)
        self._menu_layout.setContentsMargins(0, 0, 0, 0)
        self._menu_layout.setSpacing(0)
        h.addWidget(self.menu_host)

        h.addStretch(1)
        self.custom_host = QWidget()
        self._custom_layout = QHBoxLayout(self.custom_host)
        self._custom_layout.setContentsMargins(0, 0, 0, 0)
        self._custom_layout.setSpacing(6)
        h.addWidget(self.custom_host)

        self.btn_min = WindowButton("min")
        self.btn_max = WindowButton("max")
        self.btn_close = WindowButton("close")
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(self.toggle_max)
        self.btn_close.clicked.connect(window.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            h.addWidget(b)

        self.setStyleSheet(
            "QWidget#titleBar{background:transparent;}"
            "QMenuBar{background:transparent;border:none;}"
        )

    # ---- 菜单栏挂进来（放标题栏左侧，和设计稿一致）----
    def attach_menubar(self, menubar: QWidget) -> None:
        """把菜单栏嵌进标题栏，并且让它和标题文字**在同一条基线上**。

        踩过的坑（用户截图圈出来："这几个文字位置不太对，都没有对齐"）：
        QMenuBar 的默认 `padding: 2px 6px` + 布局把它拉满整条 44px 高，
        菜单文字是**贴着顶**画的 —— 实测「文件 / 帮助」的文字中心在 y≈16.5，
        而标题「证件照排版助手」和版本号在 y≈24，差了 7~8px，一眼就看出歪。
        → 这里把菜单栏钉成固定高度（由布局垂直居中），并去掉它自己的上下 padding，
        实测三者文字中心落在同一行（误差 ≤1px）。
        """
        menubar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        menubar.setFixedHeight(MENUBAR_H)
        # 往上/往下各留一点，让菜单文字和标题文字落在同一条基线上（实测：标题在 y≈24，
        # 菜单窗口居中后文字在 y≈22.5，这里补 2px 正好齐平）
        self._menu_layout.setContentsMargins(0, 2, 0, 0)
        menubar.setStyleSheet(
            "QMenuBar{background:transparent;border:none;padding:0px;}"
            "QMenuBar::item{background:transparent;padding:5px 10px;border-radius:6px;}"
            "QMenuBar::item:selected{background:%s;color:%s;}"
            % (style.PRIMARY_SOFT, style.PRIMARY))
        self._menu_layout.addWidget(menubar)

    def add_action_widget(self, w: QWidget) -> None:
        self._custom_layout.addWidget(w)

    def toggle_max(self) -> None:
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    # ---- 拖动 / 双击最大化 ----
    def mousePressEvent(self, e):                          # noqa: N802
        if e.button() == Qt.LeftButton:
            handle = self._win.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):                    # noqa: N802
        if e.button() == Qt.LeftButton:
            self.toggle_max()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)


class Frame(QWidget):
    """窗口主体：负责外投影/描边和四周边缘的系统缩放。

    `glass=True` 时**不刷不透明底色** —— 窗口已经是 WA_TranslucentBackground，
    不画底色的地方就是真透明，DWM 的毛玻璃（acrylic）才会透出来。
    只补一层极淡的白雾 + 1px 亮描边，让边界看得出来。
    """

    BG = style.BG

    def __init__(self, window: QWidget, parent=None, glass: bool = True,
                 backdrop: bool = False):
        super().__init__(parent)
        self._win = window
        self.glass = glass
        self.backdrop = backdrop       # True = 系统亚克力（DWM 自己画模糊与圆角）
        # 毛玻璃模式下窗口本身已经被 SetWindowRgn 裁成圆角（见 acrylic.apply_round_region），
        # 外投影根本露不到窗口外面，所以留白收到 2px，让描边贴着窗口边。
        self.margin = 2 if glass else MARGIN
        self.setMouseTracking(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.margin, self.margin, self.margin, self.margin)
        outer.setSpacing(0)
        self.inner = QWidget()
        self.inner.setObjectName("frameInner")
        if glass:
            self.inner.setStyleSheet("QWidget#frameInner{background:transparent;}")
        outer.addWidget(self.inner)

    def paintEvent(self, e):                               # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = self.margin
        r = QRectF(self.rect()).adjusted(m - 1, m - 1, -m + 1, -m + 1)
        if self.backdrop:
            # 系统亚克力模式：DWM 负责模糊和圆角，这里**什么都不画**。
            # 一旦画了底色，就会把那层模糊整个盖住（"灰不拉几"就是这么来的）。
            return
        if self.glass:
            # ⚠ 这一层"几乎看不见的白雾"**不能去掉**，alpha 必须 > 0：
            # 分层窗口（WA_TranslucentBackground）的鼠标命中是**按像素 alpha 判定**的，
            # alpha=0 的像素会被 Windows 当成"这里没东西"，点击直接**穿透到后面的窗口**
            # （用户实测"能透过软件界面点到后面的东西"）。顺带它也是那圈"玻璃板"的观感来源。
            p.setBrush(QColor(255, 255, 255, 12))
            p.setPen(Qt.NoPen)
            p.drawRect(self.rect())
            # 圆角描边（圆角由 SetWindowRgn 在系统层裁好，这里只描边）
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(255, 255, 255, 150))
        else:
            for i, a in ((7, 14), (4, 22), (2, 30)):
                p.setBrush(QColor(10, 16, 30, a))
                p.drawRoundedRect(r.adjusted(-i, -i + 1, i, i + 1),
                                  RADIUS + i, RADIUS + i)
            p.setBrush(QColor(self.BG))
            p.setPen(QColor(style.BORDER_STRONG))
        p.drawRoundedRect(r, RADIUS, RADIUS)

    # ---- 八方向缩放（默认关掉，见文件头 ALLOW_EDGE_RESIZE 的说明）----
    def _edges_at(self, pos: QPoint) -> Qt.Edges:
        if not ALLOW_EDGE_RESIZE:
            return Qt.Edges()               # 固定窗口：边缘不是缩放热区
        m = max(EDGE, self.margin + 4)      # 边缘感应区不能因为留白变小而消失
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
        return edges

    def mouseMoveEvent(self, e):                           # noqa: N802
        edges = self._edges_at(e.position().toPoint())
        cursors = {
            (Qt.LeftEdge | Qt.TopEdge): Qt.SizeFDiagCursor,
            (Qt.RightEdge | Qt.BottomEdge): Qt.SizeFDiagCursor,
            (Qt.RightEdge | Qt.TopEdge): Qt.SizeBDiagCursor,
            (Qt.LeftEdge | Qt.BottomEdge): Qt.SizeBDiagCursor,
            Qt.LeftEdge: Qt.SizeHorCursor,
            Qt.RightEdge: Qt.SizeHorCursor,
            Qt.TopEdge: Qt.SizeVerCursor,
            Qt.BottomEdge: Qt.SizeVerCursor,
        }
        self.setCursor(cursors.get(edges, Qt.ArrowCursor))
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):                          # noqa: N802
        if e.button() == Qt.LeftButton:
            edges = self._edges_at(e.position().toPoint())
            if edges:
                handle = self._win.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    e.accept()
                    return
        super().mousePressEvent(e)


def wrap(window: QWidget, title: str, version: str, toolbar: QWidget,
         body: QWidget, status: QWidget, glass: bool = True,
         backdrop: bool = False):
    """把 标题栏 / 工具栏 / 主体 / 状态栏 装进自绘外壳，返回 (frame, titlebar)。

    内容从上到下的顺序保证：标题栏占住上面两个圆角、状态栏占住下面两个圆角，
    中间的工具条/主体都是满宽的矩形，不会露出直角去破坏圆角。
    """
    frame = Frame(window, glass=glass, backdrop=backdrop)
    v = QVBoxLayout(frame.inner)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    bar = TitleBar(window, title, version)
    if glass:
        # backdrop 模式圆角由 DWM 负责，这里就不要再加 border-radius（否则双圆角）
        radius_css = ("" if backdrop else
                      "border-top-left-radius:%dpx;border-top-right-radius:%dpx;"
                      % (RADIUS, RADIUS))
        bar.setStyleSheet(
            "QWidget#titleBar{background:rgba(255,255,255,0.42);%s"
            "border-bottom:1px solid rgba(255,255,255,0.55);}"
            "QMenuBar{background:transparent;border:none;}" % radius_css)
        toolbar.setStyleSheet(
            "QToolBar{background:rgba(255,255,255,0.28);border:none;"
            "border-bottom:1px solid rgba(255,255,255,0.45);}")
        status.setStyleSheet(
            "QStatusBar{background:rgba(255,255,255,0.34);border:none;"
            "border-top:1px solid rgba(255,255,255,0.45);%s}"
            "QStatusBar QLabel{color:%s;font-size:12px;}"
            % ("" if backdrop else
               ("border-bottom-left-radius:%dpx;border-bottom-right-radius:%dpx;"
                % (RADIUS, RADIUS)), style.MUTED_STRONG))
    else:
        bar.setStyleSheet("QWidget#titleBar{background:%s;border-top-left-radius:%dpx;"
                          "border-top-right-radius:%dpx;}"
                          % (style.CARD, RADIUS, RADIUS))
    v.addWidget(bar)
    v.addWidget(toolbar)
    v.addWidget(body, 1)
    v.addWidget(status)
    return frame, bar
