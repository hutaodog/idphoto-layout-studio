# -*- coding: utf-8 -*-
"""排版引擎（自研）。

上游 HivisionIDPhotos 的 judge_layout() 把行列搜索空间写死成 range(1,4) 行 × range(1,9) 列，
最多只排 3 行，导致 A4 上 1 寸照只能排 21 张（正确值 50 张）。本模块不设上限。

核心公式（分子里的 +gap 不能省，否则会少数一张）：
    cols = (paper_w - 2*margin + gap) // (photo_w + gap)
    rows = (paper_h - 2*margin + gap) // (photo_h + gap)
同时计算 90° 旋转后的排法，取张数多的那一种。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
from typing import List, Optional, Sequence, Tuple

import numpy as np

# 默认留边（毫米）：照片之间 2mm，纸张边缘 3mm（打印机不可打印区，不是出血）
DEFAULT_GAP_MM = 2.0
DEFAULT_MARGIN_MM = 3.0

LINE_COLOR = (200, 200, 200)   # 与上游一致的浅灰


def _number(value, name: str, *, positive: bool = True,
            integer: bool = False):
    if (isinstance(value, bool) or not isinstance(value, Real)
            or not math.isfinite(value) or (value <= 0 if positive else value < 0)
            or (integer and value != int(value))):
        raise ValueError("%s 必须为有限%s%s" % (
            name, "正" if positive else "非负", "整数" if integer else "数"))
    return int(value) if integer else value


def _size(value, name: str) -> Tuple[int, int]:
    try:
        if len(value) == 2:
            return tuple(_number(v, name, integer=True) for v in value)
    except TypeError:
        pass
    raise ValueError("%s 必须包含宽和高" % name)


def mm_to_px(mm: float, dpi: int) -> int:
    _number(mm, "毫米尺寸", positive=False)
    _number(dpi, "dpi", integer=True)
    return round(mm / 25.4 * dpi)


@dataclass
class LayoutPlan:
    paper_id: str
    paper_px: Tuple[int, int]        # 宽, 高
    photo_px: Tuple[int, int]        # 宽, 高（已含旋转）
    photo_px_original: Tuple[int, int]
    dpi: int
    gap_px: int
    margin_px: int
    cols: int
    rows: int
    rotated: bool
    positions: List[Tuple[int, int]] = field(default_factory=list)
    block_px: Tuple[int, int] = (0, 0)
    origin: Tuple[int, int] = (0, 0)

    @property
    def count(self) -> int:
        return len(self.positions)

    @property
    def is_empty(self) -> bool:
        return self.count == 0

    def summary(self) -> str:
        rot = "（旋转90°）" if self.rotated else ""
        return "%s：%d 列 × %d 行 = %d 张%s，照片 %d×%dpx，间距 %dpx，留边 %dpx" % (
            self.paper_id, self.cols, self.rows, self.count, rot,
            self.photo_px[0], self.photo_px[1], self.gap_px, self.margin_px,
        )


def compute_grid(paper_px: Tuple[int, int], photo_px: Tuple[int, int],
                 gap_px: int, margin_px: int) -> Tuple[int, int]:
    """给定相纸与照片尺寸，算最多能排几列几行。"""
    pw, ph = _size(paper_px, "相纸像素尺寸")
    iw, ih = _size(photo_px, "照片像素尺寸")
    gap_px = _number(gap_px, "像素间距", positive=False, integer=True)
    margin_px = _number(margin_px, "像素留边", positive=False, integer=True)
    cols = (pw - 2 * margin_px + gap_px) // (iw + gap_px)
    rows = (ph - 2 * margin_px + gap_px) // (ih + gap_px)
    return max(0, int(cols)), max(0, int(rows))


def plan_layout(paper_px: Tuple[int, int], photo_px: Tuple[int, int],
                dpi: int = 300, gap_mm: float = DEFAULT_GAP_MM,
                margin_mm: float = DEFAULT_MARGIN_MM,
                paper_id: str = "custom",
                allow_rotate: bool = True) -> LayoutPlan:
    """算出一套完整排版方案（含每张照片的左上角坐标，整块在纸面居中）。"""
    paper_px = _size(paper_px, "相纸像素尺寸")
    photo_px = _size(photo_px, "照片像素尺寸")
    dpi = _number(dpi, "dpi", integer=True)
    gap_mm = _number(gap_mm, "毫米间距", positive=False)
    margin_mm = _number(margin_mm, "毫米留边", positive=False)
    gap_px = mm_to_px(gap_mm, dpi)
    margin_px = mm_to_px(margin_mm, dpi)

    # Keep orientation selection explicit and stable: a tie always prefers the
    # source orientation (no needless 90-degree rotation), then the first
    # candidate in this fixed order.  This matters for square/tight layouts,
    # where equal counts must not depend on set/dict iteration order.
    best = None   # (count, cols, rows, rotated, iw, ih)
    orientations = [False, True] if allow_rotate else [False]
    for rotated in orientations:
        iw, ih = (photo_px[1], photo_px[0]) if rotated else (photo_px[0], photo_px[1])
        cols, rows = compute_grid(paper_px, (iw, ih), gap_px, margin_px)
        count = cols * rows
        candidate = (count, cols, rows, rotated, iw, ih)
        if best is None or (count, not rotated) > (best[0], not best[3]):
            best = candidate

    _, cols, rows, rotated, iw, ih = best
    pw, ph = paper_px

    block_w = cols * iw + max(0, cols - 1) * gap_px
    block_h = rows * ih + max(0, rows - 1) * gap_px
    # 整块在纸面居中；排不下时退回留边位置，不产生负坐标
    ox = (pw - block_w) // 2
    oy = (ph - block_h) // 2
    ox = max(margin_px if block_w + 2 * margin_px <= pw else 0, ox)
    oy = max(margin_px if block_h + 2 * margin_px <= ph else 0, oy)

    positions = []
    for r in range(rows):
        for c in range(cols):
            positions.append((ox + c * (iw + gap_px), oy + r * (ih + gap_px)))

    return LayoutPlan(
        paper_id=paper_id, paper_px=(pw, ph), photo_px=(iw, ih),
        photo_px_original=photo_px, dpi=dpi, gap_px=gap_px, margin_px=margin_px,
        cols=cols, rows=rows, rotated=rotated, positions=positions,
        block_px=(block_w, block_h), origin=(ox, oy),
    )


def plan_for_spec(paper, spec, gap_mm: float = DEFAULT_GAP_MM,
                  margin_mm: float = DEFAULT_MARGIN_MM,
                  dpi: Optional[int] = None,
                  allow_rotate: bool = True) -> LayoutPlan:
    """按**规格自己的 dpi** 排版（纸和照片用同一把尺子）。

    为什么必须有这个函数：规格库里同时有
        「一寸」            25×35mm @300dpi → 295×413 px
        「一寸（350dpi 打印）」25×35mm @350dpi → 344×482 px
    两张**物理尺寸完全一样**，6 寸相纸上都该排 12 张（3 列 × 4 行）。

    旧写法是 `plan_layout(paper.px_at(300), spec.px_size, dpi=300)`：纸按 300dpi
    算像素（1205×1795），照片却直接拿规格自带的 344×482 px —— 相当于把这张 25×35mm
    的照片当成 29.1×40.8mm（大了 16.7%），于是只能排 3 行，得到 9 张。
    用户看到的就是"两个一寸，一个 9 张一个 12 张"。

    现在一律：dpi 取规格的（或调用方指定的），纸和照片都在这个 dpi 下由毫米换算，
    照片阵块在纸上的物理尺寸永远是准确的 25×35mm。
    """
    d = _number(spec.dpi if dpi is None else dpi, "dpi", integer=True)
    return plan_layout(paper.px_at(d), spec.px_at(d), dpi=d,
                       gap_mm=gap_mm, margin_mm=margin_mm,
                       paper_id=getattr(paper, "id", "custom"),
                       allow_rotate=allow_rotate)


def smallest_paper_for(count: int, photo_px: Tuple[int, int],
                       papers: Sequence, dpi: int = 300,
                       gap_mm: float = DEFAULT_GAP_MM,
                       margin_mm: float = DEFAULT_MARGIN_MM) -> Optional[LayoutPlan]:
    """反算：要排 count 张，用面积最小的相纸。"""
    count = _number(count, "照片张数", integer=True)
    dpi = _number(dpi, "dpi", integer=True)
    photo_px = _size(photo_px, "照片像素尺寸")
    _number(gap_mm, "毫米间距", positive=False)
    _number(margin_mm, "毫米留边", positive=False)
    plans = []
    for p in papers:
        plan = plan_layout(p.px_at(dpi), photo_px, dpi=dpi, gap_mm=gap_mm,
                           margin_mm=margin_mm, paper_id=p.id)
        if plan.count >= count:
            plans.append((p.area_mm2, plan))
    if not plans:
        return None
    plans.sort(key=lambda x: x[0])
    return plans[0][1]


def render_layout(photo_bgr: np.ndarray, plan: LayoutPlan,
                  crop_line: str = "none",
                  line_color: Tuple[int, int, int] = LINE_COLOR,
                  paper_bgr: Tuple[int, int, int] = (255, 255, 255),
                  line_width: int = 1) -> np.ndarray:
    """把照片按方案铺到相纸上。

    crop_line:
      'none'  —— 不画线
      'cross' —— 贯穿式延长线（线一直延伸到纸边，裁切时好对刀）
      'box'   —— 每张照片一个独立方框
    """
    if crop_line not in ("none", "cross", "box"):
        raise ValueError("不支持的裁切线样式: %s" % crop_line)
    width = _number(line_width, "裁切线宽度", integer=True)
    pw, ph = plan.paper_px
    canvas = np.zeros((ph, pw, 3), np.uint8)
    canvas[:, :] = paper_bgr

    if photo_bgr is None or plan.is_empty:
        return canvas

    if photo_bgr.shape[2] == 4:
        import cv2
        alpha = photo_bgr[:, :, 3:4].astype(np.float32) / 255.0
        rgb = photo_bgr[:, :, :3].astype(np.float32)
        bg = np.array(paper_bgr, np.float32).reshape(1, 1, 3)
        composited = (rgb * alpha + bg * (1 - alpha)).astype(np.uint8)
        tile = composited
    else:
        tile = photo_bgr

    iw, ih = plan.photo_px
    import cv2
    # plan.rotated 只表示排版方向；输入照片本身仍是原始宽高，必须先旋转再缩放。
    if plan.rotated:
        tile = cv2.rotate(tile, cv2.ROTATE_90_CLOCKWISE)
    if tile.shape[1] != iw or tile.shape[0] != ih:
        interp = cv2.INTER_AREA if (tile.shape[1] > iw or tile.shape[0] > ih) else cv2.INTER_CUBIC
        tile = cv2.resize(tile, (iw, ih), interpolation=interp)

    rendered_positions = []
    for (x, y) in plan.positions:
        if x < 0 or y < 0 or x + iw > pw or y + ih > ph:
            continue
        canvas[y:y + ih, x:x + iw] = tile
        rendered_positions.append((x, y))

    def span(boundary, limit):
        """Center a finite-width guide on a boundary and clip safely."""
        start = int(boundary) - width // 2
        # At an outer paper edge the mathematical boundary is outside the
        # array; retain the visible part inside instead of producing a gap.
        start = min(max(0, start), max(0, limit - width))
        return start, min(limit, start + width)

    def vline(x, y0=0, y1=None):
        y0, y1 = (max(0, int(y0)), min(ph, ph if y1 is None else int(y1)))
        x0, x1 = span(x, pw)
        if x0 < x1 and y0 < y1:
            canvas[y0:y1, x0:x1] = line_color

    def hline(y, x0=0, x1=None):
        x0, x1 = (max(0, int(x0)), min(pw, pw if x1 is None else int(x1)))
        y0, y1 = span(y, ph)
        if x0 < x1 and y0 < y1:
            canvas[y0:y1, x0:x1] = line_color

    if crop_line == "cross":
        x_edges = sorted({x for x, _ in rendered_positions} |
                         {x + iw for x, _ in rendered_positions})
        y_edges = sorted({y for _, y in rendered_positions} |
                         {y + ih for _, y in rendered_positions})
        for x in x_edges:
            vline(x)
        for y in y_edges:
            hline(y)
    elif crop_line == "box":
        for x, y in rendered_positions:
            vline(x, y, y + ih + 1)
            vline(x + iw, y, y + ih + 1)
            hline(y, x, x + iw + 1)
            hline(y + ih, x, x + iw + 1)

    return canvas


def layout_matrix(spec_ids: Sequence[str], paper_px: Tuple[int, int],
                  photo_px_map: dict, **kw) -> List[LayoutPlan]:
    """批量算多种证件照在同一相纸上的张数（供 UI 表格与测试使用）。"""
    out = []
    for sid in spec_ids:
        out.append(plan_layout(paper_px, photo_px_map[sid], paper_id=sid, **kw))
    return out
