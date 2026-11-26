# -*- coding: utf-8 -*-
"""全局样式表（扁平 / 浅色 / 少描边）。

集中在这里而不是散落在各个控件里，方便统一调色和统一圆角。

设计上的几条硬规矩（都是踩过的坑）：
1. **只有窗口自己画底色，其它控件一律透明。** 原来写成 `QWidget { background: BG }`，
   而 Qt 的样式表类型选择器会命中所有子类——于是每个 QLabel 都在文字后面糊了一块
   灰底（用户截图反馈"字有灰色的底"）。现在底色只由 QMainWindow / 卡片负责，
   再显式给 QLabel 兜一条 transparent。
2. **按"卡片 + 间距"分层，而不是"框套框"。** 分组标题放在卡片边框**外面**
   （QGroupBox 的 margin-top 里），这样标题不用靠不透明背景去遮边框线，
   也就不需要给它刷底色。
3. 描边统一 1px 浅灰，圆角 8/12，靠留白和字重区分层级，不靠重边框和蓝色药丸标题。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 配色
BG = "#f3f4f7"          # 窗口底色
CARD = "#ffffff"        # 卡片 / 面板
BORDER = "#e7e9ee"      # 卡片描边、分隔线（很浅）
BORDER_STRONG = "#d8dbe3"   # 输入控件描边（比卡片略深，够看见就行）
TEXT = "#1b1f27"
MUTED = "#868d99"       # 次要文字
MUTED_STRONG = "#6b7280"    # 分组标题
PRIMARY = "#2f6fd0"
PRIMARY_HOVER = "#3f7dda"
PRIMARY_PRESSED = "#275fae"
PRIMARY_SOFT = "#eaf1fd"    # 选中态浅底
DANGER = "#d0453a"
WARN = "#c8860a"

RADIUS = 12             # 控件连续圆角，胶囊另用真正半圆路径
PANEL_RADIUS = 20       # 卡片连续圆角
DIALOG_RADIUS = 26      # 弹窗连续圆角

FONT_STACK = ('"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", '
              '"Noto Sans CJK SC", sans-serif')


STYLESHEET = f"""
/* ---------- 基础：只有窗口画底色，其它一律透明 ---------- */
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: {FONT_STACK};
    font-size: 13px;
}}
/* 显式兜一条：QLabel 曾经被全局 QWidget 规则糊上灰底 */
QLabel {{ background: transparent; }}

QMainWindow {{ background: {BG}; }}

/* ---------- 菜单栏 / 工具栏 ---------- */
QMenuBar {{
    background: {CARD};
    border-bottom: 1px solid {BORDER};
    padding: 2px 6px;
}}
QMenuBar::item {{ padding: 5px 10px; border-radius: 6px; background: transparent; }}
QMenuBar::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QMenu {{
    background: {CARD}; border: 1px solid {BORDER};
    border-radius: {RADIUS}px; padding: 6px;
}}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QToolBar {{
    background: {CARD};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
    padding: 6px 12px;
    color: {TEXT};
}}
QToolBar QToolButton:hover {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QToolBar QToolButton:pressed {{ background: #dbe7fa; }}
QToolBar QToolButton:disabled {{ color: #b9bfc9; }}
QToolBar::separator {{ width: 1px; background: {BORDER}; margin: 5px 8px; }}

/* ---------- 分组卡片：标题在边框外面 ---------- */
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {PANEL_RADIUS}px;
    margin-top: 32px;              /* 标题带：卡片之间靠它拉开距离（用户反馈"模块离太近"） */
    /* 内容留白交给各分组的 layout contentsMargins，避免 QSS padding 和
       layout margin 叠加成两层间距 */
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 3px;
    top: 9px;                      /* 落在 margin 里，上距卡片下距边框都留出空白 */
    padding: 0;
    background: transparent;       /* 不需要遮边框线，所以不用刷底色 */
    color: {MUTED_STRONG};
    font-weight: 600;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #f7f9fc; border-color: #c6cdd9; }}
QPushButton:pressed {{ background: #eef1f6; }}
QPushButton:disabled {{ color: #b9bfc9; background: #f7f8fa; border-color: {BORDER}; }}

QPushButton#primary {{
    background: {PRIMARY};
    border: 1px solid {PRIMARY};
    color: #ffffff;
    font-weight: 600;
    padding: 9px 20px;
}}
QPushButton#primary:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
QPushButton#primary:pressed {{ background: {PRIMARY_PRESSED}; border-color: {PRIMARY_PRESSED}; }}
QPushButton#primary:disabled {{ background: #b9c8e0; border-color: #b9c8e0; color: #eef2f8; }}

QPushButton#ghost {{
    background: transparent;
    border: 1px solid {BORDER_STRONG};
    padding: 9px 16px;
}}
QPushButton#ghost:hover {{ background: {PRIMARY_SOFT}; border-color: #bcd0f2; color: {PRIMARY}; }}

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 6px 10px;
    min-height: 20px;
    selection-background-color: {PRIMARY};
    selection-color: #ffffff;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: #c6cdd9;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {PRIMARY};
}}
QLineEdit:read-only {{ background: #f7f8fa; color: {MUTED}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: #f7f8fa; color: #b9bfc9;
}}

QComboBox::drop-down {{ border: none; width: 24px; }}
/* 箭头不在 QSS 里画：`border` 拼三角这一招在本机渲染出来是一个小方块
   （实测），改成由 widgets.NoWheelComboBox/NoWheelSpinBox 用 QPainter 画。 */
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border: none;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 5px;
    selection-background-color: {PRIMARY_SOFT};
    selection-color: {PRIMARY};
    outline: none;
}}

/* 数字框的上下箭头：做小、做淡，别再糊成一个黑块 */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    width: 20px;
    background: transparent;
    border: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {PRIMARY_SOFT};
}}
/* 上下箭头同样交给 QPainter 画（QSS 的 border 三角在本机渲染成长方形色块） */
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border: none;
    background: transparent;
}}

/* ---------- 滑块 ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: #e3e6ec;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {PRIMARY}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 12px; height: 12px;
    margin: -6px 0;
    border-radius: 7px;
    background: {CARD};
    border: 2px solid {PRIMARY};
}}
QSlider::handle:horizontal:hover {{ background: {PRIMARY_SOFT}; }}
QSlider::handle:horizontal:pressed {{ background: {PRIMARY}; }}
QSlider::handle:horizontal:disabled {{ border-color: #c9ced8; background: #f2f3f6; }}

/* ---------- 列表 ---------- */
QListWidget {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {PANEL_RADIUS}px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 7px;
    margin: 1px 0px;
}}
QListWidget::item:hover {{ background: #f5f7fa; }}
QListWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}

/* ---------- 单复选 ----------
   两条踩过的坑，别改回去：
   1. 选中态**不能改边框宽度**。Qt 的 QSS 里子控件的 width/height 是内容盒，边框是加在外面的：
      没选中 15+1*2=17px、选中 15+4*2=23px，尺寸一跳，23px 的方块配 8px 圆角就渲染成
      "圆角方块"而不是圆点（用户截图里圈出来的就是这个），行高也跟着被撑大。
      现在两种状态几何完全一致，只换颜色。
   2. 要给文字留足高度：min-height 兜住，否则大字号 / 高 DPI 环境下文字底部会被裁掉
      （用户反馈"点排版预览时字体显示不全"）。 */
QRadioButton, QCheckBox {{
    spacing: 8px;
    padding: 3px 0;
    min-height: 20px;
    background: transparent;
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #c3c9d4;
    background: {CARD};
}}
QRadioButton::indicator {{ border-radius: 9px; }}   /* 大于半边长 -> 正圆 */
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{ border-color: {PRIMARY}; }}
QRadioButton::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
}}

/* ---------- 滚动条：细一点 ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 2px 2px 0; }}
QScrollBar::handle:vertical {{ background: #d3d7de; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #b9c0cc; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 0 2px 2px 2px; }}
QScrollBar::handle:horizontal {{ background: #d3d7de; border-radius: 4px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: #b9c0cc; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 底部操作栏 / 状态栏 ---------- */
QFrame#actionBar {{
    background: {CARD};
    border-top: 1px solid {BORDER};
}}

QStatusBar {{ background: {CARD}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {MUTED}; font-size: 12px; }}

QProgressBar {{
    background: #e9ecf1; border: none; border-radius: 5px;
    height: 10px; text-align: center; color: {MUTED}; font-size: 10px;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 5px; }}

QSplitter::handle {{ background: transparent; width: 10px; }}
QSplitter::handle:hover {{ background: #e3e6ec; border-radius: 5px; }}

QToolTip {{
    background: #2b3242; color: #ffffff; border: none;
    border-radius: {RADIUS}px; padding: 6px 9px;
}}
"""


# Painting is kept separate from the QSS above: its box metrics, fonts, padding
# and foreground-state rules remain the source of truth.
import time
import weakref

from shiboken6 import isValid
from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QFrame, QGroupBox, QLabel, QLineEdit,
    QListWidget, QMenu, QMenuBar, QProgressBar, QPushButton, QScrollBar, QSlider,
    QSplitterHandle,
    QStyle, QStyledItemDelegate, QStyleOptionButton, QStyleOptionProgressBar,
    QStyleOptionSlider, QStyleOptionViewItem, QToolBar, QToolButton, QWidget,
)
from .corners import apply_declared_surface, apply_surface, capsule_path, draw_surface
from .motion import busy_band


def _local_override(widget, suffix):
    widget.setStyleSheet(widget.styleSheet() + "\n" + suffix)


class _ContinuousItems(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected or hover:
            rect = QRectF(option.rect).adjusted(0, 1, 0, -1)
            draw_surface(painter, rect, PRIMARY_SOFT if selected else "#f5f7fa",
                         None, 7, 0)
        painter.restore()
        native = QStyleOptionViewItem(option)
        self.initStyleOption(native, index)
        native.state &= ~(QStyle.State_Selected | QStyle.State_MouseOver)
        if selected:
            native.palette.setColor(QPalette.Text, QColor(PRIMARY))
            native.palette.setColor(QPalette.WindowText, QColor(PRIMARY))
        super().paint(painter, native, index)


class _ContinuousStyle(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._installing = set()
        self._busy = weakref.WeakSet()
        self._phase = 0.0
        self._last_tick = time.perf_counter()
        self._style_pending = weakref.WeakSet()
        self._style_timer = QTimer(self)
        self._style_timer.setSingleShot(True)
        self._style_timer.timeout.connect(self._configure_pending)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._animate)
        app.installEventFilter(self)
        for widget in app.allWidgets():
            self.configure(widget)

    def _animate(self):
        now = time.perf_counter()
        self._phase = (self._phase + max(0.0, now - self._last_tick) / 1.4) % 1.0
        self._last_tick = now
        for bar in tuple(self._busy):
            try:
                if bar.isVisible() and bar.isEnabled() and bar.minimum() == bar.maximum() == 0:
                    bar.update()
                else:
                    self._busy.discard(bar)
            except RuntimeError:
                self._busy.discard(bar)
        if not self._busy:
            self._timer.stop()

    def configure(self, w):
        if not isinstance(w, QWidget) or getattr(w, "_continuous_configured", False):
            return
        if id(w) in self._installing or w.property("continuousCorners") is False:
            return
        # Custom painters install their own surfaces.  Never cover a hand-drawn
        # capsule, color swatch, titlebar circle or animated popup viewport.
        if w.metaObject().className() in ("PillButton", "WindowButton", "ColorSwatch"):
            return
        self._installing.add(id(w))
        try:
            self._configure(w)
        finally:
            self._installing.discard(id(w))

    def _configure(self, w):
        if getattr(w, "_continuous_surface", None) is not None:
            w._continuous_configured = True
            return
        if isinstance(w, QPushButton):
            primary, ghost = w.objectName() == "primary", w.objectName() == "ghost"
            fill = PRIMARY if primary else ("transparent" if ghost else CARD)
            edge = PRIMARY if primary else BORDER_STRONG
            states = {
                "hover": dict(fill=PRIMARY_HOVER if primary else
                              (PRIMARY_SOFT if ghost else "#f7f9fc"),
                              border=PRIMARY_HOVER if primary else
                              ("#bcd0f2" if ghost else "#c6cdd9")),
                "pressed": dict(fill=PRIMARY_PRESSED if primary else "#eef1f6",
                                border=PRIMARY_PRESSED if primary else "#c6cdd9"),
                "disabled": dict(fill="#b9c8e0" if primary else "#f7f8fa",
                                 border="#b9c8e0" if primary else BORDER),
            }
            apply_surface(w, fill, edge, RADIUS, states=states)
        elif isinstance(w, (QLineEdit, QAbstractSpinBox, QComboBox)):
            if isinstance(w, QLineEdit) and isinstance(w.parentWidget(),
                                                       (QAbstractSpinBox, QComboBox)):
                return
            def input_fill(widget):
                readonly = isinstance(widget, QLineEdit) and widget.isReadOnly()
                return "#f7f8fa" if readonly or not widget.isEnabled() else CARD
            def input_edge(widget):
                focused = QApplication.focusWidget()
                focus = widget.hasFocus() or (focused is not None and widget.isAncestorOf(focused))
                return PRIMARY if focus else ("#c6cdd9" if widget.underMouse() else BORDER_STRONG)
            apply_surface(w, input_fill, input_edge, RADIUS)
        elif isinstance(w, QToolButton) and isinstance(w.parentWidget(), QToolBar):
            apply_surface(w, "transparent", "transparent", RADIUS,
                          states={"hover": dict(fill=PRIMARY_SOFT),
                                  "pressed": dict(fill="#dbe7fa")})
        elif isinstance(w, QGroupBox):
            # Layout variants with stripped groups provide their own surface.
            if "background:transparent" in w.styleSheet().replace(" ", ""):
                return
            apply_surface(w, CARD, BORDER, PANEL_RADIUS,
                          rect=lambda widget: QRectF(widget.rect()).adjusted(0, 32, 0, 0))
        elif isinstance(w, QListWidget):
            apply_surface(w, CARD, BORDER, PANEL_RADIUS)
            _local_override(w, "QListWidget::item:hover,QListWidget::item:selected"
                               "{background:transparent;}"
                               "QListWidget{selection-background-color:transparent;}")
            w.setItemDelegate(_ContinuousItems(w))
            w.viewport().setAutoFillBackground(False)
            w.setMouseTracking(True)
        elif isinstance(w, QCheckBox):
            _local_override(w, "QCheckBox::indicator,QCheckBox::indicator:hover,"
                               "QCheckBox::indicator:checked"
                               "{background:transparent;border-color:transparent;}")
            w._continuous_native_kind = "checkbox"
        elif isinstance(w, QSlider):
            w._continuous_native_kind = "slider"
        elif isinstance(w, QScrollBar):
            w._continuous_native_kind = "scrollbar"
        elif isinstance(w, QProgressBar):
            w._continuous_native_kind = "progress"
        elif isinstance(w, QSplitterHandle):
            apply_surface(w, "transparent", None, 5, border_width=0,
                          states={"hover": dict(fill="#e3e6ec")})
        elif isinstance(w, QMenu):
            w.setAttribute(Qt.WA_TranslucentBackground, True)
            surface = apply_surface(w, CARD, BORDER, RADIUS)
            _local_override(w, "QMenu::item:selected{background:transparent;}")
            surface.overlay = self._paint_selection
        elif isinstance(w, QMenuBar):
            clear = "background:transparent" in w.styleSheet().replace(" ", "")
            surface = apply_surface(w, "transparent" if clear else CARD, None, 0,
                                    border_width=0, edges={} if clear else {"bottom": BORDER})
            _local_override(w, "QMenuBar::item:selected{background:transparent;}")
            surface.overlay = self._paint_selection
        elif isinstance(w, (QLabel, QFrame)) and w.metaObject().className() != "QTipLabel":
            if "paintEvent" in type(w).__dict__ and type(w).__module__.startswith("app."):
                return
            if apply_declared_surface(w) is None:
                return
            if hasattr(w, "viewport"):
                w.viewport().setAutoFillBackground(False)
        elif w.metaObject().className() == "QTipLabel":
            w.setAttribute(Qt.WA_TranslucentBackground, True)
            apply_surface(w, QColor(43, 50, 66, 240), None, RADIUS, border_width=0)
        else:
            return
        w._continuous_configured = True

    def _configure_pending(self):
        pending = tuple(self._style_pending)
        self._style_pending.clear()
        for widget in pending:
            if isValid(widget):
                self.configure(widget)

    def eventFilter(self, w, event):  # noqa: N802
        kind = event.type()
        if kind in (QEvent.Polish, QEvent.Show):
            self.configure(w)
        elif kind == QEvent.StyleChange and isinstance(w, QWidget):
            # StyleChange is also delivered during native widget construction
            # and repolish. Never mutate QSS or inspect virtual widget state on
            # that stack; weak references keep deletion before dispatch safe.
            self._style_pending.add(w)
            self._style_timer.start(0)
        if kind == QEvent.Paint and isinstance(w, QWidget):
            native = getattr(w, "_continuous_native_kind", None)
            if native:
                return self._paint(w, native)
        return False

    @staticmethod
    def _paint_selection(painter, widget):
        action = widget.activeAction()
        if action is not None and not action.isSeparator():
            draw_surface(painter, QRectF(widget.actionGeometry(action)), PRIMARY_SOFT, None, 6, 0)

    def _paint(self, w, kind):
        p = QPainter(w)
        p.setRenderHint(QPainter.Antialiasing, True)
        if kind == "checkbox":
            opt = QStyleOptionButton()
            w.initStyleOption(opt)
            rect = w.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, w)
            checked = w.isChecked()
            draw_surface(p, QRectF(rect), PRIMARY if checked else CARD,
                         PRIMARY if checked or w.underMouse() else "#c3c9d4", 4)
            # app.widgets.CheckBox draws its own check over the native label.
            if checked and w.metaObject().className() != "CheckBox":
                p.setPen(QPen(QColor("white"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                from PySide6.QtGui import QPainterPath
                tick = QPainterPath()
                tick.moveTo(rect.x() + rect.width() * .26, rect.y() + rect.height() * .52)
                tick.lineTo(rect.x() + rect.width() * .45, rect.y() + rect.height() * .72)
                tick.lineTo(rect.x() + rect.width() * .76, rect.y() + rect.height() * .31)
                p.drawPath(tick)
        elif kind in ("slider", "scrollbar"):
            opt = QStyleOptionSlider()
            w.initStyleOption(opt)
            if kind == "scrollbar":
                rect = w.style().subControlRect(QStyle.CC_ScrollBar, opt,
                                               QStyle.SC_ScrollBarSlider, w)
                hovered = bool(opt.activeSubControls & QStyle.SC_ScrollBarSlider)
                draw_surface(p, QRectF(rect), "#b9c0cc" if hovered else "#d3d7de",
                             None, 4, 0, capsule=True)
            else:
                groove = w.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, w)
                handle = w.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, w)
                draw_surface(p, QRectF(groove), "#e3e6ec", None, 2, 0, capsule=True)
                p.save()
                p.setClipPath(capsule_path(QRectF(groove)))
                filled = QRectF(groove)
                if w.orientation() == Qt.Horizontal:
                    if opt.upsideDown:
                        filled.setLeft(handle.center().x())
                    else:
                        filled.setRight(handle.center().x())
                elif opt.upsideDown:
                    filled.setTop(handle.center().y())
                else:
                    filled.setBottom(handle.center().y())
                p.fillRect(filled, QColor(PRIMARY))
                p.restore()
                if not w.isEnabled():
                    fill, edge = "#f2f3f6", "#c9ced8"
                else:
                    hovered = bool(opt.activeSubControls & QStyle.SC_SliderHandle)
                    fill = PRIMARY if w.isSliderDown() else (PRIMARY_SOFT if hovered else CARD)
                    edge = PRIMARY
                # Slider thumb is an intentional circular control.
                p.setPen(QPen(QColor(edge), 2))
                p.setBrush(QColor(fill))
                p.drawEllipse(QRectF(handle).adjusted(1, 1, -1, -1))
        elif kind == "progress":
            opt = QStyleOptionProgressBar()
            w.initStyleOption(opt)
            rect = QRectF(w.rect())
            draw_surface(p, rect, "#e9ecf1", None, 0, 0, capsule=True)
            p.save()
            p.setClipPath(capsule_path(rect))
            fill = QRectF(rect)
            busy = w.minimum() == w.maximum() == 0
            if busy:
                if w.isVisible() and w.isEnabled():
                    self._busy.add(w)
                    if not self._timer.isActive():
                        self._last_tick = time.perf_counter()
                        self._timer.start()
                offset, span = busy_band(self._phase)
                if w.orientation() == Qt.Horizontal:
                    fill.setWidth(rect.width() * span)
                    fill.moveLeft(rect.left() + rect.width() * offset)
                    if w.invertedAppearance() != (w.layoutDirection() == Qt.RightToLeft):
                        fill.moveRight(rect.right() - rect.width() * offset)
                else:
                    fill.setHeight(rect.height() * span)
                    fill.moveTop(rect.top() + rect.height() * offset)
                    if not w.invertedAppearance():
                        fill.moveBottom(rect.bottom() - rect.height() * offset)
            else:
                self._busy.discard(w)
                fraction = max(0.0, min(1.0, (w.value() - w.minimum()) /
                                       max(1, w.maximum() - w.minimum())))
                if w.orientation() == Qt.Horizontal:
                    fill.setWidth(rect.width() * fraction)
                    if w.invertedAppearance() != (w.layoutDirection() == Qt.RightToLeft):
                        fill.moveRight(rect.right())
                else:
                    fill.setHeight(rect.height() * fraction)
                    if not w.invertedAppearance():
                        fill.moveBottom(rect.bottom())
            draw_surface(p, fill, PRIMARY, None, 0, 0, capsule=True)
            p.restore()
            if w.isTextVisible():
                p.setPen(w.palette().color(QPalette.Text))
                p.drawText(w.rect(), w.alignment(), w.text())
        p.end()
        return kind in ("slider", "scrollbar", "progress")


def install_continuous_style(app: QApplication | None = None):
    """Install continuous backgrounds once; preserve all existing QSS metrics.

    Covers standard buttons, inputs, groups, lists, checkbox indicators, menu
    selections, tooltips, sliders, scrollbars and progress bars. Explicit
    ``corners.apply_surface`` calls take precedence. Set a custom painter's
    ``continuousCorners`` property to False before polish to opt out.
    """
    app = app or QApplication.instance()
    if app is None:
        return None
    current = getattr(app, "_continuous_style", None)
    if current is None:
        current = _ContinuousStyle(app)
        app._continuous_style = current
    return current
