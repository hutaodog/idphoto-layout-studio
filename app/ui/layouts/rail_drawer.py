# -*- coding: utf-8 -*-
"""02 · 图标栏 + 参数抽屉：平时预览最大化，参数按需从左侧滑出。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import style
from .common import IconRail

NAME = "图标栏 + 参数抽屉"
DESC = "左 64px 图标栏，参数按需滑出抽屉，平时预览最大化"

RAIL_ITEMS = [
    ("照片", "照片列表"),
    ("规格", "证件照规格"),
    ("底色", "背景底色"),
    ("微调", "构图微调"),
    ("排版", "相纸与排版"),
    ("导出", "输出设置"),
]


def build(win) -> QWidget:
    # ---- 抽屉：6 个页面，各自复用 MainWindow 的面板构造函数 ----
    left = win._build_left_panel()
    # 抽屉自己有标题行，照片列表面板内部的标题带就重复了 -> 藏起来
    if getattr(win, "lbl_photos_title", None) is not None:
        win.lbl_photos_title.hide()

    pages = [
        left,
        win._group_spec(),
        win._group_bg(),
        win._group_adjust(),
        win._group_layout(),
        win._group_output(),
    ]
    stack = QStackedWidget()
    for p in pages:
        stack.addWidget(p)

    drawer = QWidget()
    drawer.setObjectName("drawer")
    drawer.setFixedWidth(392)
    drawer.setStyleSheet(
        "QWidget#drawer{background:%s;border-right:1px solid %s;}"
        % (style.CARD, style.BORDER))
    dv = QVBoxLayout(drawer)
    dv.setContentsMargins(12, 10, 12, 12)
    dv.setSpacing(8)

    head = QHBoxLayout()
    head.setSpacing(6)
    lbl = QLabel(RAIL_ITEMS[0][1])
    lbl.setStyleSheet("font-weight:600;font-size:13px;color:%s;" % style.TEXT)
    head.addWidget(lbl)
    head.addStretch(1)
    btn_close = QToolButton()
    btn_close.setText("收起")
    btn_close.setCursor(Qt.PointingHandCursor)
    btn_close.setStyleSheet(
        "QToolButton{border:none;background:transparent;color:%s;font-size:12px;}"
        "QToolButton:hover{color:%s;}" % (style.MUTED, style.PRIMARY))
    head.addWidget(btn_close)
    dv.addLayout(head)
    dv.addWidget(stack, 1)

    rail = IconRail([(t, tip) for t, tip in RAIL_ITEMS])
    rail.add_bottom("设置", "设置")

    def show_page(idx: int) -> None:
        stack.setCurrentIndex(idx)
        lbl.setText(RAIL_ITEMS[idx][1])
        drawer.setVisible(True)
        rail.set_current(idx)

    rail.currentChanged.connect(show_page)
    btn_close.clicked.connect(drawer.hide)

    # 中间：预览占满剩余宽度
    center = win._build_center_panel()

    top = QWidget()
    h = QHBoxLayout(top)
    h.setContentsMargins(0, 0, 12, 12)
    h.setSpacing(0)
    h.addWidget(rail)
    h.addWidget(drawer)
    h.addWidget(center, 1)

    root = QWidget()
    rv = QVBoxLayout(root)
    rv.setContentsMargins(0, 0, 0, 0)
    rv.setSpacing(0)
    rv.addWidget(top, 1)
    rv.addWidget(win._build_action_bar())

    # 让其它布局切走时不会被残留引用干扰
    win.split = None
    return root
