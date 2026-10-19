# -*- coding: utf-8 -*-
"""导出测试：DPI 元数据与文件大小上下限。

这是调研里最容易翻车的地方：把 295×413px 标成 350dpi 打印出来只有 21.4×30.0mm（小 8.5%）；
报名系统还有「不小于 20KB」这种下限要求，20KB 只能承载约 0.06MP，
所以「144×192px 且 ≥20KB」根本无法靠降质量达成，必须合法填充。
"""
import os

import numpy as np
import pytest

from app.core.exporter import (printed_mm, read_dpi, resample_to_dpi,
                               save_image)
from app.core.specs import SpecLibrary

from conftest import OUT_DIR


@pytest.fixture(scope="module")
def lib():
    return SpecLibrary.load()


@pytest.fixture(scope="module", autouse=True)
def outdir():
    os.makedirs(OUT_DIR, exist_ok=True)


def _img(w, h, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def test_print_size_stays_correct_at_any_output_dpi(lib):
    """「输出设置」里换了分辨率，打印出来的毫米尺寸必须还是规格尺寸。

    体检时发现的坑：规格 px 是按规格自己的 dpi 定的（一寸 295×413@300dpi = 25×35mm）。
    如果选 600dpi 时**只改元数据不改像素**，同一张图打印出来只剩 12.5×17.5mm。
    `resample_to_dpi` 把像素一起缩放，物理尺寸永远不变。
    """
    spec = lib.photo("cn_yicun")
    for dpi in (300, 350, 600):
        src = _img(*spec.px_size)                     # 库里就是 300dpi 的像素
        pic = resample_to_dpi(src, spec.mm_size, dpi)
        p = os.path.join(OUT_DIR, "yicun_at_%d.jpg" % dpi)
        save_image(pic, p, dpi=dpi)
        assert read_dpi(p) == (dpi, dpi), (dpi, read_dpi(p))
        w_mm, h_mm = printed_mm(p)
        assert abs(w_mm - 25.0) < 0.3 and abs(h_mm - 35.0) < 0.3, (
            "%d dpi 打出来是 %.1f×%.1fmm，应该还是 25×35mm" % (dpi, w_mm, h_mm))
    # 尺寸没变时不该白折腾一遍（同一对象直接返回）
    assert resample_to_dpi(src, spec.mm_size, 300) is src


def test_dpi_is_written_and_read_back(lib):
    spec = lib.photo("cn_yicun")
    p = os.path.join(OUT_DIR, "yicun_300.jpg")
    rep = save_image(_img(*spec.px_size), p, dpi=300)
    assert rep.dpi_readback == (300, 300), rep.dpi_readback
    assert rep.ok(), rep.messages
    w, h = printed_mm(p)
    assert abs(w - 25.0) < 0.15 and abs(h - 35.0) < 0.15, (w, h)


def test_idcard_350dpi_prints_exactly_26x32mm(lib):
    """身份证这条是 DPI 陷阱的典型：按 300dpi 会打大 15%。"""
    spec = lib.photo("cn_idcard")
    p = os.path.join(OUT_DIR, "idcard_350.jpg")
    save_image(_img(*spec.px_size), p, dpi=spec.dpi)
    assert read_dpi(p) == (350, 350)
    w, h = printed_mm(p)
    assert abs(w - 26.0) < 0.15 and abs(h - 32.0) < 0.15, (w, h)
    # 反证：同一张图若标 300dpi 就会明显偏大
    p300 = os.path.join(OUT_DIR, "idcard_as300.jpg")
    save_image(_img(*spec.px_size), p300, dpi=300)
    w300, _ = printed_mm(p300)
    assert w300 > 29.0, "反证失败：标 300dpi 应打印成约 30.3mm，实得 %.1f" % w300


def test_target_kb_upper_bound():
    p = os.path.join(OUT_DIR, "target40.jpg")
    rep = save_image(_img(295, 413, seed=1), p, dpi=300, target_kb=40)
    assert rep.bytes <= 40 * 1024, rep.bytes
    assert rep.fits_limits
    assert rep.quality is not None


def test_min_kb_lower_bound_is_padded():
    """小图 + 下限要求：必须靠合法填充达标，不能靠降质量。

    用低熵图（近乎纯色）保证压出来明显小于 20KB，否则这条测试测不到填充逻辑。
    """
    p = os.path.join(OUT_DIR, "min20.jpg")
    flat = np.full((192, 144, 3), 120, np.uint8)
    flat[60:130, 40:100] = 200
    rep = save_image(flat, p, dpi=300, min_kb=20)
    assert rep.bytes >= 20 * 1024, rep.bytes
    assert rep.padded_bytes > 0, "没有触发填充：%r" % (rep,)
    # 填充后仍是能正常解码的 JPEG，且 dpi 没被冲掉
    assert read_dpi(p) == (300, 300)
    from PIL import Image
    with Image.open(p) as im:
        assert im.size == (144, 192)


def test_both_bounds_together():
    """NCRE 那类「20~200KB」的双向约束。"""
    p = os.path.join(OUT_DIR, "both.jpg")
    rep = save_image(_img(192, 144, seed=3), p, dpi=300, min_kb=20, max_kb=200)
    assert 20 * 1024 <= rep.bytes <= 200 * 1024, rep.bytes
    assert rep.fits_limits


def test_dpi_survives_compression_and_padding():
    """顺序铁律：先压缩、再写 EXIF、最后填充——反过来 dpi 会被冲掉。"""
    p = os.path.join(OUT_DIR, "dpi_survive.jpg")
    save_image(_img(600, 600, seed=4), p, dpi=350, min_kb=60)
    assert read_dpi(p) == (350, 350)
    assert os.path.getsize(p) >= 60 * 1024


def test_png_export_keeps_alpha_and_dpi():
    img = np.zeros((413, 295, 4), np.uint8)
    img[:, :, 0] = 200
    img[:, :, 3] = 255
    p = os.path.join(OUT_DIR, "alpha.png")
    rep = save_image(img, p, dpi=300, fmt="png")
    assert os.path.exists(p)
    assert rep.dpi_readback == (300, 300), rep.dpi_readback
    from PIL import Image
    with Image.open(p) as im:
        assert im.mode == "RGBA"


def test_chinese_path_roundtrip():
    """中文路径必须能写能读（cv2.imwrite 在这里会静默失败）。"""
    p = os.path.join(OUT_DIR, "中文文件名_一寸.jpg")
    rep = save_image(_img(295, 413, seed=5), p, dpi=300)
    assert os.path.exists(p) and rep.bytes > 2000
    assert read_dpi(p) == (300, 300)


def test_reports_failure_when_limit_impossible():
    """像素太大又卡很死的上限时，必须如实报告放不下，而不是假装成功。"""
    p = os.path.join(OUT_DIR, "impossible.jpg")
    rep = save_image(_img(2000, 2000, seed=6), p, dpi=300, max_kb=5)
    assert rep.fits_limits is False
    assert rep.messages
