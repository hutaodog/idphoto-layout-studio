"""Deterministic crop/source and inference-lock checks, independent of model files."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.core.pipeline import (ManualTransform, PipelineError, Processor,
                               _warp_crop_to_size, crop_to_spec)
from app.core.specs import SpecLibrary


def source_image():
    y, x = np.indices((100, 80))
    return np.dstack((x + 20, y + 30, (x + y) // 2 + 50)).astype(np.uint8)


def test_direct_warp_identity_keeps_pixel_centers():
    src = source_image()
    actual = _warp_crop_to_size(src, 80, 100, (40, 50), (80, 100))
    np.testing.assert_array_equal(actual, src)


def test_original_uses_source_pixels_and_exact_crop_geometry():
    src = source_image()
    spec = replace(SpecLibrary.load().photo("cn_yicun"), px=(60, 80))
    matting = np.zeros((100, 80, 4), np.uint8)  # alpha RGB deliberately unlike source
    transform = ManualTransform(head_ratio=0.5, center_y=0.5)
    actual = crop_to_spec(matting, spec, (30, 30, 20, 40), transform,
                          source_bgr=src, preserve_original=True)
    np.testing.assert_array_equal(actual, src[10:90, 10:70])
    assert actual.shape == (80, 60, 3)
    solid = crop_to_spec(matting, spec, (30, 30, 20, 40), transform, (5, 10, 15))
    np.testing.assert_array_equal(solid, np.full_like(solid, (5, 10, 15)))


@pytest.mark.parametrize("rotate", [0, 13, -30])
def test_source_and_opaque_matting_share_manual_transforms(rotate):
    src = source_image()
    rgba = np.dstack((src, np.full(src.shape[:2], 255, np.uint8)))
    spec = SpecLibrary.load().photo("cn_yicun")
    transform = ManualTransform(zoom=.7, offset_x=.11, offset_y=-.13, rotate=rotate)
    source = crop_to_spec(rgba, spec, (20, 15, 25, 35), transform,
                         source_bgr=src, preserve_original=True)
    alpha = crop_to_spec(rgba, spec, (20, 15, 25, 35), transform)
    np.testing.assert_array_equal(source, alpha)
    transparent = crop_to_spec(rgba, spec, None, transform, bg_bgr=None)
    assert transparent.shape == (*spec.hw, 4)


def test_zoom_minimum_only_allocates_output_sized_warp(monkeypatch):
    src = source_image()
    rgba = np.dstack((src, np.full(src.shape[:2], 255, np.uint8)))
    sizes = []
    real_warp = cv2.warpAffine
    def warp(image, matrix, size, **kwargs):
        sizes.append((image.shape, size))
        return real_warp(image, matrix, size, **kwargs)
    monkeypatch.setattr(cv2, "warpAffine", warp)
    def forbidden(*args, **kw):
        raise AssertionError("large intermediate crop/resize must not be allocated")
    monkeypatch.setattr(cv2, "getRectSubPix", forbidden)
    monkeypatch.setattr(cv2, "resize", forbidden)
    spec = SpecLibrary.load().photo("cn_yicun")
    out = crop_to_spec(rgba, spec, (20, 15, 25, 75), ManualTransform(zoom=0),
                       source_bgr=src, preserve_original=True)
    assert out.shape == (*spec.hw, 3)
    assert sizes == [(src.shape, spec.px_size)]
    assert out.min() >= src.min()  # out-of-source padding replicates existing border


def test_nonfinite_manual_parameters_are_sanitized():
    src = source_image()
    rgba = np.dstack((src, np.zeros(src.shape[:2], np.uint8)))
    invalid = ManualTransform(zoom=float("nan"), head_ratio=float("inf"),
                              offset_x="bad", offset_y=float("nan"),
                              rotate=None, center_y=float("-inf"))
    spec = SpecLibrary.load().photo("cn_yicun")
    expected = crop_to_spec(rgba, spec, None, ManualTransform(), source_bgr=src,
                            preserve_original=True)
    actual = crop_to_spec(rgba, spec, None, invalid, source_bgr=src,
                          preserve_original=True)
    np.testing.assert_array_equal(actual, expected)


def test_original_mode_rejects_missing_or_misaligned_source():
    rgba = np.zeros((100, 80, 4), np.uint8)
    spec = SpecLibrary.load().photo("cn_yicun")
    for source in (None, np.zeros((50, 40, 3), np.uint8)):
        with pytest.raises(PipelineError, match="原图"):
            crop_to_spec(rgba, spec, None, ManualTransform(), source_bgr=source,
                          preserve_original=True)


def test_hollow_option_is_serialized_and_environment_is_restored(monkeypatch):
    proc = Processor()
    spec = proc.lib.photo("cn_yicun")
    src = source_image()
    entered, release = threading.Event(), threading.Event()
    seen = []
    def creator(image, **kw):
        current = os.environ.get("IDPHOTO_HOLLOW_FIX")
        seen.append(current)
        if len(seen) == 1:
            entered.set()
            assert release.wait(4)
        assert os.environ.get("IDPHOTO_HOLLOW_FIX") == current
        standard = np.zeros((*spec.hw, 4), np.uint8)
        return SimpleNamespace(standard=standard, matting=np.zeros((100,80,4), np.uint8),
                               face=None, original_standard=cv2.resize(src, spec.px),
                               original_source=src)
    monkeypatch.setenv("IDPHOTO_HOLLOW_FIX", "existing-value")
    monkeypatch.setattr(proc, "weights_ready", lambda: True)
    monkeypatch.setattr(proc, "_ensure_creator", lambda: creator)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(proc.process, src, spec, None, True)
        assert entered.wait(4)
        second = pool.submit(proc.process, src, spec, None, False)
        release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert seen == ["1", "0"]
    assert os.environ["IDPHOTO_HOLLOW_FIX"] == "existing-value"
    def broken(*args, **kwargs):
        raise RuntimeError("inference error")
    monkeypatch.setattr(proc, "_ensure_creator", lambda: broken)
    with pytest.raises(PipelineError, match="inference error"):
        proc.process(src, spec, None, False)
    assert os.environ["IDPHOTO_HOLLOW_FIX"] == "existing-value"
