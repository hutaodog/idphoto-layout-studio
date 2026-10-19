# -*- coding: utf-8 -*-
"""09 · 中控台式：56px 图标栏 + 可折叠属性面板 + 大预览。

属性面板里每个分组都是**可折叠**的：折叠后只留一行标题 + 当前值摘要
（例如「构图微调   手动微调 · 62%」），这是这套布局的核心特征。
点左边图标栏会把属性面板滚到对应分组并展开它。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from .. import style
from .common import CollapsibleSection, IconRail

NAME = "中控台式"
DESC = "图标栏 + 可折叠属性面板（折叠行带值摘要）+ 大预览"

RAIL = [("照片", "照片列表"), ("规格", "证件照规格"), ("底色", "背景底色"),
        ("微调", "构图微调"), ("排版", "相纸与排版"), ("导出", "输出设置")]


def _strip_title(gb) -> None:
    """去掉分组卡片自带的标题带（标题由可折叠分组的 header 负责）。"""
    gb.setTitle("")
    gb.setStyleSheet(
        "QGroupBox{background:%s;border:1px solid %s;border-radius:12px;"
        "margin-top:4px;}" % (style.CARD, style.BORDER))


def build(win) -> QWidget:
    left = win._build_left_panel()
    if getattr(win, "lbl_photos_title", None) is not None:
        win.lbl_photos_title.hide()

    groups = [
        ("照片列表", left, ""),
        ("证件照规格", win._group_spec(), "54 条"),
        ("背景底色", win._group_bg(), "标准蓝"),
        ("构图微调", win._group_adjust(), "自动构图"),
        ("相纸与排版", win._group_layout(), "6寸（4R）·16 张"),
        ("输出设置", win._group_output(), "跟随规格 · 300 dpi"),
    ]

    panel = QWidget()
    pv = QVBoxLayout(panel)
    pv.setContentsMargins(10, 6, 10, 10)
    pv.setSpacing(4)

    sections = []
    for i, (title, content, summary) in enumerate(groups):
        if i > 0:
            _strip_title(content)
        sec = CollapsibleSection(title, content, summary=summary, expanded=(i <= 1))
        sections.append(sec)
        pv.addWidget(sec)
    pv.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(panel)
    scroll.setFixedWidth(340)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea{background:%s;border:none;}" % style.BG)

    rail = IconRail([(t, tip) for t, tip in RAIL])
    rail.add_bottom("设置", "设置")

    def goto(idx: int) -> None:
        sec = sections[idx]
        sec.set_expanded(True)
        scroll.ensureWidgetVisible(sec, 0, 12)

    rail.currentChanged.connect(goto)

    center = win._build_center_panel()

    body = QWidget()
    h = QHBoxLayout(body)
    h.setContentsMargins(0, 0, 12, 12)
    h.setSpacing(0)
    h.addWidget(rail)
    h.addWidget(scroll)
    h.addWidget(center, 1)

    root = QWidget()
    rv = QVBoxLayout(root)
    rv.setContentsMargins(0, 0, 0, 0)
    rv.setSpacing(0)
    rv.addWidget(body, 1)
    rv.addWidget(win._build_action_bar())
    win.split = None
    return root
