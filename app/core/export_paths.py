# -*- coding: utf-8 -*-
"""GUI 导出的可读文件名与独占路径；不改变通用编码器的覆盖语义。"""
from __future__ import annotations

import os
import re
import unicodedata
from contextlib import contextmanager
from typing import Iterator, Optional

from .specs import PaperSpec, PhotoSpec


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])$", re.IGNORECASE)


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _shorten(text: str, limit: int) -> str:
    """NTFS 的单个文件名按 UTF-16 计长，避免从代理对中间截断。"""
    return text.encode("utf-16-le")[:limit * 2].decode("utf-16-le", errors="ignore")


def safe_filename_part(value: str, limit: int = 64) -> str:
    """保留中文可读性，去掉 Windows 非法字符、尾随点空格和设备名。"""
    text = unicodedata.normalize("NFC", str(value))
    text = _INVALID.sub("_", text).strip(" .")
    text = re.sub(r"_+", "_", text)
    text = _shorten(text, limit).rstrip(" .") or "照片"
    if _RESERVED.fullmatch(text.split(".", 1)[0].rstrip(" ")):
        text = "_" + _shorten(text, limit - 1)
    return text


def export_stem(source_stem: str, spec: PhotoSpec, background: str,
                paper: Optional[PaperSpec] = None) -> str:
    """照片名、可读规格、稳定 ID、毫米和底色；排版另带相纸信息。"""
    parts = [safe_filename_part(spec.name_zh, 42), safe_filename_part(spec.id),
             "%gx%gmm" % spec.mm_size, safe_filename_part(background, 32)]
    if paper is None:
        parts.append("证件照")
    else:
        parts.extend([safe_filename_part(paper.name_zh, 24),
                      safe_filename_part(paper.id, 32),
                      "%gx%gmm排版" % paper.mm])
    metadata = "_".join(parts)
    # 优先缩短原照片名，保证规格、尺寸和纸张仍可辨认。预留扩展名和重名序号空间。
    source_limit = min(48, 224 - _units(metadata) - 1)
    if source_limit < 1:
        raise ValueError("规格和相纸名称过长，无法生成安全的导出文件名")
    return "%s_%s" % (safe_filename_part(source_stem, source_limit), metadata)


@contextmanager
def reserve_export_path(directory: str, stem: str) -> Iterator[str]:
    """独占保留 .jpg；已存在则递增后缀，写失败只清理本次占用的文件。

    保持预留句柄直至保存完成；Windows 下也阻止路径在写入期间被替换。
    调用者仅可把保留路径交给会原地写文件的编码器（如 save_image）。
    """
    directory = os.path.abspath(os.fspath(directory))
    os.makedirs(directory, exist_ok=True)
    stem = safe_filename_part(stem, 224)
    index = 1
    while True:
        suffix = "" if index == 1 else "_%d" % index
        path = os.path.join(directory, "%s%s.jpg" % (stem, suffix))
        try:
            reservation = open(path, "xb")
        except OSError:
            # 目录、链接和普通文件都占用名称。O_EXCL 处理检查后的并发创建。
            if not os.path.lexists(path):
                raise
            index += 1
            continue
        break
    identity = os.fstat(reservation.fileno())
    try:
        yield path
        current = os.stat(path, follow_symlinks=False)
        if not os.path.samestat(identity, current) or current.st_size == 0:
            raise OSError("导出未写入预留的文件：%s" % path)
    except BaseException:
        reservation.close()
        try:
            if os.path.samestat(identity, os.stat(path, follow_symlinks=False)):
                os.unlink(path)
        except OSError:
            pass
        raise
    else:
        reservation.close()
