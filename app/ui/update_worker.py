# -*- coding: utf-8 -*-
"""更新相关的后台线程（检查 / 下载）。

网络请求一律丢到 QThread 里，别卡界面。信号都用 object/str/int，不传 Qt 类型，
方便在无界面环境（测试）里直接调用 run()。
"""
from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..core import updater


class UpdateCheckWorker(QThread):
    """查 GitHub 上有没有新版本。"""

    ok = Signal(object)          # ReleaseInfo
    fail = Signal(str)

    def __init__(self, parent=None, timeout: float = 20.0):
        super().__init__(parent)
        self.timeout = timeout

    def run(self):                                          # noqa: D401
        try:
            self.ok.emit(updater.fetch_latest(timeout=self.timeout))
        except Exception as e:                              # noqa: BLE001
            self.fail.emit(str(e) or repr(e))


class UpdateDownloadWorker(QThread):
    """下载新版本（含校验 + 解压），返回 UpdatePlan。"""

    progress = Signal(int, int)      # 已下字节, 总字节（总长未知时为 0）
    ok = Signal(object)              # UpdatePlan
    fail = Signal(str)
    cancelled = Signal()

    def __init__(self, info, kind: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.info = info
        self.kind = kind
        self._stop = threading.Event()

    def cancel(self) -> None:
        self._stop.set()

    def _should_stop(self) -> bool:
        return self._stop.is_set()

    def run(self):                                          # noqa: D401
        try:
            plan = updater.prepare_update(
                self.info, kind=self.kind,
                progress=lambda done, total: self.progress.emit(int(done), int(total)),
                should_stop=self._should_stop)
            if self._stop.is_set():
                self.cancelled.emit()
                return
            self.ok.emit(plan)
        except updater.UpdateCancelled:
            self.cancelled.emit()
        except Exception as e:                              # noqa: BLE001
            self.fail.emit(str(e) or repr(e))
