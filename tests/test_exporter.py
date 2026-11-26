# -*- coding: utf-8 -*-
"""导出测试：DPI 元数据与文件大小上下限。

这是调研里最容易翻车的地方：把 295×413px 标成 350dpi 打印出来只有 21.4×30.0mm（小 8.5%）；
报名系统还有「不小于 20KB」这种下限要求，20KB 只能承载约 0.06MP，
所以「144×192px 且 ≥20KB」根本无法靠降质量达成，必须合法填充。
"""
import os
import struct
import zlib

import numpy as np
import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

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


@pytest.mark.parametrize("deficit", [1, 3, 11, 12, 13, 27, 28, 65538])
def test_png_padding_is_valid_with_tiny_deficit(tmp_path, deficit):
    """Validate every CRC and chunk position, including deficits below 12 bytes."""
    from app.core.exporter import _encode, _png_pad

    img = np.full((12, 13, 3), 90, np.uint8)
    data = _encode(img, "png", 300)
    padded, amount = _png_pad(data, len(data) + deficit)
    assert amount == max(12, deficit)
    assert padded[-12:] == data[-12:]  # original IEND stays last
    chunks = _png_chunks(padded)
    assert chunks[-1] == (b"IEND", b"")
    kind, payload = chunks[-2]
    if deficit < 28:
        assert kind == b"paDd" and payload == bytes(max(12, deficit) - 12)
    else:
        assert kind == b"tEXt"
        assert payload.count(b"\x00") == 1
        assert payload.startswith(b"idphoto-padding\x00")
    path = tmp_path / "tiny.png"
    path.write_bytes(padded)
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        im.load()
        assert im.size == (13, 12)
        assert im.info["dpi"] == pytest.approx((300, 300), abs=0.5)


def test_png_export_keeps_alpha_and_dpi():
    img = np.zeros((413, 295, 4), np.uint8)
    img[:, :, 0] = 200
    img[:, :, 3] = np.linspace(0, 255, 295, dtype=np.uint8)
    p = os.path.join(OUT_DIR, "alpha.png")
    rep = save_image(img, p, dpi=300, fmt="png")
    assert os.path.exists(p)
    assert rep.dpi_readback == (300, 300), rep.dpi_readback
    from PIL import Image
    with Image.open(p) as im:
        assert im.mode == "RGBA"
        assert np.array_equal(np.asarray(im), img[:, :, [2, 1, 0, 3]])


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


def _png_chunks(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks = []
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        end = offset + 12 + length
        assert end <= len(data)
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[end - 4:end])[0]
        assert crc == zlib.crc32(kind + payload) & 0xffffffff
        chunks.append((kind, payload))
        offset = end
        if kind == b"IEND":
            assert offset == len(data), "padding must precede IEND"
    assert offset == len(data)
    return chunks


@pytest.mark.parametrize("suffix", ["jpg", "png"])
def test_encoded_dpi_metadata_matches_pillow_and_raw_headers(tmp_path, suffix):
    path = tmp_path / "nested" / "中文" / ("metadata." + suffix)
    rep = save_image(_img(24, 36), path, dpi=350)
    assert rep.ok() and rep.dpi_written == rep.dpi_readback == (350, 350)
    with Image.open(path) as im:
        im.load()
        assert im.info["dpi"] == pytest.approx((350, 350), abs=0.02)
        if suffix == "jpg":
            assert im.info["jfif_unit"] == 1
            assert im.info["jfif_density"] == (350, 350)
            exif = im.getexif()
            assert (float(exif[282]), float(exif[283]), exif[296]) == (350, 350, 2)
    if suffix == "png":
        phys = dict(_png_chunks(path.read_bytes()))[b"pHYs"]
        assert struct.unpack(">IIB", phys) == (round(350 / 0.0254),
                                               round(350 / 0.0254), 1)


@pytest.mark.parametrize("unit,x,y,expected", [
    (2, IFDRational(1505, 4), IFDRational(1401, 4), (376, 350)),
    (3, IFDRational(15000, 127), IFDRational(17500, 127), (300, 350)),
])
def test_read_dpi_uses_fractional_exif_over_default_jfif(tmp_path, unit, x, y, expected):
    path = tmp_path / "external.jpg"
    exif = Image.Exif()
    exif[282], exif[283], exif[296] = x, y, unit
    Image.new("RGB", (30, 20), "white").save(path, dpi=(72, 72), exif=exif)
    with Image.open(path) as im:
        assert im.info["jfif_density"] == (72, 72)
    assert read_dpi(path) == expected


def test_read_dpi_falls_back_to_jfif_without_exif(tmp_path):
    path = tmp_path / "jfif_only.jpg"
    Image.new("RGB", (30, 20)).save(path, dpi=(300, 350))
    assert read_dpi(path) == (300, 350)


def test_jpeg_composites_bgra_alpha_onto_white(tmp_path):
    bgra = np.zeros((32, 96, 4), np.uint8)
    bgra[:, 32:64] = (0, 0, 200, 128)
    bgra[:, 64:] = (0, 0, 200, 255)
    path = tmp_path / "alpha.jpg"
    assert save_image(bgra, path).ok()
    with Image.open(path) as im:
        pixels = np.asarray(im)
        assert im.mode == "RGB"
    assert pixels[16, 16] == pytest.approx((255, 255, 255), abs=2)
    assert pixels[16, 48] == pytest.approx((227, 127, 127), abs=3)
    assert pixels[16, 80] == pytest.approx((200, 0, 0), abs=3)


@pytest.mark.parametrize("deficit", [1, 4, 65538, 65539, 65540, 131078])
def test_jpeg_padding_uses_valid_com_segments_before_eoi(tmp_path, deficit):
    from app.core.exporter import _encode, _jpeg_pad

    data = _encode(np.full((8, 9, 3), 90, np.uint8), "jpg", 300)
    padded, amount = _jpeg_pad(data, len(data) + deficit)
    assert amount == max(4, deficit)
    offset = len(data) - 2
    assert padded[:offset] == data[:-2]
    while offset < len(padded) - 2:
        assert padded[offset:offset + 2] == b"\xff\xfe"
        length = struct.unpack(">H", padded[offset + 2:offset + 4])[0]
        assert 2 <= length <= 65535
        offset += 2 + length
    assert offset == len(padded) - 2 and padded[offset:] == b"\xff\xd9"
    path = tmp_path / "padded.jpg"
    path.write_bytes(padded)
    with Image.open(path) as im:
        im.load()
        assert im.size == (9, 8)
    assert read_dpi(path) == (300, 300)


def test_png_tiny_padding_cannot_claim_impossible_exact_range(tmp_path):
    from app.core.exporter import _encode

    image = np.full((8, 9, 3), 90, np.uint8)
    limit = (len(_encode(image, "png", 300)) + 1) / 1024
    report = save_image(image, tmp_path / "limited.png", min_kb=limit, max_kb=limit)
    assert report.padded_bytes == 12
    assert not report.fits_limits and not report.ok()
    assert any("上限" in message for message in report.messages)


def test_single_image_uses_stricter_target_and_spec_maximum(tmp_path):
    image = _img(295, 413, seed=21)
    for target, maximum in ((80, 24), (24, 80)):
        report = save_image(image, tmp_path / ("limit_%d.jpg" % target),
                            target_kb=target, max_kb=maximum, min_kb=20)
        assert 20 * 1024 <= report.bytes <= 24 * 1024
        assert report.ok()


@pytest.mark.parametrize("suffix,options", [
    ("bmp", {}), ("jpg", {"fmt": "gif"}), ("jpg", {"fmt": ""}),
    ("jpg", {"fmt": 123}), ("jpg", {"max_kb": -1}),
    ("jpg", {"target_kb": 0}), ("jpg", {"min_kb": -1}),
    ("jpg", {"max_kb": float("nan")}), ("jpg", {"max_kb": float("inf")}),
    ("jpg", {"min_kb": float("nan")}), ("jpg", {"min_kb": float("inf")}),
    ("jpg", {"max_kb": 1e308}),
    ("jpg", {"target_kb": "20"}), ("jpg", {"max_kb": True}),
    ("jpg", {"min_kb": 21, "max_kb": 20}),
    ("jpg", {"min_kb": 21, "target_kb": 20}),
    ("jpg", {"dpi": 0}), ("jpg", {"dpi": 300.5}), ("jpg", {"dpi": 65536}),
    ("jpg", {"quality": 0}), ("jpg", {"quality": 101}),
])
def test_export_rejects_invalid_format_and_limits_before_writing(tmp_path, suffix, options):
    path = tmp_path / "must_not_be_created" / ("bad." + suffix)
    with pytest.raises(ValueError):
        save_image(np.zeros((8, 8, 3), np.uint8), path, **options)
    assert not path.parent.exists()
