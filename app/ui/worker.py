# -*- coding: utf-8 -*-
"""单张照片的后台处理。底色和手动构图由界面用最新设置渲染。"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from ..core.pipeline import PipelineError, Processor, load_photo
from ..core.specs import PhotoSpec


@dataclass(frozen=True)
class PhotoRequest:
    id: int
    path: str
    spec: PhotoSpec
    hollow_fix: bool


class ProcessWorker(QThread):
    ok = Signal(int, object)
    fail = Signal(int, str)

    def __init__(self, proc: Processor, request: PhotoRequest, parent=None):
        super().__init__(parent)
        self.proc = proc
        self.request = request

    def run(self):
        req = self.request
        try:
            img = load_photo(req.path)
            res = self.proc.process(img, req.spec, bg=None, hollow_fix=req.hollow_fix)
        except PipelineError as e:
            self.fail.emit(req.id, str(e))
        except Exception as e:                         # noqa: BLE001
            self.fail.emit(req.id, "未预期的错误：%r" % (e,))
        else:
            self.ok.emit(req.id, res)
