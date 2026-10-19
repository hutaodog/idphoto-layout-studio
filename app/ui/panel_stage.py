# -*- coding: utf-8 -*-
"""玻璃卡片舞台：绝对定位 + 默认摆法 + 拖动/拉伸 + 防重叠。

从 `dashboard.py` 里抽出来的公共机制，现在两套界面共用：
- `dashboard.py`（卡片仪表盘）：7 张卡平铺，没有背景层；
- `canvas_first.py`（画布优先，方案 10）：预览画布铺满当背景，其余 6 张卡浮在它上面。

约定：
* 卡片是 `GlassPanel`，绝对定位在舞台上，可以拖、可以八方向拉；
* **任何时刻都不允许两张卡片重叠** —— 用户拖动/拉伸后由 `resolve_overlaps()` 负责让位；
* 用户自己摆过之后（`_moved`），窗口再变大小就不重新排，只把卡片约束回可视范围；
  `reset_to_default()` 可以一键还原并重新打开"跟着窗口自动排"。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QWidget

from .glass_panel import GlassPanel

# 卡片再挤也不能小于这个尺寸。别调太小：这些卡片内容都很密
# （6 个滑块 / 规格列表 / 7 个色块），压到 160×110 会截得看不清。
HARD_MIN_W = 260
HARD_MIN_H = 190

# 设计基准尺寸：默认摆法按这个比例算，窗口变化就跟着缩放
DESIGN_W, DESIGN_H = 1600, 872

# 槽位：(key, 相对矩形 (x, y, w, h), 最小宽, 最小高)
Slot = Tuple[str, Tuple[float, float, float, float], int, int]


def strip_group(gb) -> QWidget:
    """去掉分组卡片自带的标题带与白底 —— 玻璃卡片本身就是卡片。"""
    gb.setTitle("")
    gb.setStyleSheet(
        "QGroupBox{background:transparent;border:none;margin-top:2px;}"
        "QGroupBox::title{height:0px;}")
    return gb


class PanelStage(QWidget):
    """承载所有玻璃卡片的舞台。"""

    def __init__(self, slots: List[Slot], background: Optional[QWidget] = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("glassStage")
        # 舞台自身完全透明：桌面经由窗口毛玻璃透进来
        self.setStyleSheet("QWidget#glassStage{background:transparent;}")
        self.slots = list(slots)
        self.panels: List[Tuple[str, GlassPanel]] = []
        self._moved = False
        self._placed = False
        self.background = background
        if background is not None:
            background.setParent(self)
            background.lower()          # 永远垫在卡片下面

    # ------------------------------------------------------------------ 装配
    def add(self, key: str, panel: GlassPanel) -> None:
        panel.setParent(self)
        # 直接把卡片对象带过去：不要用 self.sender()，信号从 Python 侧 emit 时
        # sender() 可能是 None，那样防重叠就整个不会执行。
        panel.userChanged.connect(lambda _p=panel: self._on_user_changed(_p))
        self.panels.append((key, panel))
        panel.raise_()

    def _frac(self, key: str):
        for k, frac, _mw, _mh in self.slots:
            if k == key:
                return frac
        return None

    def _minima(self, key: str):
        for k, _frac, mw, mh in self.slots:
            if k == key:
                return mw, mh
        return HARD_MIN_W, HARD_MIN_H

    # ------------------------------------------------------------------ 摆法
    def _default_rect(self, frac) -> QRect:
        w, h = self.width(), self.height()
        x, y, fw, fh = frac
        return QRect(int(x * w), int(y * h), int(fw * w), int(fh * h))

    def apply_default(self) -> None:
        if self.background is not None:
            self.background.setGeometry(0, 0, self.width(), self.height())
        for key, panel in self.panels:
            frac = self._frac(key)
            if frac is None:
                continue
            r = self._default_rect(frac)
            r.setWidth(max(160, r.width()))
            r.setHeight(max(120, r.height()))
            # fit_into 会把卡片的最小尺寸压到不超过这个格子，避免窗口小的时候
            # 卡片撑出格子、和邻居重叠
            panel.fit_into(r)

    def reset_to_default(self) -> None:
        """恢复默认布局：位置、大小全回来，并重新允许"跟着窗口自动排"。"""
        self._moved = False
        self._placed = True
        self.apply_default()

    def _user_moved(self) -> bool:
        """用户是否真的自己拖过/拉过卡片。

        不能用"几何和默认值不一致"来判断 —— 窗口一缩放，默认值就变了，
        于是每次缩放都会被误判成"用户挪过"，卡片就再也不重排、直接叠在一起。
        """
        return self._moved

    def resizeEvent(self, e):                              # noqa: N802
        super().resizeEvent(e)
        if not self._placed:
            self.apply_default()
            self._placed = True
            return
        if self._user_moved():
            area = self.rect()
            if self.background is not None:
                self.background.setGeometry(0, 0, self.width(), self.height())
            for _k, p in self.panels:
                p.set_bounds(area)
        else:
            self.apply_default()

    # ------------------------------------------------------------------ 防重叠
    def _on_user_changed(self, panel) -> None:
        self._moved = True
        if isinstance(panel, GlassPanel):
            self.resolve_overlaps(panel)

    def _pairs_overlapping(self):
        ps = [p for _k, p in self.panels]
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                if ps[i].geometry().intersects(ps[j].geometry()):
                    return ps[i], ps[j]
        return None

    def resolve_overlaps(self, moved: GlassPanel, passes: int = 120) -> None:
        """让被压住的卡片"让位"，保证结束时**没有任何两张卡片重叠**。

        三级兜底：逐个挪 → 重新打包剩余空间 → 把用户拖的那张收回来。
        宁可尺寸不完全随手，也绝不接受卡片互相覆盖。
        """
        area = self.rect()
        moved.fit_into(moved.geometry().intersected(area))

        for _ in range(passes):
            pair = self._pairs_overlapping()
            if pair is None:
                return
            a, b = pair
            if a is moved:
                victim, blocker = b, a
            elif b is moved:
                victim, blocker = a, b
            else:
                victim, blocker = b, a
            new = (self._shrink_away(victim.geometry(), blocker.geometry(), victim)
                   or self._move_away(victim.geometry(), blocker.geometry(), area, victim))
            if new is not None:
                victim.fit_into(new.intersected(area))
                continue
            back = self._shrink_away(moved.geometry(), victim.geometry(), moved)
            if back is not None:
                moved.fit_into(back.intersected(area))

        # 二级兜底：循环跑完还有重叠（一张卡被拉到占掉半个屏幕时，逐个挪收敛不了）
        if self._pairs_overlapping() is not None:
            self._repack_others(moved)

        # 三级兜底：还不行就把用户那张一直收到不压住任何人为止
        for _ in range(60):
            pair = self._pairs_overlapping()
            if pair is None:
                break
            a, b = pair
            victim = b if a is moved else a
            back = self._shrink_away(moved.geometry(), victim.geometry(), moved)
            if back is None:
                break
            moved.fit_into(back.intersected(self.rect()))

    def _shrink_away(self, g: QRect, mg: QRect, panel: GlassPanel):
        """把 g 从 mg 那一侧缩出去；先按卡片声明的最小尺寸，再退到硬下限。"""
        cands = [
            QRect(g.left(), g.top(), g.width(), mg.top() - g.top()),          # 往上收
            QRect(g.left(), mg.bottom() + 1, g.width(), g.bottom() - mg.bottom()),
            QRect(g.left(), g.top(), mg.left() - g.left(), g.height()),       # 往左收
            QRect(mg.right() + 1, g.top(), g.right() - mg.right(), g.height()),
        ]
        ok = [c for c in cands
              if c.width() >= panel.min_w and c.height() >= panel.min_h]
        if not ok:
            ok = [c for c in cands
                  if c.width() >= HARD_MIN_W and c.height() >= HARD_MIN_H]
        if not ok:
            return None
        # 选"剩下面积最大"的那一种收法，视觉上改动最小
        return max(ok, key=lambda c: c.width() * c.height())

    def _move_away(self, g: QRect, mg: QRect, area: QRect, panel: GlassPanel):
        """把整张卡挪到附近不压住 mg 的位置；找不到就返回 None。"""
        step = 16
        for dist in range(step, 2400, step):
            for cand in (QRect(g.left(), mg.bottom() + 1 + (dist - step), g.width(), g.height()),
                         QRect(mg.right() + 1 + (dist - step), g.top(), g.width(), g.height()),
                         QRect(g.left(), g.top() - dist, g.width(), g.height()),
                         QRect(g.left() - dist, g.top(), g.width(), g.height())):
                if not cand.intersects(mg) and area.contains(cand):
                    return cand
        return None

    @staticmethod
    def _subtract(rects, cut):
        """从若干矩形里挖掉 cut 那块。

        ⚠ 四块必须**互不相交**：上下两块占满整宽，所以左右两块只能取
        `inter` 那一段的高度 —— 第一版让左右也占满整高，四块互相重叠，
        打包时两张卡片被放进互相重叠的"空闲区"，又叠在一起了。
        """
        out = []
        for r in rects:
            if not r.intersects(cut):
                out.append(r)
                continue
            inter = r.intersected(cut)
            if inter.top() > r.top():
                out.append(QRect(r.left(), r.top(), r.width(), inter.top() - r.top()))
            if inter.bottom() < r.bottom():
                out.append(QRect(r.left(), inter.bottom() + 1, r.width(),
                                 r.bottom() - inter.bottom()))
            if inter.left() > r.left():
                out.append(QRect(r.left(), inter.top(), inter.left() - r.left(),
                                 inter.height()))
            if inter.right() < r.right():
                out.append(QRect(inter.right() + 1, inter.top(),
                                 r.right() - inter.right(), inter.height()))
        return [x for x in out if x.width() > 0 and x.height() > 0]

    def _repack_others(self, moved: GlassPanel) -> None:
        """把除 moved 以外的卡片重新塞进剩余空间（可能有 L 形区域）。"""
        free = self._subtract([self.rect()], moved.geometry())
        others = [p for _k, p in self.panels if p is not moved]
        others.sort(key=lambda p: p.geometry().width() * p.geometry().height(),
                    reverse=True)
        for p in others:
            if not free:
                return
            g = p.geometry()
            best, best_waste = None, None
            for fr in free:
                w = min(g.width(), fr.width())
                h = min(g.height(), fr.height())
                if w < HARD_MIN_W or h < HARD_MIN_H:
                    continue
                waste = fr.width() * fr.height() - w * h
                if best_waste is None or waste < best_waste:
                    best_waste, best = waste, QRect(fr.left(), fr.top(), w, h)
            if best is None:
                fr = max(free, key=lambda r: r.width() * r.height())
                best = QRect(fr.left(), fr.top(), fr.width(), fr.height())
            p.fit_into(best)
            free = self._subtract(free, best)
