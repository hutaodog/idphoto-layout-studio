# -*- coding: utf-8 -*-
"""自定义控件：滚轮防误触的数字框/下拉框、色块按钮、大圆角弹窗。

滚轮防误触：Qt 默认让鼠标滚轮直接改数字框和下拉框的值。第一次反馈后改成
"先点一下聚焦，滚轮才生效"；但用户第二次截图反馈**点过之后滚页面仍会误改**
（鼠标停在参数框上滚动就变数），所以现在是**彻底不响应滚轮**：
数值只能键盘输入，或用数字框右侧的上下箭头调。滚轮事件 ignore() 之后会冒泡给
父容器，右侧面板照常滚动，不会"滚不动"。
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen,
                           QPolygonF)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QStyle, QStyleOptionButton,
                               QStyleOptionComboBox, QStyleOptionSpinBox,
                               QVBoxLayout, QWidget)

from . import style


class _WheelGuard:
    """混入类：忽略一切滚轮事件，数值绝不会被滚轮改掉。

    注意别"优化"成 `if self.hasFocus(): super().wheelEvent(event)`：那样用户
    只要点过一次这个框，之后每次把鼠标停在上面滚页面都会改到数值（实测复现）。
    """

    def wheelEvent(self, event):                      # noqa: N802
        event.ignore()                                # 交还给父容器滚动


def _paint_triangle(p: QPainter, cx: float, cy: float, w: float, h: float,
                    up: bool, color: QColor) -> None:
    """画一个实心小三角（下拉箭头 / 数字框上下箭头）。

    为什么自己画：QSS 里用 `border-*` 拼三角这一招，在本机的 Qt 版本上渲染成了
    **一个小方块**（下拉箭头）和**两个灰色长方形**（数字框上下箭头）——
    用户截图圈过"这块的图标显示好像有问题"。自己画最省事也最可控。
    """
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    if up:
        pts = [QPointF(cx - w / 2, cy + h / 2), QPointF(cx + w / 2, cy + h / 2),
               QPointF(cx, cy - h / 2)]
    else:
        pts = [QPointF(cx - w / 2, cy - h / 2), QPointF(cx + w / 2, cy - h / 2),
               QPointF(cx, cy + h / 2)]
    p.drawPolygon(QPolygonF(pts))


def _arrow_color(widget) -> QColor:
    return QColor(style.MUTED_STRONG) if widget.isEnabled() else QColor("#cdd2da")


class _SpinArrows:
    """给数字框补一对自绘的上下箭头（QSS 画出来是两个灰方块，见 `_paint_triangle`）。"""

    def paintEvent(self, e):                           # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)
        color = _arrow_color(self)
        for sub, up in ((QStyle.SC_SpinBoxUp, True), (QStyle.SC_SpinBoxDown, False)):
            r = self.style().subControlRect(QStyle.CC_SpinBox, opt, sub, self)
            if r.isValid() and not r.isEmpty():
                _paint_triangle(p, r.center().x() + 0.5, r.center().y() + 0.5,
                                8.0, 5.0, up, color)


class NoWheelSpinBox(_SpinArrows, _WheelGuard, QSpinBox):
    pass


class NoWheelDoubleSpinBox(_SpinArrows, _WheelGuard, QDoubleSpinBox):
    pass


class NoWheelComboBox(_WheelGuard, QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 不让"鼠标划过"就抢焦点（否则输入法/焦点高亮会乱跳）
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, e):                           # noqa: N802
        """自绘下拉箭头（QSS 画出来是个小方块，见 `_paint_triangle` 的说明）。"""
        super().paintEvent(e)
        if not self.count():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        r = self.style().subControlRect(QStyle.CC_ComboBox, opt,
                                        QStyle.SC_ComboBoxArrow, self)
        if r.isValid() is False or r.isEmpty():
            r = self.rect().adjusted(self.width() - 26, 0, 0, 0)
        _paint_triangle(p, r.center().x() + 0.5, r.center().y() + 1.0,
                        10.0, 6.0, False, _arrow_color(self))


class CheckBox(QCheckBox):
    """带自绘对勾的复选框。

    QSS 只能把选中态画成"实心蓝方块"（微软雅黑里没有对勾字形，也不能靠文字画），
    看着就像坏了（用户截图圈过）。所以勾由这里画：白色折线，圆头圆角。
    """

    def paintEvent(self, e):                           # noqa: N802
        super().paintEvent(e)
        if not self.isChecked():
            return
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        r = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, self)
        if r.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#ffffff"), 2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(r.left() + r.width() * 0.26, r.top() + r.height() * 0.52)
        path.lineTo(r.left() + r.width() * 0.45, r.top() + r.height() * 0.72)
        path.lineTo(r.left() + r.width() * 0.76, r.top() + r.height() * 0.31)
        p.drawPath(path)


class NoWheelSlider(_WheelGuard, QSlider):
    """微调滑块：也不用滚轮改值（滚页面时鼠标划过滑块同理会误改）。"""


class ColorSwatch(QPushButton):
    """色块按钮（选中时加粗描边）。

    注意：规格库里的 hex 是不带 # 的（如 "628BCE"），直接塞进 CSS 是**非法值**，
    Qt 会静默回退成全局样式的白色——表现为"色块一片空白"。这里统一补上 #。
    """

    def __init__(self, hex_code: str, text: str = "", parent=None):
        super().__init__(text, parent)
        self.hex_code = hex_code
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._refresh()

    @property
    def css_color(self) -> str:
        h = (self.hex_code or "").lstrip("#").strip()
        if len(h) != 6:
            h = "FFFFFF"
        return "#" + h.upper()

    def _refresh(self) -> None:
        bg = self.css_color
        fg = "#ffffff" if self._is_dark() else "#3a3f4b"
        # 描边 1px→选中 2px：只差 1px，选中时不会有明显的尺寸跳动
        self.setStyleSheet(
            "QPushButton{background-color:%s;border:1px solid rgba(0,0,0,0.14);"
            "border-radius:%dpx;color:%s;font-weight:600;padding:5px 10px;}"
            "QPushButton:hover{border:2px solid #b9c6da;}"
            "QPushButton:checked{border:2px solid %s;}"
            % (bg, style.RADIUS, fg, style.PRIMARY)
        )

    def _is_dark(self) -> bool:
        h = self.css_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) < 150


class PillButton(QPushButton):
    """胶囊按钮（工具栏右侧那三个导出按钮）——**平面**风格 + 主按钮泛光。

    用户前后改了三轮，最后拍板的是这一版，别再往回改：
      v1.5.3「改成胶囊状，也有点玻璃质感」→ 做了清玻璃；
      v1.5.4「改成那种磨砂玻璃…蓝色按钮可以带点泛光」→ 做了磨砂玻璃；
      v1.5.5「把玻璃效果去掉吧，就改成平面就行，泛光保留。现在这样太丑」→ **平面 + 泛光**。

    现在的画法（全部自绘；QSS 的 border-radius 是固定值，高度一变就不是胶囊了）：
      * **平涂纯色**填充 + 1px 描边，没有渐变、没有颗粒、没有高光；
      * 白胶囊：常态白底浅灰边，悬停浅蓝底蓝字，按下再深一点；**不投影**；
      * 蓝胶囊：常态主题蓝，悬停/按下用主题色的 hover/pressed 色；
      * **只有主按钮保留一圈蓝色泛光**。

    文字仍交给 style 的 CE_PushButtonLabel 画，字体/省略号行为与普通 QPushButton 一致。
    注意：**不要**把 QHBoxLayout 塞进 QPushButton（见交接笔记坑 #12）——这里是纯自绘。
    """

    def __init__(self, text: str = "", primary: bool = False, parent=None):
        super().__init__(text, parent)
        self.primary = primary
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(38 if primary else 34)
        # 底色/描边全部自绘；这里只留左右内边距给文字（也把全局 QSS 的按钮底色挡掉）
        self.setStyleSheet(
            "QPushButton{background:transparent;border:none;padding:0 22px;}")
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance(text) + 52)
        # 只有主按钮要泛光：offset=0 让光晕四周均匀；白胶囊保持平面，不挂投影
        if primary:
            sh = QGraphicsDropShadowEffect(self)
            sh.setBlurRadius(28)
            sh.setOffset(0, 0)
            sh.setColor(QColor(47, 111, 208, 165))
            self.setGraphicsEffect(sh)

    # ---------- 状态变化要重画 ----------
    def enterEvent(self, e):                               # noqa: N802
        super().enterEvent(e)
        self.update()

    def leaveEvent(self, e):                               # noqa: N802
        super().leaveEvent(e)
        self.update()

    # ---------- 颜色 ----------
    def _palette(self):
        """返回 (填充色, 描边色, 文字色) —— 平面风格，只有三个值。

        用户最后拍板："把玻璃效果去掉吧，就改成平面就行，泛光保留。"
        所以这里不再有渐变/颗粒/高光，只有三种状态各一组纯色。
        """
        if self.isDown():
            if self.primary:
                return style.PRIMARY_PRESSED, style.PRIMARY_PRESSED, "#ffffff"
            return "#dbe7fa", style.PRIMARY, style.PRIMARY
        if self.underMouse():
            if self.primary:
                return style.PRIMARY_HOVER, style.PRIMARY_HOVER, "#ffffff"
            # 悬停给一点主题蓝（和项目里别的 ghost 按钮一致），白底上才看得出反应
            return style.PRIMARY_SOFT, "#bcd0f2", style.PRIMARY
        if self.primary:
            return style.PRIMARY, style.PRIMARY, "#ffffff"
        return style.CARD, style.BORDER_STRONG, style.TEXT

    # ---------- 绘制 ----------
    def paintEvent(self, e):                               # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = min(r.height(), r.width()) / 2.0
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)

        fill, border, fg = self._palette()

        # 平面：一层纯色 + 1px 描边，就这两笔
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(fill))
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(border), 1.0))
        p.drawPath(path)

        # 文字（沿用 QPushButton 自己的绘制，字体/省略号行为不变）
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.palette.setColor(self.foregroundRole(), QColor(fg))
        p.setPen(QColor(fg))
        self.style().drawControl(QStyle.CE_PushButtonLabel, opt, p)


class RoundedDialog(QDialog):
    """无边框大圆角弹窗（Windows 原生标题栏太方，用户要求圆角大一点）。"""

    RADIUS = style.DIALOG_RADIUS

    def __init__(self, parent=None, title: str = "", text: str = "",
                 kind: str = "info", buttons: Sequence[str] = ("好的",),
                 detail: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self._drag: Optional[QPoint] = None
        self._result_index = 0
        self._buttons: List[QPushButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)     # 给阴影留出空间

        card = QFrame()
        card.setObjectName("dialogCard")
        card.setStyleSheet(
            "#dialogCard{background:%s;border-radius:%dpx;border:1px solid %s;}"
            % (style.CARD, self.RADIUS, style.BORDER))
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(38)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 28, 45, 90))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(26, 22, 26, 20)
        v.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(10)
        # 画一个色点，而不是用 ⓘ/⚠/✕ 这类符号字形：
        # 微软雅黑里没有 U+24D8 / U+26A0 / U+2715（实测会渲染成豆腐块）
        dot = QFrame()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet("background:%s;border-radius:5px;" % (
            style.PRIMARY if kind == "info" else
            (style.WARN if kind == "warn" else style.DANGER)))
        head.addWidget(dot, 0, Qt.AlignVCenter)
        lbl_title = QLabel(title or "提示")
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        lbl_title.setFont(f)
        lbl_title.setStyleSheet("background:transparent;")
        head.addWidget(lbl_title, 1)
        v.addLayout(head)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet("background:transparent;color:%s;" % style.TEXT)
        if detail:
            holder = QScrollArea()
            holder.setWidgetResizable(True)
            holder.setMaximumHeight(150)
            holder.setStyleSheet(
                "QScrollArea{background:#f6f8fb;border:1px solid %s;border-radius:10px;}"
                % style.BORDER)
            inner = QLabel(detail)
            inner.setWordWrap(True)
            inner.setTextInteractionFlags(Qt.TextSelectableByMouse)
            inner.setStyleSheet("background:transparent;color:%s;font-size:12px;" % style.MUTED)
            holder.setWidget(inner)
            v.addWidget(body)
            v.addWidget(holder)
        else:
            v.addWidget(body)

        row = QHBoxLayout()
        row.addStretch(1)
        for i, label in enumerate(buttons):
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            if i == len(buttons) - 1:
                btn.setObjectName("primary")
                btn.setMinimumWidth(96)
            else:
                btn.setObjectName("ghost")
                btn.setMinimumWidth(88)
            btn.clicked.connect(lambda _=False, idx=i: self._choose(idx))
            row.addWidget(btn)
            self._buttons.append(btn)
        v.addLayout(row)

        self._card = card
        if buttons:
            self._buttons[-1].setDefault(True)
            self._buttons[-1].setFocus()

    def _choose(self, idx: int) -> None:
        self._result_index = idx
        self.accept() if idx == len(self._buttons) - 1 else self.reject()

    def result_index(self) -> int:
        return self._result_index

    # 无边框窗口：按住卡片任意位置可拖动
    def mousePressEvent(self, e):                         # noqa: N802
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):                          # noqa: N802
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):                       # noqa: N802
        self._drag = None

    def keyPressEvent(self, e):                           # noqa: N802
        if e.key() == Qt.Key_Escape:
            self._result_index = 0
            self.reject()
            return
        super().keyPressEvent(e)


def show_message(parent, title: str, text: str = "", kind: str = "info",
                 ok_text: str = "好的", detail: str = "") -> None:
    """统一的圆角提示弹窗。测试里可以直接 monkeypatch 掉这个函数。"""
    dlg = RoundedDialog(parent, title=title, text=text, kind=kind,
                        buttons=(ok_text,), detail=detail)
    _center_on(dlg, parent)
    dlg.exec()


def ask_confirm(parent, title: str, text: str = "", yes_text: str = "确定",
                no_text: str = "取消") -> bool:
    dlg = RoundedDialog(parent, title=title, text=text, kind="warn",
                        buttons=(no_text, yes_text))
    _center_on(dlg, parent)
    dlg.exec()
    return dlg.result_index() == 1


def _center_on(dlg: QDialog, parent) -> None:
    try:
        dlg.adjustSize()
        if parent is not None:
            geo = parent.frameGeometry()
            dlg.move(geo.center() - dlg.rect().center())
    except Exception:                                      # noqa: BLE001
        pass
