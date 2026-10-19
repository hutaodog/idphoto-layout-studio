# -*- coding: utf-8 -*-
"""画布优先（方案 10）：照片画布铺满整个窗口，参数以悬浮玻璃卡浮在它上面。

和「卡片仪表盘」的区别只在**摆法**：
- 这里 `预览` 是**背景层**（铺满），不是玻璃卡；
- 其余 6 张玻璃卡浮在画布上：左边一列（照片列表 / 背景底色 / 相纸与排版），
  右边一列（证件照规格 / 构图微调），中间下方一条（输出设置 + 导出）。
- 卡片照旧可以拖动、八方向拉伸，并且**互相之间绝不重叠**（机制在 `panel_stage.py`）。

毛玻璃、圆角、iOS 玻璃高光都沿用同一套（`app/ui/acrylic.py` + `glass_panel.py`），
所以换到这套布局不会丢掉任何观感或功能。
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..glass_panel import GlassPanel
from ..panel_stage import PanelStage, strip_group

NAME = "画布优先"
DESC = "照片铺满，参数以悬浮玻璃卡浮在画布上"

# 浮在画布上的 6 张卡：(key, 标题, 相对矩形 x/y/w/h, 最小宽, 最小高)
_LAYOUT: List[Tuple[str, str, Tuple[float, float, float, float], int, int]] = [
    # 左列
    ("photos", "照片列表",   (0.010, 0.010, 0.225, 0.250), 300, 150),
    ("bg",     "背景底色",   (0.010, 0.272, 0.225, 0.200), 300, 200),
    ("layout", "相纸与排版", (0.010, 0.484, 0.225, 0.506), 340, 300),
    # 右列
    ("spec",   "证件照规格", (0.765, 0.010, 0.225, 0.400), 300, 300),
    ("adjust", "构图微调",   (0.765, 0.422, 0.225, 0.568), 360, 330),
    # 中间下方
    ("output", "输出设置 / 导出", (0.245, 0.660, 0.510, 0.330), 340, 300),
]

_SLOTS = [(k, frac, mw, mh) for k, _t, frac, mw, mh in _LAYOUT]

# 背景画布四周留一点，露出一圈毛玻璃，别顶到窗口边
_BG_INSET = 8


def build(win) -> QWidget:
    stage = PanelStage(_SLOTS, background=_preview_background(win))
    win.glass_stage = stage            # 「恢复默认布局」要拿到它

    spec = [
        ("photos", "照片列表", _photos(win), "已导入 1 张"),
        ("bg", "背景底色", strip_group(win._group_bg()), "标准蓝"),
        ("layout", "相纸与排版", strip_group(win._group_layout()), "6寸（4R）· 16 张"),
        ("spec", "证件照规格", _spec(win), "54 条"),
        ("adjust", "构图微调", strip_group(win._group_adjust()), "自动构图"),
        ("output", "输出设置 / 导出",
         strip_group(win._group_output()), "跟随规格 · 300 dpi"),
    ]
    for key, title, content, sub in spec:
        mw, mh = stage._minima(key)
        stage.add(key, GlassPanel(title, content, min_w=mw, min_h=mh, subtitle=sub))

    root = QWidget()
    rv = QVBoxLayout(root)
    rv.setContentsMargins(0, 0, 0, 0)
    rv.setSpacing(0)
    rv.addWidget(stage, 1)
    win.split = None
    return root


def _preview_background(win) -> QWidget:
    """背景层 = 预览画布。

    `_build_center_panel()` 返回的外壳顶部有 40px 是给三栏对齐用的，这里把内层
    预览卡片取出来；再套一个留白容器，让画布四周露出一点毛玻璃。
    """
    holder = win._build_center_panel()
    inner = holder.findChild(QWidget, "previewCard")
    card = inner if inner is not None else holder
    if inner is not None:
        inner.setParent(None)
    holder.setParent(None)
    holder.deleteLater()
    win.canvas.setMinimumSize(300, 240)

    wrap = QWidget()
    v = QVBoxLayout(wrap)
    v.setContentsMargins(_BG_INSET, _BG_INSET, _BG_INSET, _BG_INSET)
    v.setSpacing(0)
    v.addWidget(card)
    return wrap


def _photos(win) -> QWidget:
    panel = win._build_left_panel()
    panel.setMaximumWidth(16777215)
    panel.setMinimumWidth(0)
    if getattr(win, "lbl_photos_title", None) is not None:
        win.lbl_photos_title.hide()
    win.lst_photos.setMinimumHeight(60)
    return panel


def _spec(win) -> QWidget:
    gb = strip_group(win._group_spec())
    win.lst_specs.setMinimumHeight(96)
    win.lst_specs.setMaximumHeight(16777215)
    return gb
