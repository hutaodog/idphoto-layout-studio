# -*- coding: utf-8 -*-
"""规格库：证件照尺寸、相纸尺寸、底色。

三条铁律（来自调研，写进代码而不是写在文档里）：
1. dpi 是每条预设的独立字段，不能当成全局常量 300。例如库中350dpi预设
   只改元数据为300会让打印尺寸放大约16.7%；300改350会缩小约14.3%。
2. 上传像素与打印毫米是两套口径；上传预设的兼容毫米只供打印流程使用，非官方打印要求。
3. 同名不同义（二寸有 35×53 与 35×49 等场景口径），因此每条都带 source / confidence；
   已复核的来源另存 refs，记录发布方、适用范围和核验日期，不能把网页数当独立标准数。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)


def mm_to_px(mm: float, dpi: int) -> int:
    """毫米转像素。round() 而非 int()，误差控制在 ±1px 内。"""
    return round(mm / 25.4 * dpi)


@dataclass
class ColorSpec:
    id: str
    name_zh: str
    hex: str
    rgb: Tuple[int, int, int]
    note: str = ""

    @property
    def bgr(self) -> Tuple[int, int, int]:
        r, g, b = self.rgb
        return (b, g, r)

    @property
    def hex_code(self) -> str:
        return "#" + self.hex.lstrip("#").upper()


@dataclass
class PaperSpec:
    id: str
    name_zh: str
    mm: Tuple[float, float]      # 宽, 高（竖版）
    dpi: int
    px: Tuple[int, int]          # 宽, 高
    aliases: Tuple[str, ...] = ()

    def px_at(self, dpi: int) -> Tuple[int, int]:
        return (mm_to_px(self.mm[0], dpi), mm_to_px(self.mm[1], dpi))

    @property
    def area_mm2(self) -> float:
        return self.mm[0] * self.mm[1]


@dataclass
class PhotoSpec:
    id: str
    name_zh: str
    category: str
    mm: Tuple[float, float]      # 宽, 高
    dpi: int
    px: Tuple[int, int]          # 宽, 高
    bg: Tuple[str, ...]
    aliases: Tuple[str, ...] = ()
    upload: Dict = field(default_factory=dict)
    compose: Dict = field(default_factory=dict)
    note: str = ""
    source: str = ""
    confidence: str = "B"
    # 增量补录的可追溯证据；source 仍是兼容现有界面的简要摘要。
    # scope 应区分支持/冲突的口径及其具体业务场景，verified 是查阅日期。
    refs: Tuple[Dict[str, str], ...] = ()
    mm_from_px: bool = False      # 数字上传预设反算的兼容打印尺寸，非官方实体要求

    @property
    def px_size(self) -> Tuple[int, int]:
        """(宽, 高) 像素。"""
        return (int(self.px[0]), int(self.px[1]))

    @property
    def hw(self) -> Tuple[int, int]:
        """(高, 宽) —— 上游 Hivision 的 size 参数用的是 (h, w)。"""
        return (int(self.px[1]), int(self.px[0]))

    @property
    def mm_size(self) -> Tuple[float, float]:
        return (float(self.mm[0]), float(self.mm[1]))

    @property
    def aspect(self) -> float:
        return self.px[0] / self.px[1]

    @property
    def is_landscape(self) -> bool:
        return self.px[0] > self.px[1]

    def px_at(self, dpi: int) -> Tuple[int, int]:
        return (mm_to_px(self.mm[0], dpi), mm_to_px(self.mm[1], dpi))

    def print_mm_at(self, dpi: int) -> Tuple[float, float]:
        """按指定 dpi 打印出来的实际毫米尺寸——用于校验 dpi 元数据写对了没有。"""
        return (self.px[0] / dpi * 25.4, self.px[1] / dpi * 25.4)

    @property
    def kb_limits(self) -> Tuple[Optional[int], Optional[int]]:
        return (self.upload.get("min_kb"), self.upload.get("max_kb"))

    def display(self) -> str:
        return "%s  %.0f×%.0fmm  %d×%dpx@%ddpi" % (
            self.name_zh, self.mm[0], self.mm[1], self.px[0], self.px[1], self.dpi,
        )


class SpecLibrary:
    """规格库的加载与查询。默认从 app/data/*.json 读取。"""

    def __init__(self, photos: List[PhotoSpec], papers: List[PaperSpec],
                 colors: List[ColorSpec], raw: Optional[dict] = None):
        self.photos = photos
        self.papers = papers
        self.colors = colors
        self.raw = raw or {}
        self._photo_by_id = {s.id: s for s in photos}
        self._paper_by_id = {s.id: s for s in papers}
        self._color_by_id = {c.id: c for c in colors}

    # ---------- 加载 ----------
    @classmethod
    def load(cls, data_dir: Optional[str] = None) -> "SpecLibrary":
        d = data_dir or DATA_DIR
        with open(os.path.join(d, "photo_specs.json"), "r", encoding="utf-8") as f:
            photo_raw = json.load(f)
        with open(os.path.join(d, "paper_specs.json"), "r", encoding="utf-8") as f:
            paper_raw = json.load(f)
        with open(os.path.join(d, "bg_colors.json"), "r", encoding="utf-8") as f:
            color_raw = json.load(f)

        photos = []
        for s in photo_raw["specs"]:
            mm = (float(s["mm"][0]), float(s["mm"][1]))
            dpi = int(s["dpi"])
            px = s.get("px")
            if px is None:                      # px 为 null 时由 mm+dpi 计算
                px = (mm_to_px(mm[0], dpi), mm_to_px(mm[1], dpi))
            photos.append(PhotoSpec(
                id=s["id"], name_zh=s["name_zh"], category=s["category"],
                mm=mm, dpi=dpi, px=(int(px[0]), int(px[1])),
                bg=tuple(s.get("bg", ["white"])), aliases=tuple(s.get("aliases", [])),
                upload=dict(s.get("upload") or {}), compose=dict(s.get("compose") or {}),
                note=s.get("note", ""), source=s.get("source", ""),
                confidence=s.get("confidence", "B"),
                refs=tuple(dict(ref) for ref in (s.get("refs") or [])),
                mm_from_px=bool(s.get("mm_from_px", False)),
            ))

        papers = [PaperSpec(
            id=p["id"], name_zh=p["name_zh"],
            mm=(float(p["mm"][0]), float(p["mm"][1])),
            dpi=int(p.get("dpi", 300)),
            px=(int(p["px"][0]), int(p["px"][1])),
            aliases=tuple(p.get("aliases", [])),
        ) for p in paper_raw["papers"]]

        colors = [ColorSpec(
            id=c["id"], name_zh=c["name_zh"], hex=c["hex"],
            rgb=tuple(c["rgb"]), note=c.get("note", ""),
        ) for c in color_raw["colors"]]

        lib = cls(photos, papers, colors, raw={"photo": photo_raw, "paper": paper_raw,
                                               "color": color_raw})
        lib._default_compose = photo_raw.get("compose_default", {})
        return lib

    # ---------- 查询 ----------
    @property
    def default_compose(self) -> Dict:
        return getattr(self, "_default_compose", {
            "head_measure_ratio": 0.2, "head_height_ratio": 0.45,
            "head_top_range": [0.12, 0.1],
        })

    def photo(self, spec_id: str) -> PhotoSpec:
        if spec_id not in self._photo_by_id:
            raise KeyError("未知证件照规格: %s" % spec_id)
        return self._photo_by_id[spec_id]

    def paper(self, paper_id: str) -> PaperSpec:
        if paper_id not in self._paper_by_id:
            raise KeyError("未知相纸规格: %s" % paper_id)
        return self._paper_by_id[paper_id]

    def color(self, color_id: str) -> ColorSpec:
        if color_id not in self._color_by_id:
            raise KeyError("未知底色: %s" % color_id)
        return self._color_by_id[color_id]

    def categories(self) -> List[str]:
        seen, out = set(), []
        for s in self.photos:
            if s.category not in seen:
                seen.add(s.category)
                out.append(s.category)
        return out

    def by_category(self, category: str) -> List[PhotoSpec]:
        return [s for s in self.photos if s.category == category]

    def search(self, text: str) -> List[PhotoSpec]:
        """按 id / 中文名 / 别名模糊搜索。"""
        t = (text or "").strip().lower()
        if not t:
            return list(self.photos)
        hits = []
        for s in self.photos:
            hay = [s.id.lower(), s.name_zh.lower()] + [a.lower() for a in s.aliases]
            if any(t in h for h in hay):
                hits.append(s)
        return hits

    def require(self) -> None:
        """校验数据结构与换算，不代表已验证任何业务受理标准。"""
        if len(self.photos) < 1:
            raise ValueError("规格库为空")
        ids = [s.id for s in self.photos]
        if len(ids) != len(set(ids)):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError("规格 id 重复: %s" % dup)
        colors = set(self._color_by_id)
        for spec in [*self.photos, *self.papers]:
            values = [*spec.mm, spec.dpi, *spec.px]
            if (len(spec.mm) != 2 or len(spec.px) != 2
                    or any(not math.isfinite(v) or v <= 0 for v in values)
                    or any(int(v) != v for v in [spec.dpi, *spec.px])):
                raise ValueError("规格尺寸必须是正有限值，像素和DPI必须为整数: %s" % spec.id)
            if any(abs(a - b) > 1 for a, b in zip(spec.px_at(spec.dpi), spec.px)):
                raise ValueError("规格毫米、像素和DPI换算不一致: %s" % spec.id)
        for spec in self.photos:
            if not spec.bg or any(color not in colors for color in spec.bg):
                raise ValueError("规格底色引用无效: %s" % spec.id)
            if spec.confidence not in ("A", "B", "C", "D"):
                raise ValueError("规格证据等级无效: %s" % spec.id)
            for ref in spec.refs:
                if (not all(ref.get(k) for k in ("title", "issuer", "url", "scope", "verified"))
                        or not ref["url"].startswith(("https://", "http://"))):
                    raise ValueError("规格来源记录不完整: %s" % spec.id)

    def set_custom_color(self, rgb: Tuple[int, int, int], name: str = "自定义") -> ColorSpec:
        """注册/更新一个自定义底色（界面上的取色器用），返回可直接当 bg id 用的 ColorSpec。"""
        r, g, b = (int(v) for v in rgb)
        spec = ColorSpec(id="custom", name_zh=name, hex="%02X%02X%02X" % (r, g, b),
                         rgb=(r, g, b), note="用户自定义")
        self._color_by_id["custom"] = spec
        self.colors = [c for c in self.colors if c.id != "custom"] + [spec]
        return spec
