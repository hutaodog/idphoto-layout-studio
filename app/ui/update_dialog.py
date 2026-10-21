# -*- coding: utf-8 -*-
"""更新对话框：发现新版本 → 看更新说明 → 下载并更新。

设计要点：
* **非模态**（`setModal(False)`）：检查更新不该把用户卡住，他要继续干活就点"以后再说"；
* 三块内容：标题（当前版本 → 新版本）、更新说明（只读文本）、进度条；
* 按钮随状态变化：可更新时是「下载并更新」，下载中是「取消」，完成后自动关闭；
* 源码运行时（`kind == "source"`）不给自动更新，只提供「打开下载页面」。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QTextBrowser, QVBoxLayout)

from ..core import updater
from .. import __version__
from . import style
from .update_worker import UpdateDownloadWorker


class UpdateDialog(QDialog):
    """检查更新 / 下载更新 的窗口。

    `apply_requested(plan)` 信号发出后，主窗口负责启动新版本进程并退出自己。
    """

    apply_requested = Signal(object)      # UpdatePlan
    skipped = Signal(str)                 # 版本号

    def __init__(self, info: updater.ReleaseInfo, parent=None,
                 kind: Optional[str] = None, auto_check: bool = False):
        super().__init__(parent)
        self.info = info
        self.kind = kind or updater.build_kind()
        self.asset = updater.pick_asset(info, self.kind)
        self.plan = None
        self._worker: Optional[UpdateDownloadWorker] = None

        self.setWindowTitle("检查更新")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(560)
        self.setStyleSheet(style.STYLESHEET + "QDialog{background:%s;}" % style.CARD)

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)

        # ---- 标题 ----
        head = QHBoxLayout()
        head.setSpacing(10)
        self.lbl_title = QLabel("发现新版本 v%s" % info.version)
        f = self.lbl_title.font()
        f.setPointSizeF(f.pointSizeF() + 3.0)
        f.setBold(True)
        self.lbl_title.setFont(f)
        head.addWidget(self.lbl_title)
        head.addStretch(1)
        self.lbl_cur = QLabel("当前 v%s" % __version__)
        self.lbl_cur.setStyleSheet("color:%s;font-size:12px;" % style.MUTED)
        head.addWidget(self.lbl_cur)
        v.addLayout(head)

        # ---- 副标题（下载哪个包 / 多大）----
        if self.asset is not None:
            sub = "将下载 %s（%.1f MB）并自动更新" % (
                "单文件版" if self.kind == "single" else "便携文件夹版", self.asset.mb)
        else:
            sub = "源码运行，不自动更新；点下面的按钮去 Release 页面手动下载"
        self.lbl_sub = QLabel(sub)
        self.lbl_sub.setStyleSheet("color:%s;font-size:12px;" % style.MUTED_STRONG)
        self.lbl_sub.setWordWrap(True)
        v.addWidget(self.lbl_sub)

        # ---- 更新说明（GitHub 的 body 是 Markdown，用 QTextBrowser 渲染，别直接怼原文）----
        self.txt = QTextBrowser()
        self.txt.setOpenExternalLinks(True)
        self.txt.setMinimumHeight(150)
        self.txt.setMaximumHeight(220)
        self.txt.setStyleSheet(
            "QTextBrowser{background:#fafbfc;border:1px solid %s;border-radius:8px;"
            "color:%s;font-size:12px;padding:8px;}" % (style.BORDER, style.MUTED_STRONG))
        notes = (info.notes or "").strip() or "（这个版本没有写更新说明）"
        try:
            self.txt.setMarkdown(notes)          # Qt 5.14+ / 6.x 都支持
        except Exception:                        # noqa: BLE001
            self.txt.setPlainText(notes)
        v.addWidget(self.txt)

        # ---- 进度 ----
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        self.bar.setMaximumHeight(10)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color:%s;font-size:12px;" % style.MUTED)
        self.lbl_progress.setVisible(False)
        v.addWidget(self.lbl_progress)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background:%s;max-height:1px;border:none;" % style.BORDER)
        v.addWidget(line)

        # ---- 按钮 ----
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_page = QPushButton("打开下载页面")
        self.btn_page.setObjectName("ghost")
        self.btn_page.clicked.connect(self._open_page)
        btns.addWidget(self.btn_page)
        btns.addStretch(1)

        self.btn_skip = QPushButton("跳过这个版本")
        self.btn_skip.setObjectName("ghost")
        self.btn_skip.clicked.connect(self._on_skip)
        btns.addWidget(self.btn_skip)

        self.btn_later = QPushButton("以后再说")
        self.btn_later.setObjectName("ghost")
        self.btn_later.clicked.connect(self.reject)
        btns.addWidget(self.btn_later)

        self.btn_go = QPushButton("下载并更新")
        self.btn_go.setObjectName("primary")
        self.btn_go.setMinimumWidth(130)
        self.btn_go.setDefault(True)
        self.btn_go.setEnabled(self.asset is not None)
        self.btn_go.clicked.connect(self._on_go)
        btns.addWidget(self.btn_go)
        v.addLayout(btns)

        if auto_check:
            self.lbl_progress.setVisible(True)
            self.lbl_progress.setText("启动时自动检查发现的更新；可在「帮助」菜单里关掉自动检查。")

    # ------------------------------------------------------------------ 动作
    def _open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self.info.page_url or updater.RELEASES_PAGE))

    def _on_skip(self) -> None:
        updater.save_state(skipped=self.info.version)
        self.skipped.emit(self.info.version)
        self.reject()

    def _on_go(self) -> None:
        if self.asset is None:
            self._open_page()
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_go.setEnabled(False)
        self.btn_later.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.bar.setVisible(True)
        self.lbl_progress.setVisible(True)
        self.lbl_progress.setText("正在下载…")
        self.btn_go.setText("正在下载…")

        w = UpdateDownloadWorker(self.info, self.kind, parent=self)
        w.progress.connect(self._on_progress)
        w.ok.connect(self._on_downloaded)
        w.fail.connect(self._on_failed)
        w.cancelled.connect(self._on_cancelled)
        self._worker = w
        w.start()

    def cancel_download(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.lbl_progress.setText("正在取消…")

    # ------------------------------------------------------------------ 回调
    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = int(done * 100 / total)
            self.bar.setValue(max(0, min(100, pct)))
            self.lbl_progress.setText("正在下载… %.1f / %.1f MB（%d%%）" % (
                done / 1048576.0, total / 1048576.0, pct))
        else:
            self.bar.setRange(0, 0)
            self.lbl_progress.setText("正在下载… %.1f MB" % (done / 1048576.0))

    def _on_downloaded(self, plan) -> None:
        self.plan = plan
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.lbl_progress.setText("下载并校验完成，正在重启完成更新…")
        self.btn_go.setText("正在更新…")
        self.apply_requested.emit(plan)

    def _on_failed(self, msg: str) -> None:
        self.bar.setVisible(False)
        self.lbl_progress.setVisible(True)
        self.lbl_progress.setText("下载失败：%s" % msg.splitlines()[0])
        self.btn_go.setEnabled(True)
        self.btn_go.setText("重试")
        self.btn_later.setEnabled(True)
        self.btn_skip.setEnabled(True)

    def _on_cancelled(self) -> None:
        self.bar.setVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.lbl_progress.setText("已取消下载（没有改动任何文件）")
        self.btn_go.setEnabled(True)
        self.btn_go.setText("下载并更新")
        self.btn_later.setEnabled(True)
        self.btn_skip.setEnabled(True)

    def closeEvent(self, e):                                # noqa: N802
        self.cancel_download()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)         # 让线程收尾，再让对话框被销毁
        super().closeEvent(e)
