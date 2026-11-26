# -*- coding: utf-8 -*-
"""排版引擎测试：张数必须逐条对上，公式里的 +gap 不能少。

这些数字是整段工作的硬指标。上游 HivisionIDPhotos 因为把行列搜索空间写死成
range(1,4)/range(1,9)，A4 上 1 寸照只排得出 21 张；本引擎的正确值是 50 张。
"""
import numpy as np
import pytest

from app.core.layout import (DEFAULT_GAP_MM, DEFAULT_MARGIN_MM, compute_grid,
                             plan_for_spec, plan_layout, render_layout,
                             smallest_paper_for)
from app.core.specs import SpecLibrary, mm_to_px

# 期望值：gap=2mm、margin=3mm，**纸和照片都按规格自己的 dpi** 换算（plan_for_spec）。
# 来源：调研报告 research/03-specs.md 表 3，已用「不转置 / 转置取最大」重算确认。
# 注意身份证是 350dpi 规格：以前纸按 300dpi、照片却按 350dpi 的像素算，6 寸只排 9 张，
# 实际能排 12 张（这就是"两个一寸一个 9 张一个 12 张"的同一个 bug）。
EXPECTED = {
    ("cn_yicun", "5inch"): 9,
    ("cn_yicun", "6inch"): 12,
    ("cn_yicun", "7inch"): 18,
    ("cn_yicun", "A4"): 50,
    ("cn_yicun", "A3"): 110,
    ("cn_ercun", "5inch"): 4,
    ("cn_ercun", "6inch"): 4,
    ("cn_ercun", "7inch"): 9,
    ("cn_dayicun", "5inch"): 4,      # 33×48mm（原来的「小二寸」已并入大一寸）
    ("cn_dayicun", "6inch"): 4,
    ("cn_dayicun", "7inch"): 9,
    ("cn_xiaoyicun", "6inch"): 16,   # 22×32mm
    ("visa_us", "5inch"): 2,
    ("visa_us", "6inch"): 2,
    ("visa_us", "7inch"): 6,
    ("cn_idcard", "5inch"): 9,
    ("cn_idcard", "6inch"): 12,
    ("cn_idcard", "7inch"): 20,
}


@pytest.fixture(scope="module")
def lib():
    return SpecLibrary.load()


def test_formula_requires_plus_gap_in_numerator():
    """分子里少了 +gap 就会少数一张，这是最容易写错的一处。"""
    # 纸 1000px，照片 300px，间距 20px，留边 10px
    cols, rows = compute_grid((1000, 1000), (300, 300), 20, 10)
    assert cols == 3, cols          # (1000-20+20)//(300+20) = 3
    assert rows == 3, rows
    # 用漏掉 +gap 的错误公式会得到 (1000-20)//320 = 3 —— 换一组能区分的数字
    cols2, _ = compute_grid((1000, 1000), (310, 310), 20, 10)
    assert cols2 == 3, cols2        # (1000-20+20)//330 = 3；错误公式 (980)//330 = 2


@pytest.mark.parametrize("key,expected", sorted(EXPECTED.items()))
def test_expected_counts(lib, key, expected):
    spec_id, paper_id = key
    spec = lib.photo(spec_id)
    paper = lib.paper(paper_id)
    plan = plan_for_spec(paper, spec, gap_mm=DEFAULT_GAP_MM,
                         margin_mm=DEFAULT_MARGIN_MM)
    assert plan.count == expected, (
        "%s 排 %s 期望 %d 张，实得 %d 张（%d×%d）%s"
        % (spec.name_zh, paper.name_zh, expected, plan.count,
           plan.cols, plan.rows, " 旋转" if plan.rotated else ""))


def test_same_physical_size_gives_same_count(lib):
    """**物理尺寸相同的规格，在任何相纸上张数必须一模一样**（与 dpi 无关）。

    用户的原始反馈："这两个一寸为什么不一样呢？一个是 9 张，一个是 12 张。"
    当时库里有一寸（300dpi, 295×413px）和一寸（350dpi 打印）（350dpi, 344×482px）两条，
    都是 25×35mm；旧代码固定拿 `paper.px_at(300)` 当纸、却用规格自带的像素当照片，
    等于把 350dpi 那条当成 29.1×40.8mm 的照片，6 寸纸上只排 9 张。

    v1.5.5 起这种"同尺寸不同 dpi"的重复规格已经从库里删掉了（用户要求去重），
    所以这里**自己造一条 350dpi 的同尺寸规格**来守住这个性质。
    """
    from app.core.specs import PhotoSpec

    a = lib.photo("cn_yicun")
    b = PhotoSpec(id="synthetic_350", name_zh="一寸（350dpi）", category="测试",
                  mm=a.mm, dpi=350,
                  px=(mm_to_px(a.mm[0], 350), mm_to_px(a.mm[1], 350)),
                  bg=("white",), source="测试用", confidence="B")
    assert a.mm_size == b.mm_size, "这两条规格的毫米尺寸必须相同，测试前提变了"
    assert a.px != b.px, "两条规格的像素数应该不同（一个 300dpi 一个 350dpi）"
    for paper in lib.papers:
        pa = plan_for_spec(paper, a)
        pb = plan_for_spec(paper, b)
        assert pa.count == pb.count, (
            "%s 上「%s」排 %d 张，「%s」排 %d 张 —— 物理尺寸一样却排得不一样"
            % (paper.name_zh, a.name_zh, pa.count, b.name_zh, pb.count))
    assert plan_for_spec(lib.paper("6inch"), b).count == 12


def test_plan_for_spec_uses_one_ruler_for_paper_and_photo(lib):
    """排版用的纸和照片必须同一个 dpi：照片阵块换算回毫米要正好等于规格毫米。"""
    for spec_id in ("cn_yicun", "cn_idcard", "cn_ercun", "cn_sancun", "visa_uk_online"):
        spec = lib.photo(spec_id)
        paper = lib.paper("6inch")
        plan = plan_for_spec(paper, spec)
        assert plan.dpi == spec.dpi, (spec_id, plan.dpi, spec.dpi)
        assert plan.paper_px == paper.px_at(spec.dpi), (spec_id, plan.paper_px)
        # 排版可能把照片转 90°（横版排得更省纸），所以比"宽高集合"而不是逐轴比
        got = sorted((round(plan.photo_px[0] / plan.dpi * 25.4, 2),
                      round(plan.photo_px[1] / plan.dpi * 25.4, 2)))
        want = sorted((spec.mm_size[0], spec.mm_size[1]))
        assert abs(got[0] - want[0]) < 0.35 and abs(got[1] - want[1]) < 0.35, (
            spec_id, got, want)
        # 阵块不能超出纸面（含留边）
        assert plan.block_px[0] + 2 * plan.margin_px <= plan.paper_px[0] + 1
        assert plan.block_px[1] + 2 * plan.margin_px <= plan.paper_px[1] + 1



def test_orientation_ties_prefer_unrotated():
    """Equal counts choose the source orientation deterministically."""
    plan = plan_layout((100, 100), (20, 30), dpi=300, gap_mm=0,
                       margin_mm=0, allow_rotate=True)
    assert plan.count == 15
    assert plan.rotated is False


@pytest.mark.parametrize("scale", [1, 2])
def test_renderer_rotates_pixels_clockwise_before_resizing(scale):
    """Rotated placement preserves the expected source-pixel orientation."""
    plan = plan_layout((3, 2), (2, 3), dpi=300, gap_mm=0,
                       margin_mm=0, allow_rotate=True)
    assert plan.rotated and plan.photo_px == (3, 2)
    photo = np.array([[[1, 1, 1], [2, 2, 2]],
                      [[3, 3, 3], [4, 4, 4]],
                      [[5, 5, 5], [6, 6, 6]]], dtype=np.uint8)
    photo = np.repeat(np.repeat(photo, scale, axis=0), scale, axis=1)
    canvas = render_layout(photo, plan)
    expected = np.array([[5, 3, 1], [6, 4, 2]], dtype=np.uint8)
    assert np.array_equal(canvas[:, :, 0], expected)


def test_crop_guides_include_exact_right_and_bottom_edges():
    """Guide pixels at paper bounds remain visible and box lines stay local."""
    plan = plan_layout((9, 8), (4, 3), dpi=300, gap_mm=0,
                       margin_mm=0, allow_rotate=False)
    # Pin one tile to the right and bottom canvas edges.
    plan.positions = [(5, 5)]
    plan.cols = plan.rows = 1
    tile = np.full((3, 4, 3), 90, np.uint8)
    cross = render_layout(tile, plan, crop_line="cross")
    assert np.all(cross[:, 8] == 200)  # right edge, not x == paper width
    assert np.all(cross[7, :] == 200)   # bottom edge, not y == paper height
    box = render_layout(tile, plan, crop_line="box")
    assert np.all(box[5:8, 5] == 200) and np.all(box[5:8, 8] == 200)
    assert np.all(box[5, 5:9] == 200) and np.all(box[7, 5:9] == 200)
    assert np.all(box[:5, :] == 255) and np.all(box[:, :5] == 255)


def test_rotation_takes_the_better_one(lib):
    """7 寸排 1 寸照必须旋转才排得下 18 张（不旋转只有 16 张）。"""
    spec, paper = lib.photo("cn_yicun"), lib.paper("7inch")
    straight = plan_for_spec(paper, spec, allow_rotate=False)
    both = plan_for_spec(paper, spec, allow_rotate=True)
    assert straight.count == 16, straight.count
    assert both.count == 18, both.count
    assert both.rotated is True
    assert both.photo_px == (spec.px[1], spec.px[0])


def test_beats_upstream_3_row_cap(lib):
    """自研引擎必须明显优于上游写死 3 行的实现（上游 A4 只排 21 张）。"""
    spec, paper = lib.photo("cn_yicun"), lib.paper("A4")
    plan = plan_layout(paper.px_at(300), spec.px_size, dpi=300)
    assert plan.count >= 49
    assert plan.rows > 3, "行数被限制了：%d" % plan.rows


def test_gap_and_margin_change_count(lib):
    """间距/留边可调，且越大排得越少。"""
    spec, paper = lib.photo("cn_yicun"), lib.paper("6inch")
    tight = plan_layout(paper.px_at(300), spec.px_size, dpi=300, gap_mm=1.0, margin_mm=1.0)
    loose = plan_layout(paper.px_at(300), spec.px_size, dpi=300, gap_mm=8.0, margin_mm=12.0)
    assert tight.count > loose.count, (tight.count, loose.count)
    assert tight.gap_px == round(1.0 / 25.4 * 300)
    assert loose.margin_px == round(12.0 / 25.4 * 300)


def test_positions_are_inside_paper_and_non_overlapping(lib):
    spec, paper = lib.photo("cn_yicun"), lib.paper("6inch")
    plan = plan_layout(paper.px_at(300), spec.px_size, dpi=300)
    pw, ph = plan.paper_px
    iw, ih = plan.photo_px
    assert plan.count == len(plan.positions)
    for (x, y) in plan.positions:
        assert 0 <= x and x + iw <= pw, (x, iw, pw)
        assert 0 <= y and y + ih <= ph, (y, ih, ph)
    # 两两不重叠
    for i in range(len(plan.positions)):
        for j in range(i + 1, len(plan.positions)):
            ax, ay = plan.positions[i]
            bx, by = plan.positions[j]
            overlap = not (ax + iw <= bx or bx + iw <= ax or ay + ih <= by or by + ih <= ay)
            assert not overlap, "第 %d 与第 %d 张重叠" % (i, j)


def test_block_is_centered(lib):
    spec, paper = lib.photo("cn_yicun"), lib.paper("6inch")
    plan = plan_layout(paper.px_at(300), spec.px_size, dpi=300)
    ox, oy = plan.origin
    bw, bh = plan.block_px
    left = ox
    right = plan.paper_px[0] - (ox + bw)
    top = oy
    bottom = plan.paper_px[1] - (oy + bh)
    assert abs(left - right) <= 2, (left, right)
    assert abs(top - bottom) <= 2, (top, bottom)


def test_render_canvas_size_and_crop_lines(lib):
    spec, paper = lib.photo("cn_yicun"), lib.paper("6inch")
    plan = plan_layout(paper.px_at(300), spec.px_size, dpi=300)
    photo = np.full((spec.px[1], spec.px[0], 3), 90, np.uint8)
    for style in ("none", "cross", "box"):
        canvas = render_layout(photo, plan, crop_line=style)
        assert canvas.shape == (plan.paper_px[1], plan.paper_px[0], 3), canvas.shape
        assert canvas.dtype == np.uint8
    none = render_layout(photo, plan, crop_line="none")
    cross = render_layout(photo, plan, crop_line="cross")
    assert not np.array_equal(none, cross), "贯穿式裁剪线没有画上去"
    # 原图区域应保持照片内容（90），只有线是浅灰 200
    # 注意按像素统计：三通道都为 90 才算一个照片像素
    assert np.all(none == 90, axis=2).sum() == plan.count * spec.px[0] * spec.px[1]


def test_render_composites_rgba_over_paper(lib):
    """RGBA 照片要按 alpha 合成到白纸上，不能出现黑边。"""
    spec, paper = lib.photo("cn_yicun"), lib.paper("6inch")
    plan = plan_layout(paper.px_at(300), spec.px_size, dpi=300)
    rgba = np.zeros((spec.px[1], spec.px[0], 4), np.uint8)
    rgba[:, :, :3] = 10
    rgba[:, :, 3] = 0            # 全透明
    canvas = render_layout(rgba, plan, crop_line="none")
    assert canvas.min() == 255, "全透明区域没有合成成白底，最小像素 %d" % canvas.min()


def test_smallest_paper_for(lib):
    """要 8 张 1 寸照，应选面积最小的能装下的相纸（5 寸能装 9 张，最小）。"""
    spec = lib.photo("cn_yicun")
    plan = smallest_paper_for(8, spec.px_size, lib.papers)
    assert plan is not None
    assert plan.count >= 8
    assert plan.paper_id == "5inch", plan.paper_id
    plan20 = smallest_paper_for(20, spec.px_size, lib.papers)
    assert plan20.paper_id in ("A4", "7inch")
    assert plan20.count >= 20


def test_empty_when_photo_larger_than_paper(lib):
    plan = plan_layout((100, 100), (500, 500), dpi=300)
    assert plan.count == 0
    assert plan.is_empty
    canvas = render_layout(np.zeros((500, 500, 3), np.uint8), plan)
    assert canvas.shape == (100, 100, 3)


@pytest.mark.parametrize("style", ["cross", "box"])
@pytest.mark.parametrize("dpi", [300, 350])
def test_crop_guides_cut_exact_photo_size_instead_of_gap_midpoints(lib, style, dpi):
    spec, paper = lib.photo("cn_yicun"), lib.paper("6inch")
    plan = plan_for_spec(paper, spec, dpi=dpi, gap_mm=4)
    iw, ih = plan.photo_px
    photo = np.full((spec.px[1], spec.px[0], 3), 90, np.uint8)
    canvas = render_layout(photo, plan, crop_line=style)
    x, y = plan.positions[0]
    # Observe the actual rendered guides through each tile's interior, rather
    # than deriving an expected result from the planner's block dimensions.
    xs = np.flatnonzero(np.all(canvas[y + ih // 2] == 200, axis=1))
    ys = np.flatnonzero(np.all(canvas[:, x + iw // 2] == 200, axis=1))
    assert xs.tolist() == sorted({edge for px, _ in plan.positions
                                 for edge in (px, px + iw)})
    assert ys.tolist() == sorted({edge for _, py in plan.positions
                                 for edge in (py, py + ih)})
    cut = canvas[ys[0]:ys[1], xs[0]:xs[1]]
    assert cut.shape[:2] == (ih, iw)
    assert np.all(cut[1:, 1:] == 90)
    cut_mm = sorted((cut.shape[1] / dpi * 25.4, cut.shape[0] / dpi * 25.4))
    assert cut_mm == pytest.approx(sorted(spec.mm_size), abs=25.4 / dpi)
    assert np.all(canvas[y + ih // 2, x + iw + plan.gap_px // 2] == 255)
    assert np.all(canvas[y + ih + plan.gap_px // 2, x + iw // 2] == 255)
    if style == "box":
        assert np.all(canvas[y + ih, x + iw] == 200)  # closed lower-right corner


@pytest.mark.parametrize("options", [
    {"gap_mm": -1}, {"gap_mm": float("nan")}, {"gap_mm": float("inf")},
    {"margin_mm": -1}, {"margin_mm": float("nan")},
    {"margin_mm": float("inf")}, {"gap_mm": True},
    {"dpi": 0}, {"dpi": -300}, {"dpi": 300.5}, {"dpi": True},
])
def test_layout_rejects_invalid_rulers(options):
    with pytest.raises(ValueError):
        plan_layout((100, 100), (20, 30), **options)


@pytest.mark.parametrize("dpi", [0, -1, float("nan"), float("inf"), 300.5, True])
def test_plan_for_spec_rejects_invalid_dpi_before_converting(lib, dpi):
    with pytest.raises(ValueError, match="dpi"):
        plan_for_spec(lib.paper("6inch"), lib.photo("cn_yicun"), dpi=dpi)


@pytest.mark.parametrize("count", [0, -1, 1.5, True])
def test_smallest_paper_rejects_invalid_count_even_without_papers(count):
    with pytest.raises(ValueError, match="照片张数"):
        smallest_paper_for(count, (20, 30), [])


def test_large_margins_give_empty_plan_without_negative_positions():
    plan = plan_layout((100, 100), (20, 30), margin_mm=100)
    assert plan.is_empty
    assert all(value >= 0 for value in plan.origin)


@pytest.mark.parametrize("options", [{"crop_line": "invalid"}, {"line_width": 0},
                                     {"line_width": 1.5}])
def test_render_rejects_invalid_crop_guides(options):
    plan = plan_layout((100, 100), (20, 30), gap_mm=0, margin_mm=0)
    with pytest.raises(ValueError):
        render_layout(np.zeros((30, 20, 3), np.uint8), plan, **options)
