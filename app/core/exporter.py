# -*- coding: utf-8 -*-
"""导出：精确控制 DPI 元数据与文件大小。

这里集中了调研里最容易翻车的两件事：
1. **DPI 元数据**：把 295×413px 标成 350dpi 打印出来只有 21.4×30.0mm（小 8.5%）；
   身份证 358×441px 若按 300dpi 打印是 30.3×37.3mm（比标准 26×32mm 大 15%）。
   因此 DPI 必须逐张写入并**回读校验**。
2. **文件大小有下限**：报名系统不只卡上限（≤200KB），还有下限（≥20KB）。
   20KB 只能承载约 0.06MP，所以「144×192px 且 ≥20KB」无法靠降质量达成，必须合法填充。

顺序铁律：**先压缩、再写 EXIF、最后填充**（反过来重新压缩会把 DPI 元数据冲掉）。
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import piexif
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


def _to_pil(img: np.ndarray) -> Image.Image:
    """BGR / BGRA ndarray -> PIL Image（RGB / RGBA）。"""
    arr = to_uint8(img)
    if arr.ndim == 2:
        return Image.fromarray(arr, mode="L").convert("RGB")
    if arr.shape[2] == 4:
        return Image.fromarray(arr[:, :, [2, 1, 0, 3]], mode="RGBA")
    if arr.shape[2] == 3:
        return Image.fromarray(arr[:, :, ::-1], mode="RGB")
    raise ValueError("不支持的图像形状: %r" % (arr.shape,))


def _exif_bytes(dpi: int) -> bytes:
    exif_dict = {
        "0th": {
            piexif.ImageIFD.XResolution: (int(dpi), 1),
            piexif.ImageIFD.YResolution: (int(dpi), 1),
            piexif.ImageIFD.ResolutionUnit: 2,       # 2 = 英寸
            piexif.ImageIFD.Software: "IDPhotoStudio",
        },
        "Exif": {},
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    return piexif.dump(exif_dict)


def _encode(img: np.ndarray, fmt: str, dpi: int, quality: int = 95) -> bytes:
    pil = _to_pil(img)
    buf = io.BytesIO()
    if fmt == "png":
        pil.save(buf, format="PNG", dpi=(dpi, dpi))
    else:
        if pil.mode == "RGBA":
            pil = pil.convert("RGB")
        pil.save(buf, format="JPEG", quality=int(quality), dpi=(dpi, dpi),
                 optimize=True, progressive=False)
    data = buf.getvalue()
    # 先压缩，再写 EXIF
    try:
        data = piexif.insert(_exif_bytes(dpi), data)
    except Exception:
        pass  # EXIF 写入失败不阻断导出（JFIF 里已有 dpi）
    return data


def _pad_to_bytes(data: bytes, target: int) -> Tuple[bytes, int]:
    """在 EOI 之前插入合法的 COM 注释段把文件撑到目标字节数（永不欠账）。"""
    if len(data) >= target:
        return data, 0
    need = target - len(data)
    eoi = data.rfind(b"\xff\xd9")
    if eoi == -1:
        body, tail = data, b""
    else:
        body, tail = data[:eoi], data[eoi:]

    segs, remaining = [], need
    while remaining > 0:
        take = min(remaining, MAX_COM_SEG)
        if take < 4:
            take = 4                      # 不足 4 字节无法构成合法段，宁可超出几字节
        payload = take - 4
        segs.append(b"\xff\xfe" + (payload + 2).to_bytes(2, "big") + b"\x00" * payload)
        remaining -= take
    padded = body + b"".join(segs) + tail
    return padded, len(padded) - len(data)


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

    if img is None:
        return img
    want_w = max(1, int(round(mm[0] / 25.4 * dpi)))
    want_h = max(1, int(round(mm[1] / 25.4 * dpi)))
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
    fmt = (fmt or os.path.splitext(path)[1].lstrip(".") or "jpg").lower()
    fmt = {"jpeg": "jpg", "jpe": "jpg"}.get(fmt, fmt)
    pil_fmt = "png" if fmt == "png" else "jpg"

    upper_kb = [v for v in (target_kb, max_kb) if v]
    upper_bytes = int(min(upper_kb) * 1024) if upper_kb else None

    if upper_bytes is not None and pil_fmt == "jpg":
        data, used_q = _fit_quality(img, pil_fmt, dpi, upper_bytes,
                                    lo=5, hi=min(95, quality or 95))
        if len(data) > upper_bytes:
            msgs.append("即使降到最低质量仍超过 %.0fKB 上限，请改用更小的像素尺寸"
                        % (upper_bytes / 1024))
    else:
        used_q = quality or 95
        data = _encode(img, pil_fmt, dpi, used_q)

    padded = 0
    if min_kb:
        if len(data) < int(min_kb * 1024):
            data, padded = _pad_to_bytes(data, int(min_kb * 1024))
            msgs.append("文件小于 %.0fKB 下限，已用合法注释段填充 %d 字节"
                        % (min_kb, padded))

    with open(path, "wb") as f:       # 路径安全的写（open 支持中文路径）
        f.write(data)

    rb = read_dpi(path)
    fits = True
    if upper_bytes is not None and len(data) > upper_bytes:
        fits = False
    if min_kb and len(data) < int(min_kb * 1024):
        fits = False

    return SaveReport(
        path=path, bytes=len(data), kb=round(len(data) / 1024, 2),
        dpi_written=(dpi, dpi), dpi_readback=rb, quality=used_q,
        padded_bytes=padded, fits_limits=fits, messages=msgs,
    )


def read_dpi(path: str) -> Optional[Tuple[int, int]]:
    """回读文件里的 dpi。先看 EXIF，再退回 JFIF。"""
    try:
        with Image.open(path) as im:
            info = im.info or {}
            try:
                ex = piexif.load(path)
                xr = ex.get("0th", {}).get(piexif.ImageIFD.XResolution)
                yr = ex.get("0th", {}).get(piexif.ImageIFD.YResolution)
                if xr and yr:
                    unit = ex.get("0th", {}).get(piexif.ImageIFD.ResolutionUnit, 2)
                    x = xr[0] / xr[1] if isinstance(xr, tuple) else float(xr)
                    y = yr[0] / yr[1] if isinstance(yr, tuple) else float(yr)
                    if unit == 3:          # 厘米 -> 英寸
                        x, y = x * 2.54, y * 2.54
                    return (round(x), round(y))
            except Exception:
                pass
            d = info.get("dpi")
            if d:
                return (round(d[0]), round(d[1]))
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
