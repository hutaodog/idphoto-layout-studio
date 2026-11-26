# -*- coding: utf-8 -*-
"""导出：精确控制 DPI 元数据与文件大小。

这里集中了调研里最容易翻车的两件事：
1. **DPI 元数据**：把 295×413px 标成 350dpi 打印出来只有 21.4×30.0mm（小 8.5%）；
   身份证 358×441px 若按 300dpi 打印是 30.3×37.3mm（比标准 26×32mm 大 15%）。
   因此 DPI 必须逐张写入并**回读校验**。
2. **文件大小有下限**：报名系统不只卡上限（≤200KB），还有下限（≥20KB）。
   20KB 只能承载约 0.06MP，所以「144×192px 且 ≥20KB」无法靠降质量达成，必须合法填充。

编码时写入 DPI 元数据，最后按文件格式填充。
"""
from __future__ import annotations

import io
import math
import os
import struct
import zlib
from dataclasses import dataclass
from numbers import Real
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from .io_compat import to_uint8

MAX_COM_PAYLOAD = 65533            # JPEG COM 段最大负载
MAX_COM_SEG = MAX_COM_PAYLOAD + 4  # 含 FFFE + 2 字节长度


@dataclass
class SaveReport:
    path: str
    bytes: int
    kb: float
    dpi_written: Tuple[int, int]
    dpi_readback: Optional[Tuple[int, int]]
    quality: Optional[int]
    padded_bytes: int
    fits_limits: bool
    messages: list

    def ok(self) -> bool:
        return self.fits_limits and self.dpi_readback is not None and (
            abs(self.dpi_readback[0] - self.dpi_written[0]) <= 1
            and abs(self.dpi_readback[1] - self.dpi_written[1]) <= 1
        )


def _number(value, name: str, *, integer: bool = False,
            allow_zero: bool = False):
    if (isinstance(value, bool) or not isinstance(value, Real)
            or not math.isfinite(value) or (value < 0 if allow_zero else value <= 0)
            or (integer and value != int(value))):
        raise ValueError("%s 必须为有限%s%s" % (
            name, "非负" if allow_zero else "正", "整数" if integer else "数"))
    return int(value) if integer else value


def _to_pil(img: np.ndarray) -> Image.Image:
    """BGR / BGRA ndarray -> PIL Image（RGB / RGBA）。"""
    if not isinstance(img, np.ndarray) or img.size == 0:
        raise ValueError("图像不能为空")
    arr = to_uint8(img)
    if arr.ndim == 2:
        return Image.fromarray(arr, mode="L").convert("RGB")
    if arr.ndim == 3 and arr.shape[2] == 4:
        return Image.fromarray(arr[:, :, [2, 1, 0, 3]], mode="RGBA")
    if arr.ndim == 3 and arr.shape[2] == 3:
        return Image.fromarray(arr[:, :, ::-1], mode="RGB")
    raise ValueError("不支持的图像形状: %r" % (arr.shape,))


def _encode(img: np.ndarray, fmt: str, dpi: int, quality: int = 95) -> bytes:
    pil = _to_pil(img)
    buf = io.BytesIO()
    if fmt == "png":
        pil.save(buf, format="PNG", dpi=(dpi, dpi))
    elif fmt in ("jpg", "jpeg"):
        if pil.mode == "RGBA":
            background = Image.new("RGB", pil.size, (255, 255, 255))
            background.paste(pil, mask=pil.getchannel("A"))
            pil = background
        exif = Image.Exif()
        # Pillow/JFIF stores integer DPI; EXIF resolution provides a fallback
        # for external JPEGs that omit JFIF density fields.
        from PIL.TiffImagePlugin import IFDRational
        exif[282] = IFDRational(int(dpi), 1)  # XResolution
        exif[283] = IFDRational(int(dpi), 1)  # YResolution
        exif[296] = 2                # ResolutionUnit: inches
        pil.save(buf, format="JPEG", quality=int(quality), dpi=(dpi, dpi),
                 exif=exif, optimize=True, progressive=False)
    else:
        raise ValueError("不支持的导出格式: %s" % fmt)
    return buf.getvalue()


def _jpeg_pad(data: bytes, target: int) -> Tuple[bytes, int]:
    """在 JPEG 的 EOI 前插入合法 COM 段，保持文件可解码。"""
    if len(data) >= target:
        return data, 0
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("JPEG 缺少有效的 SOI/EOI 标记")
    need = target - len(data)
    chunks = []
    while need > 0:
        size = min(MAX_COM_SEG, max(4, need))
        # Leave at least four bytes for the last COM segment, so a large
        # deficit can be met exactly instead of overshooting by 1–3 bytes.
        remaining = need - size
        if 0 < remaining < 4:
            size -= 4 - remaining
        payload = size - 4
        segment = b"\xff\xfe" + struct.pack(">H", payload + 2) + (b"\x00" * payload)
        chunks.append(segment)
        need -= size
    padded = data[:-2] + b"".join(chunks) + data[-2:]
    return padded, len(padded) - len(data)


def _png_pad(data: bytes, target: int) -> Tuple[bytes, int]:
    """在 IEND 前插入合法块；缺口不足 12 字节时补足最小块长度。"""
    if len(data) >= target:
        return data, 0
    if (not data.startswith(b"\x89PNG\r\n\x1a\n")
            or data[-12:] != b"\x00\x00\x00\x00IEND\xaeB\x60\x82"):
        raise ValueError("PNG 缺少有效的签名或 IEND 块")
    need = target - len(data)
    chunk_size = max(12, need)  # the smallest valid PNG chunk is 12 bytes
    chunk_start = len(data) - 12
    if chunk_size >= 12 + len(b"idphoto-padding") + 1:
        # Exactly one NUL separates the keyword from ASCII text; the text
        # itself deliberately contains no NUL bytes for strict PNG readers.
        keyword = b"idphoto-padding"
        text_size = chunk_size - 12 - len(keyword) - 1
        payload = keyword + b"\x00" + (b"0" * text_size)
        chunk_type = b"tEXt"
    else:
        # paDd is ancillary/private/safe-to-copy and permits arbitrary bytes.
        payload = bytes(chunk_size - 12)
        chunk_type = b"paDd"
    chunk = struct.pack(">I", len(payload)) + chunk_type + payload
    chunk += struct.pack(">I", zlib.crc32(chunk[4:]) & 0xffffffff)
    padded = data[:chunk_start] + chunk + data[chunk_start:]
    return padded, len(padded) - len(data)


def _pad_to_bytes(data: bytes, target: int, fmt: str) -> Tuple[bytes, int]:
    if fmt == "png":
        return _png_pad(data, target)
    if fmt in ("jpg", "jpeg"):
        return _jpeg_pad(data, target)
    raise ValueError("不支持的导出格式: %s" % fmt)


def _fit_quality(img: np.ndarray, fmt: str, dpi: int, upper_bytes: int,
                 lo: int = 5, hi: int = 95) -> Tuple[bytes, int]:
    """二分找到「不超过 upper_bytes」的最高质量。"""
    best_data, best_q = _encode(img, fmt, dpi, lo), lo
    if len(best_data) > upper_bytes:
        return best_data, lo              # 最低质量都放不下，如实返回
    while lo <= hi:
        mid = (lo + hi) // 2
        data = _encode(img, fmt, dpi, mid)
        if len(data) <= upper_bytes:
            best_data, best_q = data, mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best_data, best_q


def resample_to_dpi(img: np.ndarray, mm: Tuple[float, float],
                    dpi: int) -> np.ndarray:
    """把图缩放到「在目标 dpi 下正好是 mm 毫米」的像素数。

    为什么需要它（体检时发现的坑）：规格的 px 是按规格自己的 dpi 定的
    （一寸 295×413px @300dpi = 25×35mm）。用户在「输出设置」里把分辨率改成 600dpi 时，
    如果**只改元数据不改像素**，同一个文件打印出来就只剩 12.5×17.5mm —— 小了一半。
    这里把像素一起缩放，**物理尺寸永远不变**（放大靠插值，不会凭空多出细节）。
    """
    import cv2

    dpi = _number(dpi, "dpi", integer=True)
    if len(mm) != 2:
        raise ValueError("毫米尺寸必须包含宽和高")
    width_mm, height_mm = (_number(v, "毫米尺寸") for v in mm)
    if img is None:
        return img
    want_w = max(1, int(round(width_mm / 25.4 * dpi)))
    want_h = max(1, int(round(height_mm / 25.4 * dpi)))
    h, w = img.shape[0], img.shape[1]
    if w == want_w and h == want_h:
        return img
    interp = cv2.INTER_AREA if (w > want_w or h > want_h) else cv2.INTER_CUBIC
    return cv2.resize(img, (want_w, want_h), interpolation=interp)


def save_image(img: np.ndarray, path: str, dpi: int = 300,
               fmt: Optional[str] = None, quality: Optional[int] = None,
               target_kb: Optional[float] = None,
               max_kb: Optional[float] = None,
               min_kb: Optional[float] = None) -> SaveReport:
    """导出图片，精确控制 dpi 与文件大小。

    target_kb / max_kb 是上限（取二者更小者）；min_kb 是下限。
    返回 SaveReport，含回读到的 dpi 与是否满足大小约束。
    """
    msgs = []
    dpi = _number(dpi, "dpi", integer=True)
    if dpi > 65535:
        raise ValueError("dpi 不能超过 65535")
    if fmt is None:
        fmt = os.path.splitext(path)[1].lstrip(".") or "jpg"
    if not isinstance(fmt, str):
        raise ValueError("导出格式必须是 jpg、jpeg 或 png")
    pil_fmt = {"jpeg": "jpg", "jpe": "jpg"}.get(fmt.lower(), fmt.lower())
    if pil_fmt not in ("jpg", "png"):
        raise ValueError("不支持的导出格式: %s" % fmt)
    used_q = 95 if quality is None else _number(quality, "quality", integer=True)
    if used_q > 100:
        raise ValueError("quality 不能超过 100")

    upper_kb = [_number(value, name) for name, value in
                (("target_kb", target_kb), ("max_kb", max_kb)) if value is not None]
    upper_bytes = (math.floor(_number(min(upper_kb) * 1024, "文件大小上限"))
                   if upper_kb else None)
    lower_bytes = (math.ceil(_number(
        _number(min_kb, "min_kb", allow_zero=True) * 1024,
        "文件大小下限", allow_zero=True)) if min_kb is not None else 0)
    if upper_bytes is not None and (upper_bytes < 1 or lower_bytes > upper_bytes):
        raise ValueError("文件大小下限不能超过上限，且上限必须至少为 1 字节")

    if upper_bytes is not None and pil_fmt == "jpg":
        data, used_q = _fit_quality(img, pil_fmt, dpi, upper_bytes,
                                    lo=min(5, used_q), hi=used_q)
        if len(data) > upper_bytes:
            msgs.append("即使降到最低质量仍超过 %.0fKB 上限，请改用更小的像素尺寸"
                        % (upper_bytes / 1024))
    else:
        data = _encode(img, pil_fmt, dpi, used_q)

    padded = 0
    if len(data) < lower_bytes:
        data, padded = _pad_to_bytes(data, lower_bytes, pil_fmt)
        msgs.append("文件小于 %.0fKB 下限，已用合法格式块填充 %d 字节"
                    % (min_kb, padded))
    if (upper_bytes is not None and len(data) > upper_bytes
            and not any("上限" in message for message in msgs)):
        msgs.append("输出大小超过 %.2fKB 上限" % (upper_bytes / 1024))

    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:       # 路径安全的写（open 支持中文路径）
        f.write(data)

    rb = read_dpi(path)
    fits = True
    if upper_bytes is not None and len(data) > upper_bytes:
        fits = False
    if len(data) < lower_bytes:
        fits = False

    return SaveReport(
        path=path, bytes=len(data), kb=round(len(data) / 1024, 2),
        dpi_written=(dpi, dpi), dpi_readback=rb, quality=used_q,
        padded_bytes=padded, fits_limits=fits, messages=msgs,
    )


def read_dpi(path: str) -> Optional[Tuple[int, int]]:
    """优先读取有效 EXIF 分辨率，退回 JPEG JFIF / PNG pHYs。"""
    def resolution(x, y, factor=1.0):
        try:
            def ratio(value):
                return value[0] / value[1] if isinstance(value, tuple) else float(value)
            values = (ratio(x) * factor, ratio(y) * factor)
            if all(math.isfinite(v) and v > 0 for v in values):
                rounded = tuple(round(v) for v in values)
                if min(rounded) > 0:
                    return rounded
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            pass
        return None

    try:
        with Image.open(path) as im:
            # Some cameras retain a default 72dpi JFIF header while EXIF
            # carries the intended resolution, including fractional values.
            try:
                exif = im.getexif()
                unit = exif.get(296, 2)
                if unit in (2, 3):
                    result = resolution(exif.get(282), exif.get(283),
                                        2.54 if unit == 3 else 1.0)
                    if result:
                        return result
            except (TypeError, ValueError, OSError):
                pass
            d = (im.info or {}).get("dpi")
            if d and len(d) >= 2:
                return resolution(d[0], d[1])
    except Exception:
        return None
    return None


def printed_mm(path: str) -> Optional[Tuple[float, float]]:
    """文件按自身 dpi 打印出来的实际毫米尺寸——用来验证 dpi 有没有写对。"""
    dpi = read_dpi(path)
    if not dpi or dpi[0] == 0:
        return None
    with Image.open(path) as im:
        w, h = im.size
    return (w / dpi[0] * 25.4, h / dpi[1] * 25.4)
