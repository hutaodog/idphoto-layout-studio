# -*- coding: utf-8 -*-
"""后台线程：把内核处理放到工作线程，保证界面不卡。"""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from ..core.exporter import resample_to_dpi, save_image
from ..core.layout import plan_for_spec, render_layout
from ..core.pipeline import ManualTransform, PipelineError, Processor, load_photo
from ..core.specs import PhotoSpec


class ProcessWorker(QThread):
    """处理单张照片。"""

    ok = Signal(object)          # ProcessResult
    fail = Signal(str)

    def __init__(self, proc: Processor, path: str, spec: PhotoSpec, bg: str,
                 hollow_fix: bool = True, parent=None):
        super().__init__(parent)
        self.proc = proc
        self.path = path
        self.spec = spec
        self.bg = bg
        self.hollow_fix = hollow_fix

    def run(self):
        try:
            img = load_photo(self.path)
            res = self.proc.process(img, self.spec, bg=self.bg,
                                    hollow_fix=self.hollow_fix)
            self.ok.emit(res)
        except PipelineError as e:
            self.fail.emit(str(e))
        except Exception as e:                       # noqa: BLE001
            self.fail.emit("未预期的错误：%r" % (e,))


class BatchExportWorker(QThread):
    """批量导出：每张照片出证件照 + 排版照。"""

    progress = Signal(int, int, str)     # 当前序号, 总数, 说明
    itemDone = Signal(str, bool, str)    # 路径, 是否成功, 说明
    allDone = Signal(int, int)           # 成功数, 总数

    def __init__(self, proc: Processor, jobs: List[dict], out_dir: str,
                 paper, gap_mm: float, margin_mm: float, crop_line: str,
                 target_kb: float = 0, dpi_override: int = 0,
                 export_single: bool = True, export_layout: bool = True,
                 parent=None):
        super().__init__(parent)
        self.proc = proc
        self.jobs = jobs
        self.out_dir = out_dir
        self.paper = paper
        self.gap_mm = gap_mm
        self.margin_mm = margin_mm
        self.crop_line = crop_line
        self.target_kb = target_kb
        self.dpi_override = dpi_override
        self.export_single = export_single
        self.export_layout = export_layout

    def run(self):
        os.makedirs(self.out_dir, exist_ok=True)
        ok_count = 0
        total = len(self.jobs)
        for idx, job in enumerate(self.jobs, start=1):
            path = job["path"]
            spec = job["spec"]
            bg = job["bg"]
            transform: Optional[ManualTransform] = job.get("transform")
            stem = job.get("stem") or os.path.splitext(os.path.basename(path))[0]
            self.progress.emit(idx, total, "处理 %s" % os.path.basename(path))
            try:
                img = load_photo(path)
                res = self.proc.process(img, spec, bg=bg)
                photo = res.standard_bgr
                if transform is not None:
                    photo = self.proc.recrop(res, transform)

                dpi = self.dpi_override or spec.dpi
                tag = "%s_%s_%s" % (stem, spec.id, bg)
                msgs = []

                if self.export_single:
                    single = os.path.join(self.out_dir, "%s.jpg" % tag)
                    # 分辨率若与规格不同，像素跟着缩放，打印尺寸（毫米）保持不变
                    out_img = resample_to_dpi(photo, spec.mm_size, dpi)
                    rep = save_image(out_img, single, dpi=dpi,
                                     target_kb=self.target_kb or None,
                                     max_kb=spec.kb_limits[1],
                                     min_kb=spec.kb_limits[0])
                    msgs.append("单张 %.1fKB" % rep.kb)
                    if not rep.ok():
                        msgs.append("(单张未满足大小/dpi约束)")

                if self.export_layout:
                    # 纸和照片统一按同一个 dpi 换算（见 layout.plan_for_spec）：
                    # 混用会让 350dpi 的一寸规格少排 3 张。
                    plan = plan_for_spec(self.paper, spec, gap_mm=self.gap_mm,
                                         margin_mm=self.margin_mm, dpi=dpi)
                    if plan.is_empty:
                        msgs.append("该相纸排不下")
                    else:
                        canvas = render_layout(photo, plan, crop_line=self.crop_line)
                        lp = os.path.join(self.out_dir,
                                          "%s_%s排版.jpg" % (tag, self.paper.id))
                        save_image(canvas, lp, dpi=dpi)
                        msgs.append("%s排%d张" % (self.paper.name_zh, plan.count))

                ok_count += 1
                self.itemDone.emit(path, True, "；".join(msgs))
            except Exception as e:                    # noqa: BLE001
                self.itemDone.emit(path, False, "失败：%s" % e)
        self.allDone.emit(ok_count, total)
