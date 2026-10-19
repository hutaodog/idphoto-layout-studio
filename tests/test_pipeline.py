# -*- coding: utf-8 -*-
"""内核封装与端到端测试：抠图 → 换底 → 裁剪 → 排版 → 导出。

需要 app/vendor/hivision/creator/weights/hivision_modnet.onnx（24.7MB）。
权重缺失时整组跳过（而不是假装通过）。
"""
import os

import numpy as np
import pytest

from app.core.exporter import printed_mm, read_dpi, save_image
from app.core.io_compat import imread, imwrite
from app.core.layout import plan_layout, render_layout
from app.core.pipeline import ManualTransform, Processor, PipelineError, load_photo
from app.core.specs import SpecLibrary

from conftest import DEMO_IMAGE, OUT_DIR

pytestmark = pytest.mark.skipif(
    not Processor.weights_ready(),
    reason="抠图权重缺失，先运行 scripts\\download_weights.ps1",
)


@pytest.fixture(scope="module")
def lib():
    return SpecLibrary.load()


@pytest.fixture(scope="module")
def proc(lib):
    return Processor(lib=lib)


@pytest.fixture(scope="module", autouse=True)
def outdir():
    os.makedirs(OUT_DIR, exist_ok=True)


@pytest.fixture(scope="module")
def demo_img():
    if not os.path.exists(DEMO_IMAGE):
        pytest.skip("演示图不存在：%s" % DEMO_IMAGE)
    img = imread(DEMO_IMAGE)
    assert img is not None
    return img


def test_vendor_imports_without_gradio():
    """PATCH-1/2：不装 gradio 也要能 import 内核，且不能拉起 grind_skin。"""
    import sys
    import hivision  # noqa: F401
    assert "hivision.plugin.beauty.grind_skin" not in sys.modules


def test_weights_path_matches_where_upstream_looks():
    """权重探测路径必须和上游 human_matting.py 实际使用的位置一致。

    打包后 hivision 包会被放到 _MEIPASS 顶层而不是 app/vendor 下，
    如果这里写死源码目录，冻结版就会报「权重缺失」——这个 bug 真的发生过。
    """
    import hivision.creator as creator_pkg
    upstream_dir = os.path.join(os.path.dirname(os.path.abspath(creator_pkg.__file__)),
                                "weights")
    assert os.path.dirname(Processor.weights_path()) == upstream_dir, (
        "探测路径 %s 与上游实际使用的 %s 不一致"
        % (os.path.dirname(Processor.weights_path()), upstream_dir))
    assert Processor.weights_ready()


def test_pipeline_produces_exact_spec_size(proc, lib, demo_img):
    spec = lib.photo("cn_yicun")
    res = proc.process(demo_img, spec, bg="blue")
    assert res.size == spec.px_size, res.size
    assert res.standard_bgr.dtype == np.uint8
    assert res.standard_bgr.shape[2] == 3, "换底后应是 3 通道 BGR"
    assert res.face_rect is not None, "没有检测到人脸框"


def test_pipeline_detects_face_inside_image(proc, lib, demo_img):
    res = proc.process(demo_img, lib.photo("cn_dayicun"), bg="white")
    x, y, w, h = res.face_rect
    assert w > 0 and h > 0
    mh, mw = res.matting_bgra.shape[:2]
    assert 0 <= x < mw and 0 <= y < mh


def test_landscape_spec(proc, lib, demo_img):
    """横版规格（结婚证 626×413）也要能出图。"""
    spec = lib.photo("cn_marriage")
    res = proc.process(demo_img, spec, bg="red")
    assert res.size == (626, 413), res.size


def test_background_color_is_applied(proc, lib, demo_img):
    spec = lib.photo("cn_yicun")
    blue = proc.process(demo_img, spec, bg="blue").standard_bgr
    white = proc.process(demo_img, spec, bg="white").standard_bgr
    assert not np.array_equal(blue, white)
    # 四角应当接近所选底色
    corner_b = blue[2, 2].astype(int)
    assert abs(corner_b[0] - 206) < 40 and abs(corner_b[1] - 139) < 40, corner_b


def test_matting_is_reusable_for_recrop(proc, lib, demo_img):
    """手动微调不重跑模型：同一份抠图反复重裁，结果必须随之变化。"""
    spec = lib.photo("cn_yicun")
    res = proc.process(demo_img, spec, bg="white")
    base = proc.recrop(res, ManualTransform())
    zoomed = proc.recrop(res, ManualTransform(zoom=1.6))
    moved = proc.recrop(res, ManualTransform(offset_y=0.12))
    for a in (base, zoomed, moved):
        assert a.shape[:2] == (413, 295)
        assert a.dtype == np.uint8
    assert not np.array_equal(base, zoomed), "缩放没有生效"
    assert not np.array_equal(base, moved), "平移没有生效"


def test_rotation_changes_result(proc, lib, demo_img):
    spec = lib.photo("cn_yicun")
    res = proc.process(demo_img, spec, bg="white")
    a = proc.recrop(res, ManualTransform(rotate=0.0))
    b = proc.recrop(res, ManualTransform(rotate=5.0))
    assert not np.array_equal(a, b)


def test_end_to_end_export_and_layout(proc, lib, demo_img):
    """命令行那条路径：出单张 + 出 6 寸排版照，并校验尺寸与 dpi。"""
    spec, paper = lib.photo("cn_yicun"), lib.paper("6inch")
    res = proc.process(demo_img, spec, bg="blue")
    single_path = os.path.join(OUT_DIR, "01_e2e_single.jpg")
    rep = save_image(res.standard_bgr, single_path, dpi=spec.dpi, target_kb=40)
    assert rep.ok(), rep.messages
    w_mm, h_mm = printed_mm(single_path)
    assert abs(w_mm - 25.0) < 0.15 and abs(h_mm - 35.0) < 0.15

    plan = plan_layout(paper.px_at(300), spec.px_size, dpi=300)
    assert plan.count == 12, plan.count
    canvas = render_layout(res.standard_bgr, plan, crop_line="cross")
    layout_path = os.path.join(OUT_DIR, "02_e2e_layout_6inch.jpg")
    save_image(canvas, layout_path, dpi=300)
    assert read_dpi(layout_path) == (300, 300)
    back = imread(layout_path)
    assert back.shape[:2] == (1795, 1205), back.shape


def test_hollow_fix_toggle_changes_or_keeps_output(proc, lib, demo_img):
    """PATCH-4：开关必须真的接上了（默认开启；关掉后结果可以是相同或不同，但不能报错）。"""
    spec = lib.photo("cn_yicun")
    on = proc.process(demo_img, spec, bg="white", hollow_fix=True).standard_bgr
    off = proc.process(demo_img, spec, bg="white", hollow_fix=False).standard_bgr
    assert on.shape == off.shape


def test_missing_weights_message_is_actionable(monkeypatch):
    p = Processor()
    monkeypatch.setattr(Processor, "weights_ready", classmethod(lambda cls: False))
    with pytest.raises(PipelineError) as ei:
        p.process(np.zeros((300, 300, 3), np.uint8), SpecLibrary.load().photo("cn_yicun"))
    assert "download_weights" in str(ei.value)


def test_load_photo_reports_bad_path():
    with pytest.raises(PipelineError):
        load_photo(os.path.join(OUT_DIR, "definitely_missing.jpg"))
