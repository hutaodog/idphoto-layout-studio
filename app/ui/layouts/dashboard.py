# -*- coding: utf-8 -*-
"""卡片仪表盘：一屏浮动的玻璃卡片，能拖能拉。

卡片是 **iOS 风格玻璃**（竖向渐变 + 顶部高光线 + 亮描边 + 外投影），
底下是窗口的毛玻璃（能透出桌面）。7 张卡平铺，默认 **预览卡** 与 **相纸排版卡** 最大。

舞台（绝对定位 / 拖动 / 拉伸 / 防重叠）的机制在 `app/ui/panel_stage.py` 里，两套界面共用。
所有卡片内容仍然来自 MainWindow 的面板构造函数，所以功能与其它界面完全一致。
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtWidgets import (QGridLayout, QVBoxLayout, QWidget)

from ..glass_panel import GlassPanel
from ..panel_stage import PanelStage, strip_group

NAME = "卡片仪表盘"
DESC = "七张浮动玻璃卡片平铺，可自由拖动与缩放"

# (key, 标题, 相对矩形 x/y/w/h, 最小宽, 最小高)
# 预览 = 最大的那张；相纸与排版 = 第二大的那张
_LAYOUT: List[Tuple[str, str, Tuple[float, float, float, float], int, int]] = [
    ("preview", "预览",              (0.012, 0.012, 0.548, 0.440), 520, 300),
    ("layout",  "相纸与排版",         (0.568, 0.012, 0.420, 0.440), 420, 300),
    ("adjust",  "构图微调",           (0.012, 0.462, 0.285, 0.526), 380, 330),
    ("bg",      "背景底色",           (0.305, 0.462, 0.245, 0.245), 300, 200),
    ("photos",  "照片列表",           (0.305, 0.717, 0.245, 0.271), 300, 150),
    ("spec",    "证件照规格",         (0.558, 0.462, 0.200, 0.526), 300, 300),
    ("output",  "输出设置 / 导出",     (0.766, 0.462, 0.222, 0.526), 320, 300),
]

_SLOTS = [(k, frac, mw, mh) for k, _t, frac, mw, mh in _LAYOUT]


def build(win) -> QWidget:
    """装配卡片仪表盘（内容全部复用 MainWindow 上的面板构造函数）。"""
    panels_spec = [
        ("preview", "预览", win._build_center_panel(), "小一寸 260×378"),
        ("layout", "相纸与排版", win._group_layout(), "6寸（4R）· 16 张"),
        ("adjust", "构图微调", win._group_adjust(), "自动构图"),
        ("bg", "背景底色", win._group_bg(), "标准蓝"),
        ("photos", "照片列表", win._build_left_panel(), "已导入 1 张"),
        ("spec", "证件照规格", win._group_spec(), "54 条"),
        ("output", "输出设置 / 导出", win._group_output(), "跟随规格 · 300 dpi"),
    ]
    stage = PanelStage(_SLOTS)
    win.glass_stage = stage            # 「恢复默认布局」要拿到它
    _assemble(win, stage, panels_spec)

    root = QWidget()
    rv = QVBoxLayout(root)
    rv.setContentsMargins(0, 0, 0, 0)
    rv.setSpacing(0)
    rv.addWidget(stage, 1)
    win.split = None
    return root


def _assemble(win, stage: PanelStage, panels_spec) -> None:
    """把各面板加工成玻璃卡片并挂到舞台上（两套界面共用的装配流程）。"""
    prep = _content_preparer(win)
    for key, title, content, sub in panels_spec:
        content = prep(key, content)
        mw, mh = stage._minima(key)
        stage.add(key, GlassPanel(title, content, min_w=mw, min_h=mh, subtitle=sub))


def _content_preparer(win):
    """返回一个 (key, widget) -> widget 的加工函数。

    * 预览：`_build_center_panel()` 返回的外壳顶部有 40px 是给三栏对齐用的，
      这里把内层预览卡片取出来当内容，省掉那段空档；
    * 各分组：去掉 QGroupBox 自带的标题带（玻璃卡片自己有标题）；
    * 照片列表：卡片比 330 宽，放宽限制；
    * 输出：把导出按钮从动作栏里取出来，两行排（三个按钮塞一行会被裁）。
    """
    made = {"output": False}

    def prep(key: str, content: QWidget) -> QWidget:
        if key == "preview":
            holder = content
            inner = holder.findChild(QWidget, "previewCard")
            if inner is not None:
                inner.setParent(None)
                inner.setStyleSheet(
                    "QFrame#previewCard{background:transparent;border:none;}")
                holder.setParent(None)
                holder.deleteLater()
                content = inner
            else:
                content = holder
            win.canvas.setMinimumSize(300, 240)
        elif key == "photos":
            content.setMaximumWidth(16777215)
            content.setMinimumWidth(0)
            if getattr(win, "lbl_photos_title", None) is not None:
                win.lbl_photos_title.hide()
            win.lst_photos.setMinimumHeight(60)
        elif key == "spec":
            content = strip_group(content)
            win.lst_specs.setMinimumHeight(96)
            win.lst_specs.setMaximumHeight(16777215)
        elif key == "output":
            content = strip_group(content)
        else:
            content = strip_group(content)
        return content

    return prep
