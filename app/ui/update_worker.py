# -*- coding: utf-8 -*-
"""更新相关的后台线程（检查 / 下载）。

网络请求一律丢到 QThread 里，别卡界面。信号都用 object/str/int，不传 Qt 类型，
方便在无界面环境（测试）里直接调用 run()。
"""
from __future__ import annotations

import threading
from typing import List, Optional, Sequence

from PySide6.QtCore import QThread, Signal

from ..core import updater


class UpdateCheckWorker(QThread):
    """并发探测所有更新源（GitHub + 自建节点…），挑延迟最低的那个。"""

    ok = Signal(object)          # updater.BestRelease
    fail = Signal(str)

    def __init__(self, parent=None, timeout: float = updater.PROBE_TIMEOUT_S,
                 sources: Optional[Sequence[updater.Source]] = None):
        super().__init__(parent)
        self.timeout = timeout
        self.sources = list(sources) if sources else None

    def run(self):                                          # noqa: D401
        try:
            self.ok.emit(updater.fetch_latest_best(self.sources, self.timeout))
        except Exception as e:                              # noqa: BLE001
            self.fail.emit(str(e) or repr(e))


class UpdateDownloadWorker(QThread):
    """用测速选出来的源下载新版本（含校验 + 解压），返回 UpdatePlan。"""

    progress = Signal(int, int)      # 已下字节, 总字节（总长未知时为 0）
    ok = Signal(object)              # UpdatePlan
    fail = Signal(str)
    cancelled = Signal()

    def __init__(self, best, kind: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.best = best                  # updater.BestRelease
        self.kind = kind
        self._stop = threading.Event()

    def cancel(self) -> None:
        self._stop.set()

    def _should_stop(self) -> bool:
        return self._stop.is_set()

    def run(self):                                          # noqa: D401
        try:
            plan, _best = updater.prepare_update_best(
                kind=self.kind, best=self.best,
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


def describe_sources(best) -> List[str]:
    """把"每个源的延迟/结果"整理成可读的行（对话框里展示用）。"""
    lines = []
    chosen = getattr(best, "source", None)
    for r in getattr(best, "candidates", []) or []:
        if r.ok:
            mark = "[*]" if r.source is chosen else "[ ]"
            lines.append("%s %s：%d ms，v%s" % (
                mark, r.source.name, int(r.latency_ms), r.info.version))
        else:
            lines.append("[x] %s：不可用（%s）" % (r.source.name, (r.error or "")[:60]))
    return lines
