# -*- coding: utf-8 -*-
"""程序运行时该把文件写到哪儿。

**原则：不往 C 盘用户目录丢东西。** 用户明确提过"不要往 C 盘写垃圾，都在工作区内"。

* 冻结后（PyInstaller）：一切都放在 **exe 所在目录**下
  （便携版就是用户解压的那个文件夹；单文件版因为设了 `runtime_tmpdir="."`，
  解压目录也在 exe 旁边，不会去动 `%TEMP%`）。
* 源码运行时：放在**项目根目录**下。

只有一种情况会退回用户目录：程序所在目录**不可写**（例如安装在 Program Files 且没有管理员
权限）。那时给日志找 `~/.idphoto`，否则程序会因为写不了日志而直接崩。
"""
from __future__ import annotations

import os
import sys

LOG_DIR_NAME = ".logs"          # 日志/自检输出都进这里，不散落在外面
OUT_DIR_NAME = "输出"            # 默认导出目录


def app_dir() -> str:
    """程序自己所在的目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:                                      # noqa: BLE001
        return False


def log_dir() -> str:
    """日志目录：优先程序目录下的 .logs，不可写才退回用户目录。"""
    preferred = os.path.join(app_dir(), LOG_DIR_NAME)
    if _writable(preferred):
        return preferred
    fallback = os.path.join(os.path.expanduser("~"), ".idphoto")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def crash_log_path() -> str:
    return os.path.join(log_dir(), "错误日志.txt")


def default_out_dir() -> str:
    """默认导出目录：优先程序目录下的「输出」，不可写才用「图片\\证件照输出」。

    放在程序目录里是用户要求的（导出和程序待在一起，不散到 C 盘）。
    """
    preferred = os.path.join(app_dir(), OUT_DIR_NAME)
    if _writable(preferred):
        return preferred
    pics = os.path.join(os.path.expanduser("~"), "Pictures", "证件照输出")
    os.makedirs(pics, exist_ok=True)
    return pics
