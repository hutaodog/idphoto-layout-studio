# -*- coding: utf-8 -*-
"""路径安全的图像读写。

为什么必须有这个模块：cv2.imread / cv2.imwrite 在 Windows 上无法处理含中文的路径
（实测：同一张图放 ASCII 路径能读，放中文路径返回 None，且 imwrite 静默失败）。
本项目的安装目录和用户的照片文件名都极可能含中文，因此全项目一律走这里。
"""
from __future__ import annotations

import os

import cv2
import numpy as np


def imread(path: str, flags: int = cv2.IMREAD_COLOR):
    """路径安全的 cv2.imread。读不到时返回 None（与原函数行为一致）。"""
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)


def imwrite(path: str, img: np.ndarray, params=None) -> bool:
    """路径安全的 cv2.imwrite，返回是否写成功。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        return False
    buf.tofile(path)
    return True


def to_uint8(img: np.ndarray) -> np.ndarray:
    """上游 add_background() 返回 float64（实测范围 0~255），必须转 uint8 才能交给下游。"""
    if img.dtype == np.uint8:
        return img
    return np.ascontiguousarray(np.clip(img, 0, 255).astype(np.uint8))


def bgr_to_rgb(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def rgb_to_bgr(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def hex_to_bgr(hex_str: str):
    """'#628BCE' -> (206, 139, 98)  BGR 元组。"""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


def hex_to_rgb(hex_str: str):
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
