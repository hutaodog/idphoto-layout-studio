# -*- coding: utf-8 -*-
"""经典三栏：左照片列表 / 中预览 / 右参数面板（可滚动）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

NAME = "经典三栏"
DESC = "左照片列表 / 中预览 / 右参数面板 + 底部操作栏（原来的交付版式）"


def build(win) -> QWidget:
    split = QSplitter(Qt.Horizontal)
    split.addWidget(win._build_left_panel())
    split.addWidget(win._build_center_panel())
    split.addWidget(win._build_right_panel())
    split.setStretchFactor(0, 0)
    split.setStretchFactor(1, 1)
    split.setStretchFactor(2, 0)
    split.setChildrenCollapsible(False)
    win.split = split
    win._user_split = False
    split.splitterMoved.connect(lambda *_: setattr(win, "_user_split", True))
    win._apply_split_proportions()

    top = QWidget()
    cv = QVBoxLayout(top)
    cv.setContentsMargins(12, 12, 12, 0)
    cv.setSpacing(10)
    cv.addWidget(split, 1)

    root = QWidget()
    rv = QVBoxLayout(root)
    rv.setContentsMargins(0, 0, 0, 0)
    rv.setSpacing(0)
    rv.addWidget(top, 1)
    rv.addWidget(win._build_action_bar())
    return root
