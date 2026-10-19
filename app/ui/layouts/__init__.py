# -*- coding: utf-8 -*-
"""界面布局注册表。

v1.3.0 起**只有一套界面**：卡片仪表盘（用户明确要求"不做切换"）。
原来那几套（经典三栏 / 图标栏+抽屉 / 中控台式 / 画布优先）的模块文件仍然留在
本目录里当参考，但没有被注册 —— 想恢复其中某套，把它的模块名加回下面的
静态 import 列表即可。

两个约定（别改）：
1. **必须静态 import**。曾经用 importlib 动态发现，源码/测试全绿但打包版一启动
   就 `IndexError` —— PyInstaller 的静态分析看不见动态导入的字符串，模块没进 exe。
2. 布局模块只暴露 `NAME` / `DESC` / `build(win) -> QWidget`，内容一律复用
   MainWindow 上的面板构造函数，保证功能与其它布局完全一致。
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtWidgets import QWidget

DEFAULT_LAYOUT = "studio"

_MODULES: list = []

try:
    from . import studio             # 工作台：左参数列 + 右大预览（当前默认，按参考图做的）
    _MODULES.append(studio)
except Exception as _e:                                      # noqa: BLE001
    print("[layouts] studio 不可用: %r" % (_e,))

try:
    from . import canvas_first        # 方案 10：画布铺满 + 悬浮玻璃卡，保留可切
    _MODULES.append(canvas_first)
except Exception as _e:                                      # noqa: BLE001
    print("[layouts] canvas_first 不可用: %r" % (_e,))

try:
    from . import dashboard           # 卡片仪表盘（平铺），保留可切
    _MODULES.append(dashboard)
except Exception as _e:                                      # noqa: BLE001
    print("[layouts] dashboard 不可用: %r" % (_e,))


def _key(m) -> str:
    return m.__name__.rsplit(".", 1)[-1]


REGISTRY: List[Tuple[str, str, object]] = [
    (_key(m), getattr(m, "NAME", _key(m)), m) for m in _MODULES
]


def keys() -> List[str]:
    return [k for k, _n, _m in REGISTRY]


def entries() -> List[Tuple[str, str]]:
    return [(k, n) for k, n, _m in REGISTRY]


def module_for(key: str):
    for k, _n, m in REGISTRY:
        if k == key:
            return m
    if not REGISTRY:
        raise RuntimeError(
            "没有可用的界面布局模块（app.ui.layouts.* 没被打进包里？"
            "请检查 packaging/*.spec 的 hiddenimports）")
    return REGISTRY[0][2]


def build(win, key: str) -> QWidget:
    return module_for(key).build(win)
