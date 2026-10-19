# -*- coding: utf-8 -*-
"""PATCH-3: cv2.imread / cv2.imwrite 在 Windows 上无法处理中文路径
（实测：同一文件放 ASCII 路径能读，放中文路径返回 None）。np.fromfile + cv2.imdecode 可以。
本模块供内核内部读取 LUT / 模板等资源文件使用。
"""
import os

import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_COLOR):
    """路径安全的 cv2.imread：读不到时返回 None，行为与原函数一致。"""
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)


def imwrite(path, img, params=None):
    """路径安全的 cv2.imwrite，返回是否写成功。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        return False
    buf.tofile(path)
    return True
