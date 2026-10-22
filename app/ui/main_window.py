# -*- coding: utf-8 -*-
"""主窗口。

布局（按用户反馈重排：导出按钮从工具栏挪到右下角固定操作栏，不再需要找）：
    菜单栏
    工具栏：导入照片 / 批量导入 / 打开输出目录
    ┌────────┬──────────────┬────────────────┐
    │ 照片列表 │   预览画布     │  参数面板(滚动)  │
    │        │              │ 1规格 2底色 3微调 │
    │        │              │ 4相纸 5输出      │
    ├────────┴──────────────┴────────────────┤
    │ 底部操作栏：[输出目录] [导出证件照][导出排版照][导出全部] │
    └────────────────────────────────────────┘
    状态栏

交互要点：
- 预览图上按住拖动=平移，滚轮=缩放，双击=复位（毫秒级重裁，不重跑模型）
- 所有数字框/滑块/下拉框**任何时候都不吃滚轮**（鼠标停在上面滚页面不会误改数值）
- 换底色是即时的，手动微调模式下也即时生效
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox,
                               QColorDialog, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenuBar, QProgressBar, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy,
                               QSplitter, QStatusBar, QToolBar, QVBoxLayout,
                               QWidget)

from ..core.exporter import resample_to_dpi, save_image
from ..core.layout import (DEFAULT_GAP_MM, DEFAULT_MARGIN_MM, plan_for_spec,
                           plan_layout, render_layout)
from .. import __version__
from ..core import updater
from ..core.pipeline import ManualTransform, Processor
from ..core.specs import SpecLibrary
from . import chrome, layouts, style
from .preview import PreviewCanvas
from .update_dialog import UpdateDialog
from .update_worker import (UpdateCheckWorker, UpdateDownloadWorker)
from .widgets import (CheckBox, ColorSwatch, NoWheelComboBox, NoWheelDoubleSpinBox,
                      NoWheelSlider, NoWheelSpinBox, PillButton, show_message)
from .worker import BatchExportWorker, ProcessWorker

IMAGE_FILTER = "图片 (*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff);;所有文件 (*.*)"
APP_TITLE = "证件照排版助手"

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def _is_image_path(path: str) -> bool:
    """拖进来的文件是不是图片（拖拽只看后缀，够用了）。"""
    return os.path.splitext(path or "")[1].lower() in IMAGE_EXTS


def default_out_dir() -> str:
    """默认输出目录：**程序目录下的「输出」**（不可写才退回「图片\\证件照输出」）。

    两个坑都踩过，别再改回去：
    1. **不能**用 `__file__` 往上推三层：打包成单文件后那里是 PyInstaller 的临时解压目录
       （`_MEIxxxx`），程序退出时会被整个删掉——用户截图里的默认输出目录正是
       `...\\成品软件\\_MEI00038102\\输出`，导出的照片会跟着临时目录一起消失。
       `app/paths.py` 用的是 `sys.executable` 的目录，指向真正的 exe 所在处，不会踩这个坑。
    2. 也不要往 `C:\\Users\\...\\Pictures` 丢：用户明确要求"都在工作区内，别往 C 盘写"。
    """
    from ..paths import default_out_dir as _impl
    return _impl()


@dataclass
class PhotoItem:
    path: str
    result: object = None
    error: str = ""
    transform: Optional[ManualTransform] = None
    bg: Optional[str] = None
    spec_id: Optional[str] = None

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


class MainWindow(QMainWindow):
    def __init__(self, lib: Optional[SpecLibrary] = None):
        super().__init__()
        self.lib = lib or SpecLibrary.load()
        self.proc = Processor(lib=self.lib)
        self.items: List[PhotoItem] = []
        self.current: Optional[PhotoItem] = None
        self.result = None
        self.transform = ManualTransform()
        self.manual_mode = False
        self.preview_layout_mode = False
        self._worker: Optional[ProcessWorker] = None
        self._batch: Optional[BatchExportWorker] = None
        self._pending_reprocess = False
        self._bg = "white"
        # 输出目录：用户设过的（settings.json）优先；没设过或那个目录已经不可用就用默认。
        self._out_dir = self._saved_out_dir() or default_out_dir()
        self.layout_id = layouts.DEFAULT_LAYOUT
        self._layout_actions: Dict[str, QAction] = {}
        # 整窗都接拖进来的图片：只在预览卡片上放 DropArea 时，用户把文件放到
        # 左边参数区/工具栏上就"没反应"（第二张图经常就是这么丢的）。
        self.setAcceptDrops(True)
        self._drop_hot = False
        # 追加一段"毛玻璃模式"的覆盖样式：
        # 窗口自己不能再刷底色（否则 DWM 的模糊被盖住），提示框也要半透明。
        self.setStyleSheet(style.STYLESHEET + """
QMainWindow { background: transparent; }
QToolTip { background: rgba(43, 50, 66, 0.94); }
""")
        self._build_ui()
        self._refresh_spec_list()
        self._update_layout_info()
        self._sync_color_buttons()
        self._check_weights()

    # ==================== 界面搭建 ====================
    @staticmethod
    def _saved_out_dir() -> str:
        """用户在 settings.json 里记住的输出目录（不可用就返回空串）。"""
        try:
            from ..core import settings as _settings
            return _settings.get_out_dir()
        except Exception:                                 # noqa: BLE001
            return ""

    def _build_ui(self) -> None:
        """一次性搭建：窗口外壳 + 菜单 + 工具栏 + 状态栏，然后按布局装配主体。

        主体装配在 _assemble() 里，换布局时只重跑那一步（不重建整个窗口）。
        """
        self.setWindowTitle(APP_TITLE)
        self.resize(1340, 860)
        self.setMinimumSize(1080, 700)

        # 无边框 + 自绘圆角外壳；IDPHOTO_FRAME=native 可退回系统边框（保底）
        self._frameless = not chrome.native_frame_forced()
        # 毛玻璃：**只用分层半透明窗口**（"layered"）。
        # 试过 Win11 的系统亚克力（DWM backdrop）：设置本身成功（backdrop_type=3、
        # corner_pref=2 圆角），但 Qt 的非分层窗口会用不透明底色把整个窗口表面填掉，
        # 模糊被盖住，表现就是用户看到的"灰不拉几"，而且圆角外面还多一块方块。
        # 分层窗口则相反：桌面能真透出来（空隙就是透明的），代价是系统不给做模糊。
        # 所以这里选"真透出桌面"这条路；卡片自己的玻璃质感负责"毛玻璃"的观感。
        glass_off = os.environ.get("IDPHOTO_GLASS", "").strip().lower() in ("off", "0", "none")
        self._glass_req = "none" if glass_off else "layered"
        if self._frameless:
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            if self._glass_req != "none":
                self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.status = QStatusBar()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.setVisible(False)
        self.status.addPermanentWidget(self.progress)
        self.status.showMessage("就绪")

        self.menubar = QMenuBar()
        self._build_menu()
        self.toolbar = self._build_toolbar()
        self._assemble()

    def _assemble(self) -> None:
        """按 self.layout_id 装配主体；换布局时也走这里。"""
        self.split = None                      # 只有 classic 布局会设置它
        body = layouts.build(self, self.layout_id)

        if self._frameless:
            page, bar = chrome.wrap(self, APP_TITLE, __version__,
                                    self.toolbar, body, self.status, glass=True,
                                    backdrop=(self._glass_req == "backdrop"))
            bar.attach_menubar(self.menubar)
        else:
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 0, 0, 0)
            pv.setSpacing(0)
            pv.addWidget(self.menubar)
            pv.addWidget(self.toolbar)
            pv.addWidget(body, 1)
            pv.addWidget(self.status)

        old = self.takeCentralWidget()
        self.setCentralWidget(page)
        if old is not None:
            old.deleteLater()
        # 「恢复默认布局」只对能拖卡片的界面有意义（工作台那套是普通布局，拖不动）
        act = getattr(self, "act_reset_layout", None)
        if act is not None:
            act.setVisible(getattr(self, "glass_stage", None) is not None)

    def showEvent(self, event):                            # noqa: N802
        """第一次显示后挂毛玻璃（需要原生窗口句柄，不能在 __init__ 里做）。"""
        super().showEvent(event)
        if not getattr(self, "_update_timers_armed", False):
            # 更新相关：先清上次更新留下的临时文件，再（延时）静默查一次新版本。
            # 都放进延时的定时器里，别让启动路径被网络/磁盘操作拖慢；
            # 和"是不是无边框窗口"无关，所以放在最前面。
            self._update_timers_armed = True
            QTimer.singleShot(2000, updater.cleanup_stale)
            QTimer.singleShot(2200, self._report_last_update)
            QTimer.singleShot(4000, self._maybe_auto_check)
        if not self._frameless or getattr(self, "_glass_done", False):
            return
        self._glass_done = True
        if self._glass_req == "none":
            self.glass_mode = "disabled"
            self.status.showMessage("已关闭毛玻璃（IDPHOTO_GLASS=off）")
            return
        try:
            from . import acrylic
            # layered=True：分层窗口必须走 SCA 亚克力，走 DWM backdrop 会变成一块灰
            self.glass_mode = acrylic.enable_glass(
                int(self.winId()), layered=(self._glass_req == "layered"))
        except Exception as e:                            # noqa: BLE001
            self.glass_mode = "none"
            print("[glass] 启用失败: %r" % (e,))
        if self.glass_mode == "none":
            self.status.showMessage("系统不支持毛玻璃，已降级：桌面仍可从卡片空隙透出")
        self._apply_round_region()
        # 有些布局（工作台）的左列宽度是按内容算的，而**建的时候控件还没应用样式和字体**，
        # 量出来的宽度偏小、摘要文字会被裁。显示出来之后再量一次才是准的。
        refit = getattr(self, "left_refit", None)
        if callable(refit):
            refit()

    def reset_layout(self) -> None:
        """把卡片摆回默认位置和大小。

        用户把卡片拖乱之后必须能一键还原 —— 没有这个入口的话，
        "拉不回去了"就只能靠重开程序（用户实测就是这么反馈的）。
        """
        stage = getattr(self, "glass_stage", None)
        if stage is None:
            return
        stage.reset_to_default()
        self.status.showMessage("已恢复默认布局")

    def _apply_round_region(self) -> None:
        """窗口四角切圆角。

        顺序有讲究（都是实机量出来的，见 `acrylic.set_round_corners` 的注释）：
        1. 先让 **DWM** 把窗口切圆 —— 对分层窗口只有这条真管用，还自带窗口阴影；
        2. DWM 不行（老系统）才退回 `SetWindowRgn`；
        3. 两条都不行就保持直角（不报错，不影响使用）。
        """
        if not self._frameless:
            return
        try:
            from . import acrylic
        except Exception:                                 # noqa: BLE001
            return
        try:
            if acrylic.set_round_corners(int(self.winId())):
                self._round_mode = "dwm"
                return
        except Exception:                                 # noqa: BLE001
            pass
        if self._glass_req == "none":
            self._round_mode = "none"
            return
        try:
            ok = acrylic.apply_round_region(int(self.winId()), self.width(),
                                            self.height(), chrome.RADIUS + 4)
            self._round_mode = "rgn" if ok else "none"
        except Exception:                                 # noqa: BLE001
            self._round_mode = "none"

    def nativeEvent(self, eventType, message):             # noqa: N802
        """Windows 原生消息：给无边框窗口补上边缘缩放热区。

        没有这一步的话，玻璃模式下 Frame 的外圈只有 2px 能收到鼠标事件，
        用户"根本拉不动窗口大小"（用户原话）。交给系统后自带缩放光标与贴边吸附。
        """
        if getattr(self, "_frameless", False):
            hit = chrome.native_hit_test(self, message)
            if hit is not None:
                return True, hit
        return super().nativeEvent(eventType, message)

    def resizeEvent(self, event):                          # noqa: N802
        super().resizeEvent(event)
        if getattr(self, "_glass_done", False):
            self._apply_round_region()

    def changeEvent(self, event):                          # noqa: N802
        """最大化/还原/从最小化恢复时，窗口尺寸会变，圆角区域要跟着重设。

        不重设的话，最大化之后四角会退回直角（用户反馈过"四个角还是直角"）。
        """
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and getattr(self, "_glass_done", False):
            self._apply_round_region()
            refit = getattr(self, "left_refit", None)
            if callable(refit):
                refit()

    def set_layout(self, key: str) -> None:
        """切换界面布局（保留接口；v1.3.0 起只有卡片仪表盘一套）。"""
        if key not in layouts.keys() or key == getattr(self, "layout_id", None):
            return
        prev = self.layout_id
        self.layout_id = key
        try:
            self._assemble()
        except Exception as e:                            # noqa: BLE001
            # 保险：万一某套布局装配失败（比如打包时这个模块没被收集到），
            # 退回原来那套并提示，绝不让整个程序崩掉。
            self.layout_id = prev
            try:
                self._assemble()
            except Exception:                             # noqa: BLE001
                pass
            self._sync_layout_menu()
            show_message(self, "切换布局失败",
                         "「%s」这套布局装配出错，已退回原来的布局。\n\n%s"
                         % (layouts.module_for(key).NAME, e), kind="error")
            return
        self._sync_layout_menu()
        # 控件都是新建的实例：列表条目要按 self.items 重建，否则会出现
        # "预览里有图、左边列表却是空的"这种自相矛盾状态
        self._rebuild_photo_list()
        self._refresh_spec_list()
        self._update_layout_info()
        self._sync_color_buttons()
        self.refresh_preview()
        self.status.showMessage("界面布局：%s" % layouts.module_for(key).NAME)

    def _sync_layout_menu(self) -> None:
        cur = getattr(self, "layout_id", layouts.DEFAULT_LAYOUT)
        for key, act in getattr(self, "_layout_actions", {}).items():
            act.setChecked(key == cur)

    def _apply_split_proportions(self) -> None:
        """按窗口宽度分配三栏宽度。

        以前是 `setSizes([210, 620, 470])` 一把定死，再加 stretch=(0,1,0)：窗口放大后
        **多出来的宽度全给了中间预览**。在 2541px 宽的窗口上实测左栏 210、右栏 470、
        画布 1813 —— 所有设置挤在 470px 里，中间一大片空灰，用户反馈"布局太紧凑了"。
        现在左右两栏跟着窗口按比例长（有上下限），中间吃剩下的。
        """
        if getattr(self, "split", None) is None:
            return
        w = max(self.width(), self.minimumWidth())
        left = int(min(320, max(210, w * 0.115)))
        right = int(min(780, max(470, w * 0.30)))
        center = max(360, w - left - right - 30)
        self.split.setSizes([left, center, right])

    def resizeEvent(self, event):                          # noqa: N802
        super().resizeEvent(event)
        # 用户没自己拖过分隔条时，跟着窗口宽度重新分配；拖过之后就不再动它
        if not getattr(self, "_user_split", True):
            self._apply_split_proportions()

    def _build_menu(self) -> None:
        m_file = self.menubar.addMenu("文件")
        for text, slot, sc in (("导入照片", self.on_import, "Ctrl+O"),
                               ("批量导入", self.on_import_many, "Ctrl+Shift+O")):
            a = QAction(text, self)
            a.setShortcut(sc)
            a.triggered.connect(slot)
            m_file.addAction(a)
        m_file.addSeparator()
        for text, slot, sc in (("导出证件照", self.on_export_single_only, "Ctrl+S"),
                               ("导出排版照", self.on_export_layout_only, "Ctrl+L"),
                               ("导出全部照片", self.on_export_all, "Ctrl+Shift+S")):
            a = QAction(text, self)
            a.setShortcut(sc)
            a.triggered.connect(slot)
            m_file.addAction(a)
        m_file.addSeparator()
        a = QAction("恢复默认布局", self)
        a.setShortcut("Ctrl+0")
        a.triggered.connect(self.reset_layout)
        m_file.addAction(a)
        m_file.addSeparator()
        a = QAction("打开输出目录", self)
        a.triggered.connect(self.on_open_out_dir)
        m_file.addAction(a)
        a = QAction("退出", self)
        a.triggered.connect(self.close)
        m_file.addAction(a)

        m_help = self.menubar.addMenu("帮助")
        self.act_check_update = QAction("检查更新…", self)
        self.act_check_update.triggered.connect(lambda: self.on_check_update(silent=False))
        m_help.addAction(self.act_check_update)

        # 启动时自动检查（默认开）。存盘在 .update_state.json，关掉就彻底不联网。
        st = updater.load_state()
        self.act_auto_check = QAction("启动时自动检查更新", self)
        self.act_auto_check.setCheckable(True)
        self.act_auto_check.setChecked(bool(st.get("auto_check", True)))
        self.act_auto_check.toggled.connect(self._on_auto_check_toggled)
        m_help.addAction(self.act_auto_check)
        m_help.addSeparator()

        a = QAction("关于 / 开源许可", self)
        a.triggered.connect(self.on_about)
        m_help.addAction(a)

    # ==================== 检查更新 ====================
    def _on_auto_check_toggled(self, on: bool) -> None:
        updater.save_state(auto_check=bool(on))
        self.status.showMessage("启动时自动检查更新：%s" % ("开" if on else "关"))

    def _maybe_auto_check(self) -> None:
        """启动后静默查一次（24 小时内只查一次，且可以在菜单里关掉）。"""
        if os.environ.get("IDPHOTO_NO_UPDATE", "").strip().lower() in ("1", "on", "true"):
            return
        if not updater.should_auto_check():
            return
        self.on_check_update(silent=True)

    def _report_last_update(self) -> None:
        """上一次自动更新如果失败了，启动后主动告诉用户（不然他只会觉得"怎么还是旧版"）。"""
        note = os.path.join(updater.app_dir(), ".logs", "更新失败.txt")
        if not os.path.exists(note):
            return
        try:
            with open(note, "r", encoding="utf-8", errors="replace") as f:
                detail = f.read()[-1500:]
        except OSError:
            detail = ""
        try:
            os.remove(note)
        except OSError:
            pass
        show_message(self, "上次自动更新没成功",
                     "程序已经回到原来的版本，可以继续正常使用。\n\n"
                     "想再试一次就点「帮助 → 检查更新…」；一直失败的话，"
                     "建议直接去 Release 页面下载新的安装包。",
                     kind="warn", detail=detail)

    def on_check_update(self, silent: bool = False) -> None:
        """并发探测所有更新源，挑延迟最低的。silent=True 是启动时的静默检查，失败不打扰用户。"""
        if getattr(self, "_checking_update", False):
            return
        self._checking_update = True
        if not silent:
            self.status.showMessage("正在检查更新（同时给自己节点和 GitHub 测速）…")
        w = UpdateCheckWorker(self)
        w.ok.connect(lambda best: self._on_update_info(best, silent))
        w.fail.connect(lambda msg: self._on_update_error(msg, silent))
        w.finished.connect(lambda: setattr(self, "_checking_update", False))
        self._update_checker = w          # 保住引用，别被 GC 掉
        w.start()

    def _on_update_info(self, best, silent: bool) -> None:
        """best 是 updater.BestRelease（含所选源与测速结果）；兼容直接给 ReleaseInfo。"""
        if isinstance(best, updater.BestRelease):
            info, src, ms = best.info, best.source, best.latency_ms
        else:
            info, src, ms = best, None, 0.0
        updater.save_state(last_check=time.time())
        if not updater.is_newer(info.version, __version__):
            if not silent:
                extra = "（更新源：%s %d ms）" % (src.name, int(ms)) if src else ""
                show_message(self, "已是最新版本",
                             "当前 v%s 就是最新版本。%s" % (__version__, extra),
                             kind="info")
            return
        st = updater.load_state()
        if silent and st.get("skipped") == info.version:
            return                        # 用户说过"跳过这个版本"
        self._open_update_dialog(best, auto=silent)

    def _on_update_error(self, msg: str, silent: bool) -> None:
        if silent:
            self.status.showMessage("检查更新失败（不影响使用）")
            return
        show_message(self, "检查更新失败",
                     "所有更新源都连不上（GitHub 和你自己的节点）。\n\n"
                     "可以稍后再试，或者直接去 Release 页面手动下载。",
                     kind="warn", detail=msg)

    def _open_update_dialog(self, best, auto: bool = False) -> None:
        dlg = UpdateDialog(best, parent=self, auto_check=auto)
        dlg.start_update.connect(self._start_update)
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._update_dialog = dlg
        dlg.show()
        dlg.raise_()

    # ---------- 更新：主界面让位给独立的更新小窗 ----------
    def _start_update(self, best) -> None:
        """用户点了「下载并更新」：**先让主界面退场**，再用一个独立小窗显示下载/合并进度。

        为什么先关主界面：更新最后要覆盖 exe 本体，Windows 不允许覆盖正在运行的程序。
        主界面先隐藏 → 下载小窗（仍是本进程）→ 下完把活交给"新版本自己的进程"去合并
        → 本进程退出 → 新进程合并完自己拉起新版本、小窗消失。
        """
        from .task_window import TaskWindow

        dlg = getattr(self, "_update_dialog", None)
        if dlg is not None:
            dlg.hide()
        self._prev_visible = self.isVisible()
        self.hide()                                   # 主界面退场（≒ "把软件本体关了"）

        win = TaskWindow("正在更新到 v%s" % (best.info.version or "新版本"),
                         "下载完会自动合并并重新打开，你不用管。",
                         total=updater.pick_asset(best.info).size if
                         updater.pick_asset(best.info) else 0,
                         cancellable=True)
        win.set_badge("更")
        notes = (best.info.notes or "").strip()
        if notes:
            first = [ln.strip("# ").strip() for ln in notes.splitlines() if ln.strip()]
            win.set_note("本次更新：" + "；".join(first[:3])[:180])
        win.set_status("正在下载…", indeterminate=True)
        self._task_win = win
        win.cancel_requested.connect(lambda: self._cancel_update(win))
        win.show()
        win.raise_()

        w = UpdateDownloadWorker(best, None, parent=self)
        w.progress.connect(lambda d, t: (win.set_status("正在下载…"),
                                         win.set_progress(d, t)))
        w.ok.connect(lambda plan: self._update_downloaded(plan, win))
        w.fail.connect(lambda msg: self._update_failed(msg, win))
        w.cancelled.connect(lambda: self._cancel_update(win))
        self._update_downloader = w
        w.start()

    def _update_downloaded(self, plan, win) -> None:
        """下载 + 校验 + 解压都好了 → 交给新版本进程去做合并（带它自己的窗口）。"""
        geom = "%d,%d,%d,%d" % (win.x(), win.y(), win.width(), win.height())
        try:
            updater.spawn_applier(plan, old_pid=os.getpid(), ui=True, geom=geom)
        except Exception as e:                            # noqa: BLE001
            win.set_error("没法启动合并进程", "%r\n%s" % (e, plan.staging))
            win.btn_ok.clicked.connect(lambda: self._restore_after_failed_update(win))
            return
        win.set_status("下载完成，正在合并文件…", indeterminate=True)
        # 主界面和下载小窗一起退场；合并窗口会在同一位置出现
        QTimer.singleShot(120, win.close)
        QTimer.singleShot(220, self._quit_app)

    def _quit_app(self) -> None:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _update_failed(self, msg: str, win) -> None:
        win.set_error("下载失败（可以点「取消」回到程序）", str(msg)[:400])
        win.btn_cancel.setText("回到程序")
        win.btn_cancel.setEnabled(True)

    def _cancel_update(self, win) -> None:
        w = getattr(self, "_update_downloader", None)
        if w is not None and w.isRunning():
            w.cancel()
            return
        self._restore_after_failed_update(win)

    def _restore_after_failed_update(self, win) -> None:
        """更新没做成：把主界面恢复回来，别让用户以为程序没了。"""
        try:
            win.close()
        except Exception:                                # noqa: BLE001
            pass
        dlg = getattr(self, "_update_dialog", None)
        if dlg is not None and not dlg.isVisible():
            dlg.deleteLater()
        self._update_dialog = None
        self.show()
        self.raise_()
        self.status.showMessage("已取消更新，还是原来的 v%s" % __version__)

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        self.act_import = QAction("+  导入照片", self)
        self.act_import.setShortcut("Ctrl+O")
        self.act_import.triggered.connect(self.on_import)
        self.act_import_many = QAction("批量导入", self)
        self.act_import_many.triggered.connect(self.on_import_many)
        self.act_open_out = QAction("打开输出目录", self)
        self.act_open_out.triggered.connect(self.on_open_out_dir)
        self.act_reset_layout = QAction("恢复默认布局", self)
        self.act_reset_layout.setToolTip("把卡片摆回默认位置和大小（Ctrl+0）")
        self.act_reset_layout.triggered.connect(self.reset_layout)
        for a in (self.act_import, self.act_import_many):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_open_out)
        tb.addSeparator()
        tb.addAction(self.act_reset_layout)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # 三个导出按钮放**顶部工具栏右侧**（用户要求"移到上面、做醒目一点"）。
        # `_build_action_bar()` 顺带创建了 win.btn_export_*、win.lbl_out 并连好信号，
        # 这里把它们取出来放到工具栏；动作栏本身丢掉。
        bar = self._build_action_bar()
        out_label = self.lbl_out
        out_label.setMinimumWidth(0)
        out_label.setWordWrap(False)
        out_label.setParent(self)
        # 输出目录那行**放状态栏**（常驻右侧）：工具栏里空间不够，会被挤成 0 宽看不见。
        self.status.addPermanentWidget(out_label)
        self.btn_export_single.setParent(self)
        self.btn_export_layout.setParent(self)
        self.btn_export_all.setParent(self)
        for b in (self.btn_export_single, self.btn_export_layout, self.btn_export_all):
            b.setCursor(Qt.PointingHandCursor)
            tb.addWidget(b)
        # 主按钮再醒目一点：字重加粗（胶囊形状/玻璃质感由 PillButton 自绘，
        # 高度也是它自己定的：普通胶囊 34px、主按钮 38px）
        f = self.btn_export_all.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 0.5)
        self.btn_export_all.setFont(f)
        bar.setParent(None)
        bar.deleteLater()

        self.lbl_tip = QLabel("拖动 = 平移视图　滚轮 = 放大视图　双击 = 复位")
        self.lbl_tip.setToolTip("拖动、滚轮都只动**视图**，不改照片参数；\n"
                                "按住 Ctrl 拖动可以挪照片构图。")
        self.lbl_tip.setStyleSheet("color:%s;padding-left:12px;font-size:12px;"
                                   % style.MUTED)
        tb.addWidget(self.lbl_tip)
        return tb

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(200)
        panel.setMaximumWidth(330)
        v = QVBoxLayout(panel)
        # 标题带 40px（文字贴底、留 5px），让"照片列表"和右栏模块标题、预览卡片上沿
        # 三者在同一条线上
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        title = QLabel("照片列表")
        title.setFixedHeight(40)
        title.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        title.setContentsMargins(2, 0, 0, 5)
        title.setStyleSheet("font-weight:600;color:%s;" % style.MUTED_STRONG)
        self.lbl_photos_title = title      # 抽屉式布局会把它藏起来（抽屉自己有标题）
        v.addWidget(title)
        self.lst_photos = QListWidget()
        self.lst_photos.setSelectionMode(QAbstractItemView.SingleSelection)
        # 文件名长了不要横向滚动条（截图里那根灰色横条很难看）：省略号 + 完整名字放 tooltip
        self.lst_photos.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lst_photos.setTextElideMode(Qt.ElideRight)
        self.lst_photos.currentRowChanged.connect(self.on_photo_selected)
        v.addWidget(self.lst_photos, 1)
        v.addSpacing(10)
        self.lbl_batch = QLabel("还没有导入照片")
        self.lbl_batch.setWordWrap(True)
        self.lbl_batch.setStyleSheet(
            "color:%s;background:%s;border-radius:%dpx;padding:8px 10px;font-size:12px;"
            % (style.MUTED_STRONG, style.CARD, style.RADIUS))
        v.addWidget(self.lbl_batch)
        return panel

    def _build_center_panel(self) -> QWidget:
        self.canvas = PreviewCanvas()
        self.canvas.panned.connect(self.on_canvas_panned)
        self.canvas.zoomed.connect(self.on_canvas_zoomed)
        self.canvas.doubleClicked.connect(self.on_canvas_reset)

        card = QFrame()
        card.setObjectName("previewCard")
        card.setStyleSheet("QFrame#previewCard{background:%s;border:1px solid %s;"
                           "border-radius:%dpx;}" % (style.CARD, style.BORDER,
                                                     style.PANEL_RADIUS))
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 12, 16, 16)
        cv.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(14)
        self.rb_photo = QRadioButton("证件照预览")
        self.rb_photo.setChecked(True)
        self.rb_layout = QRadioButton("排版预览")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_photo)
        grp.addButton(self.rb_layout)
        self.rb_photo.toggled.connect(self.on_preview_mode_changed)
        bar.addWidget(self.rb_photo)
        bar.addWidget(self.rb_layout)
        bar.addStretch(1)
        self.lbl_preview_info = QLabel("")
        self.lbl_preview_info.setStyleSheet("color:%s;font-size:12px;" % style.MUTED)
        bar.addWidget(self.lbl_preview_info)
        cv.addLayout(bar)
        cv.addWidget(self.canvas, 1)

        # 外面再包一层：顶部留出和右栏标题一样高的 24px，三栏正文上沿才对得齐
        holder = QWidget()
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 40, 0, 0)     # 与右栏"标题带 32 + 顶部 8"对齐
        hv.setSpacing(0)
        hv.addWidget(card)
        return holder

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        # 顶部留 8：第一个模块的标题不要贴着工具栏（用户反馈"模块离太近"）
        v.setContentsMargins(0, 8, 4, 0)
        v.setSpacing(0)
        for gb in (self._group_spec(), self._group_bg(), self._group_adjust(),
                   self._group_layout(), self._group_output()):
            v.addWidget(gb)
            # 卡片间距 = 这里 + QGroupBox 的 margin-top(32) = 56px，标题落在中间
            v.addSpacing(24)
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        # 上限要够大，宽屏上参数面板才有地方长（由 _apply_split_proportions 分配）
        scroll.setMinimumWidth(460)
        scroll.setMaximumWidth(800)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return scroll

    # ---------- 各组 ----------
    def _group_spec(self) -> QGroupBox:
        gb = QGroupBox("1 · 证件照规格")
        f = QVBoxLayout(gb)
        f.setContentsMargins(18, 18, 18, 18)
        f.setSpacing(10)
        self.cmb_category = NoWheelComboBox()
        self.cmb_category.currentTextChanged.connect(lambda _=None: self._refresh_spec_list())
        f.addWidget(self.cmb_category)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索：一寸 / 护照 / 美签 …")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(lambda _=None: self._refresh_spec_list())
        f.addWidget(self.ed_search)
        self.lst_specs = QListWidget()
        self.lst_specs.setMinimumHeight(168)
        self.lst_specs.setMaximumHeight(220)
        self.lst_specs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lst_specs.setTextElideMode(Qt.ElideRight)
        self.lst_specs.currentRowChanged.connect(self.on_spec_selected)
        f.addWidget(self.lst_specs)
        self.lbl_spec_info = QLabel("")
        self.lbl_spec_info.setWordWrap(True)
        self.lbl_spec_info.setStyleSheet(
            "color:%s;background:#f7f8fa;border-radius:%dpx;padding:9px 11px;"
            "font-size:12px;" % (style.MUTED_STRONG, style.RADIUS))
        f.addWidget(self.lbl_spec_info)
        return gb

    def _group_bg(self) -> QGroupBox:
        gb = QGroupBox("2 · 背景底色")
        g = QGridLayout(gb)
        g.setContentsMargins(18, 18, 18, 18)
        g.setSpacing(10)
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        self._color_buttons: Dict[str, ColorSwatch] = {}
        cols = 4
        for i, c in enumerate(self.lib.colors):
            btn = ColorSwatch(c.hex, c.name_zh)
            btn.setToolTip("%s %s" % (c.name_zh, c.hex_code))
            btn.clicked.connect(lambda _=False, cid=c.id: self.on_bg_changed(cid))
            self.color_group.addButton(btn)
            self._color_buttons[c.id] = btn
            g.addWidget(btn, i // cols, i % cols)
        rows = (len(self.lib.colors) + cols - 1) // cols
        self.btn_custom_color = QPushButton("自定义颜色…")
        self.btn_custom_color.setObjectName("ghost")
        self.btn_custom_color.clicked.connect(self.on_pick_custom_color)
        g.addWidget(self.btn_custom_color, rows, 0, 1, cols)
        self.lbl_bg = QLabel("")
        self.lbl_bg.setStyleSheet("color:%s;" % style.MUTED)
        g.addWidget(self.lbl_bg, rows + 1, 0, 1, cols)
        return gb

    def _group_adjust(self) -> QGroupBox:
        gb = QGroupBox("3 · 构图微调")
        v = QVBoxLayout(gb)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)

        mode = QHBoxLayout()
        mode.setSpacing(16)
        self.rb_auto = QRadioButton("自动构图")
        self.rb_auto.setChecked(True)
        self.rb_manual = QRadioButton("手动微调")
        mg = QButtonGroup(self)
        mg.addButton(self.rb_auto)
        mg.addButton(self.rb_manual)
        self.rb_auto.toggled.connect(self.on_mode_changed)
        mode.addWidget(self.rb_auto)
        mode.addWidget(self.rb_manual)
        mode.addStretch(1)
        # 「复位」跟模式放在同一行：它只对"手动微调"有意义，占满一整行太浪费
        self.btn_reset = QPushButton("复位为自动构图")
        self.btn_reset.setObjectName("ghost")
        self.btn_reset.clicked.connect(self.on_canvas_reset)
        mode.addWidget(self.btn_reset)
        v.addLayout(mode)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.sl_zoom = self._slider(form, "缩放", -100, 100, 0)
        self.sl_offset_y = self._slider(form, "上下位置", -100, 100, 0)
        self.sl_offset_x = self._slider(form, "左右位置", -100, 100, 0)
        self.sl_rotate = self._slider(form, "旋转 0.1°", -300, 300, 0)
        self.sl_head = self._slider(form, "人脸占高 %", 20, 95, 55)
        self.sl_center = self._slider(form, "脸部垂直位置 %", 10, 80, 42)
        v.addLayout(form)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background:%s;max-height:1px;border:none;" % style.BORDER)
        v.addWidget(line)
        self.cb_hollow = CheckBox("启用抠图内部空洞修补")
        self.cb_hollow.setChecked(True)
        self.cb_hollow.setToolTip("把人像轮廓内的半透明空洞补成不透明，默认开启")
        self.cb_hollow.toggled.connect(lambda _=None: self.reprocess_current())
        v.addWidget(self.cb_hollow)
        return gb

    def _slider(self, form: QFormLayout, label: str, lo: int, hi: int, val: int):
        """一行微调控件：`滑块 + 右侧小数字框`。

        用滑块而不是"占满整行的数字框"：数字框拉满一行时，标签在最左、数字在最右，
        中间一大片空白，看着很怪（用户截图反馈）；而且滑块比敲数字更适合拖动微调。
        数字框留着是为了能精确输入。两边都**不吃滚轮**（防误改）。
        """
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        sld = NoWheelSlider(Qt.Horizontal)
        sld.setRange(lo, hi)
        sld.setValue(val)
        sld.setToolTip("拖动微调（滚轮不会改数值）")

        box = NoWheelSpinBox()
        box.setRange(lo, hi)
        box.setValue(val)
        box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box.setFixedWidth(76)     # 66 太挤：数字 + 自绘的上下箭头放不下
        box.setToolTip("可以直接输入精确值；滚轮不会改这里的数值")

        sld.valueChanged.connect(box.setValue)          # setValue 值没变时不会重复发信号
        box.valueChanged.connect(sld.setValue)
        sld.valueChanged.connect(lambda _=None: self.on_adjust_changed())

        h.addWidget(sld, 1)
        h.addWidget(box, 0)
        form.addRow(label, row)
        # 让"滑块 -> 配对数字框"可被外部（复位逻辑/测试）拿到
        sld.value_box = box
        return sld

    def _group_layout(self) -> QGroupBox:
        gb = QGroupBox("4 · 相纸与排版")
        f = QFormLayout(gb)
        f.setContentsMargins(18, 18, 18, 18)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(11)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.cmb_paper = NoWheelComboBox()
        for p in self.lib.papers:
            self.cmb_paper.addItem("%s　%.0f×%.0fmm" % (p.name_zh, p.mm[0], p.mm[1]), p.id)
        self.cmb_paper.setCurrentIndex(1)
        self.cmb_paper.currentIndexChanged.connect(lambda _=None: self._update_layout_info())
        f.addRow("相纸", self.cmb_paper)

        self.sp_gap = NoWheelDoubleSpinBox()
        self.sp_gap.setRange(0.0, 20.0)
        self.sp_gap.setSingleStep(0.5)
        self.sp_gap.setValue(DEFAULT_GAP_MM)
        self.sp_gap.setSuffix(" mm")
        self.sp_gap.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sp_gap.valueChanged.connect(lambda _=None: self._update_layout_info())
        f.addRow("照片间距", self.sp_gap)

        self.sp_margin = NoWheelDoubleSpinBox()
        self.sp_margin.setRange(0.0, 30.0)
        self.sp_margin.setSingleStep(0.5)
        self.sp_margin.setValue(DEFAULT_MARGIN_MM)
        self.sp_margin.setSuffix(" mm")
        self.sp_margin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sp_margin.valueChanged.connect(lambda _=None: self._update_layout_info())
        f.addRow("纸张留边", self.sp_margin)

        self.cmb_crop_line = NoWheelComboBox()
        self.cmb_crop_line.addItem("贯穿式延长线（好对刀）", "cross")
        self.cmb_crop_line.addItem("每张独立方框", "box")
        self.cmb_crop_line.addItem("不画线", "none")
        self.cmb_crop_line.currentIndexChanged.connect(lambda _=None: self._update_layout_info())
        f.addRow("裁剪线", self.cmb_crop_line)

        self.lbl_layout_info = QLabel("")
        self.lbl_layout_info.setWordWrap(True)
        self.lbl_layout_info.setStyleSheet(
            "color:%s;background:%s;border-radius:%dpx;padding:9px 11px;"
            "font-weight:600;" % (style.PRIMARY, style.PRIMARY_SOFT, style.RADIUS))
        f.addRow(self.lbl_layout_info)
        return gb

    def _group_output(self) -> QGroupBox:
        gb = QGroupBox("5 · 输出设置")
        f = QFormLayout(gb)
        f.setContentsMargins(18, 18, 18, 18)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(11)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # ---- 输出目录（用户自定义 + 记住）----
        # 以前只能靠在动作栏里那个后来被删掉的按钮改，界面上根本没有入口；
        # 而且改完不存盘，重启就回到默认。现在：入口在这儿，选完写进 settings.json。
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.ed_out_dir = QLineEdit()
        self.ed_out_dir.setReadOnly(True)
        self.ed_out_dir.setText(self._out_dir)
        self.ed_out_dir.setToolTip("导出（证件照 / 排版照 / 全部照片）会存到这个目录")
        h.addWidget(self.ed_out_dir, 1)
        self.btn_pick_out = QPushButton("选择…")
        self.btn_pick_out.setObjectName("ghost")
        self.btn_pick_out.setToolTip("换个目录存；选完之后下次打开也是这个目录")
        self.btn_pick_out.clicked.connect(self.on_pick_out_dir)
        h.addWidget(self.btn_pick_out)
        self.btn_open_out = QPushButton("打开")
        self.btn_open_out.setObjectName("ghost")
        self.btn_open_out.clicked.connect(self.on_open_out_dir)
        h.addWidget(self.btn_open_out)
        f.addRow("输出目录", row)

        self.cmb_dpi = NoWheelComboBox()
        self.cmb_dpi.addItem("跟随规格（推荐）", 0)
        for d in (300, 350, 600):
            self.cmb_dpi.addItem("%d dpi" % d, d)
        # 换了分辨率，左列「输出设置」卡头的摘要也要跟着变
        self.cmb_dpi.currentIndexChanged.connect(lambda _=None: self._refresh_card_summaries())
        f.addRow("输出分辨率", self.cmb_dpi)
        self.sp_kb = NoWheelSpinBox()
        self.sp_kb.setRange(0, 20480)
        self.sp_kb.setValue(0)
        self.sp_kb.setSuffix(" KB")
        self.sp_kb.setSpecialValueText("不限制")
        self.sp_kb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.addRow("大小上限", self.sp_kb)
        self.lbl_kb_hint = QLabel("")
        self.lbl_kb_hint.setWordWrap(True)
        self.lbl_kb_hint.setStyleSheet("color:%s;" % style.MUTED)
        f.addRow(self.lbl_kb_hint)

        self.cb_single = CheckBox("导出证件照（单张）")
        self.cb_single.setChecked(True)
        self.cb_layout = CheckBox("导出排版照（相纸）")
        self.cb_layout.setChecked(True)
        f.addRow("导出内容", self.cb_single)
        f.addRow("", self.cb_layout)
        return gb

    def _build_action_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("actionBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(10)

        self.lbl_out = QLabel()
        self.lbl_out.setStyleSheet("color:%s;font-size:12px;" % style.MUTED)
        self.lbl_out.setMinimumWidth(200)
        self._update_out_label()
        btn_dir = QPushButton("输出目录…")
        btn_dir.setObjectName("ghost")
        btn_dir.clicked.connect(self.on_pick_out_dir)
        h.addWidget(self.lbl_out, 1)
        h.addWidget(btn_dir)

        self.btn_export_single = PillButton("导出证件照")
        self.btn_export_single.clicked.connect(self.on_export_single_only)

        self.btn_export_layout = PillButton("导出排版照")
        self.btn_export_layout.clicked.connect(self.on_export_layout_only)

        self.btn_export_all = PillButton("导出全部照片", primary=True)
        self.btn_export_all.setMinimumWidth(168)
        self.btn_export_all.clicked.connect(self.on_export_all)

        for b in (self.btn_export_single, self.btn_export_layout, self.btn_export_all):
            b.setCursor(Qt.PointingHandCursor)
            h.addWidget(b)
        return bar

    def _update_out_label(self) -> None:
        d = self._out_dir
        short = d if len(d) <= 42 else ("…" + d[-41:])
        if getattr(self, "lbl_out", None) is not None:
            self.lbl_out.setText("输出目录：%s" % short)
            self.lbl_out.setToolTip(d)
        ed = getattr(self, "ed_out_dir", None)       # 「5 · 输出设置」里那行只读输入框
        if ed is not None:
            ed.setText(d)
            ed.setToolTip(d)
            ed.setCursorPosition(0)

    # ==================== 数据刷新 ====================
    def _check_weights(self) -> None:
        if not Processor.weights_ready():
            show_message(
                self, "抠图模型缺失",
                "程序找不到抠图模型文件，暂时无法处理照片。\n\n"
                "请运行 scripts\\download_weights.ps1 重新下载（约 25MB），"
                "或重新解压一份完整的便携包。",
                kind="warn", detail=Processor.weights_path())

    def _refresh_spec_list(self) -> None:
        cats = ["全部"] + self.lib.categories()
        if self.cmb_category.count() == 0:
            self.cmb_category.addItems(cats)
            self.cmb_category.setCurrentText("全部")
        text = self.ed_search.text().strip()
        if text:
            specs = self.lib.search(text)
        elif self.cmb_category.currentText() in ("", "全部"):
            specs = list(self.lib.photos)
        else:
            specs = self.lib.by_category(self.cmb_category.currentText())
        self.lst_specs.blockSignals(True)
        self.lst_specs.clear()
        for s in specs:
            flag = "" if s.confidence in ("A", "B") else "  · %s级未核实" % s.confidence
            it = QListWidgetItem("%s　%.0f×%.0fmm" % (s.name_zh, s.mm[0], s.mm[1]) + flag)
            it.setData(Qt.UserRole, s.id)
            it.setToolTip("%s\n%d×%dpx @%ddpi\n来源：%s（%s 级）"
                          % (s.name_zh, s.px[0], s.px[1], s.dpi, s.source, s.confidence))
            self.lst_specs.addItem(it)
        self.lst_specs.blockSignals(False)
        if self.lst_specs.count():
            self.lst_specs.setCurrentRow(0)

    def current_spec(self):
        it = self.lst_specs.currentItem()
        if it is None:
            return self.lib.photo("cn_yicun")
        return self.lib.photo(it.data(Qt.UserRole))

    def _update_spec_info(self) -> None:
        s = self.current_spec()
        extra = []
        if s.note:
            extra.append(s.note)
        mn, mx = s.kb_limits
        if mn or mx:
            extra.append("报名系统要求 %s" % (
                ("%d~%d KB" % (mn, mx)) if mn and mx else
                ("不超过 %d KB" % mx) if mx else ("不小于 %d KB" % mn)))
        extra.append("来源：%s（%s 级）" % (s.source, s.confidence))
        self.lbl_spec_info.setText(
            "%s\n%d×%d px @%d dpi → 打印 %.2f×%.2f mm\n%s"
            % (s.name_zh, s.px[0], s.px[1], s.dpi,
               s.px[0] / s.dpi * 25.4, s.px[1] / s.dpi * 25.4,
               "\n".join(extra)))

    def _layout_plan(self, spec=None):
        """当前的排版方案：(相纸, 方案, dpi)。

        **纸与照片必须用同一个 dpi 换算**（见 `layout.plan_for_spec` 的说明）：
        以前纸固定按 300dpi、照片却用规格自带的像素，于是 350dpi 那条一寸规格
        被当成大了 16.7% 的照片，6 寸纸上少排 3 张（9 张而不是 12 张）。
        现在输出分辨率下拉选「跟随规格」时就用规格自己的 dpi。
        """
        spec = spec or self.current_spec()
        paper = self.lib.paper(self.cmb_paper.currentData())
        dpi = self.cmb_dpi.currentData() or spec.dpi
        plan = plan_for_spec(paper, spec, gap_mm=self.sp_gap.value(),
                             margin_mm=self.sp_margin.value(), dpi=dpi)
        return paper, plan, dpi

    def _refresh_card_summaries(self) -> None:
        """把左列卡片的摘要刷成"当前状态"（只有工作台那套布局有这些卡）。

        以前这些摘要是建卡时写死的字符串：用户明明选了「一寸」，卡头还写着「小一寸」——
        他截图问过"为什么我选择 1 寸了，那块还显示小 1 寸"。现在全部接上真实状态：
        规格名 / 底色名 / 自动还是手动 / 相纸+张数 / 输出分辨率 / 照片张数。
        """
        cards = getattr(self, "card_summaries", None)
        if not cards:
            return
        spec = self.current_spec()
        try:
            paper, plan, dpi = self._layout_plan(spec)
            paper_short = paper.name_zh.split("（")[0]
            layout_text = "%s · %d 张" % (paper_short, plan.count)
        except Exception:                                  # noqa: BLE001
            layout_text = "—"
            dpi = spec.dpi
        try:
            bg_name = self.lib.color(self._bg).name_zh
        except Exception:                                  # noqa: BLE001
            bg_name = self._bg
        texts = {
            "spec": spec.name_zh,
            "bg": bg_name,
            "adjust": "手动微调" if self.manual_mode else "自动构图",
            "layout": layout_text,
            "output": "%d dpi" % (self.cmb_dpi.currentData() or spec.dpi),
            "photos": "%d 张" % len(self.items),
        }
        for key, text in texts.items():
            card = cards.get(key)
            if card is not None:
                card.set_summary(text)

    def _update_layout_info(self) -> None:
        s = self.current_spec()
        paper, plan, _dpi = self._layout_plan(s)
        if plan.is_empty:
            # 不用 ⚠/✔ 这类符号字形：微软雅黑里根本没有 U+26A0 / U+2714，
            # 会渲染成豆腐块（已实测），改用颜色 + 文字表达
            self.lbl_layout_info.setStyleSheet(
                "color:%s;background:%s;border-radius:%dpx;padding:9px 11px;"
                "font-weight:600;" % (style.WARN, "#fdf5e6", style.RADIUS))
            self.lbl_layout_info.setText("%s 上排不下 %s，换大一点的相纸"
                                         % (paper.name_zh, s.name_zh))
        else:
            self.lbl_layout_info.setStyleSheet(
                "color:%s;background:%s;border-radius:%dpx;padding:9px 11px;"
                "font-weight:600;" % (style.PRIMARY, style.PRIMARY_SOFT, style.RADIUS))
            self.lbl_layout_info.setText("%s 可排 %d 张（%d 列 × %d 行）"
                                         % (paper.name_zh, plan.count, plan.cols, plan.rows))
            self.lbl_layout_info.setToolTip(plan.summary())
        mn, mx = s.kb_limits
        if mn or mx:
            self.lbl_kb_hint.setText("该规格报名系统要求：%s" % (
                ("%d~%d KB" % (mn, mx)) if mn and mx else
                ("不超过 %d KB" % mx) if mx else ("不小于 %d KB" % mn)))
        else:
            self.lbl_kb_hint.setText("")
        self._refresh_card_summaries()
        if self.preview_layout_mode:
            self.refresh_preview()

    def _sync_color_buttons(self) -> None:
        for cid, btn in self._color_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(cid == self._bg)
            btn.blockSignals(False)

    # ==================== 事件 ====================
    def on_import(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择照片", "", IMAGE_FILTER)
        if paths:
            self.add_photos(paths[:1])

    # ---------- 拖进来导入（整窗有效，不只是预览区）----------
    def dragEnterEvent(self, e):                           # noqa: N802
        md = e.mimeData()
        if md.hasUrls() and any(_is_image_path(u.toLocalFile()) for u in md.urls()):
            e.acceptProposedAction()
            self._drop_hot = True
            self.status.showMessage("松手就导入这张照片")
            return
        super().dragEnterEvent(e)

    def dragLeaveEvent(self, e):                           # noqa: N802
        self._drop_hot = False
        super().dragLeaveEvent(e)

    def dropEvent(self, e):                                # noqa: N802
        self._drop_hot = False
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if _is_image_path(u.toLocalFile())]
        if paths:
            e.acceptProposedAction()
            self.add_photos(paths)
            return
        super().dropEvent(e)

    def on_import_many(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "批量选择照片", "", IMAGE_FILTER)
        if paths:
            self.add_photos(paths)

    def add_photos(self, paths: List[str]) -> None:
        """导入照片：**新加进来的那张自动选中并开始处理**。

        这里踩过一个真 bug（用户："导入一张照片后，再换一张拖进去就不好使了"）：
        以前加完只做 `setCurrentRow(0)` / 重选当前行，第二张虽然进了列表，
        **预览却还停在第一张** —— 用户看到的就是"拖进去没反应"。
        现在明确选中最后新加的那张；如果拖进来的全是已经有的，就选中它并说明，别静默无反应。
        """
        new_rows: List[int] = []
        for raw in paths:
            # 路径统一成规范形式再比：拖放给的是 `C:/x/a.jpg`，文件对话框给的是
            # `C:\x\a.jpg`，不归一化就会把同一张照片当成两张（"重复导入"的另一半原因）。
            p = os.path.normpath(str(raw))
            if any(os.path.normpath(it.path) == p for it in self.items):
                continue
            self.items.append(PhotoItem(path=p))
            item = QListWidgetItem(os.path.basename(p), self.lst_photos)
            item.setToolTip(p)            # 名字被省略号截断时看这里
            new_rows.append(len(self.items) - 1)
        self._update_batch_label()

        if new_rows:
            row = new_rows[-1]
            self.lst_photos.blockSignals(True)
            self.lst_photos.setCurrentRow(row)
            self.lst_photos.blockSignals(False)
            self.on_photo_selected(row)
            more = "（另有 %d 张已加进列表）" % (len(new_rows) - 1) if len(new_rows) > 1 else ""
            self.status.showMessage("已导入 %s%s" % (os.path.basename(self.items[row].path),
                                                    more))
        elif paths:
            p = paths[-1]
            for i, it in enumerate(self.items):
                if it.path == p:
                    self.lst_photos.blockSignals(True)
                    self.lst_photos.setCurrentRow(i)
                    self.lst_photos.blockSignals(False)
                    self.on_photo_selected(i)
                    break
            self.status.showMessage("这张已经在列表里了：%s" % os.path.basename(p))
        self._refresh_card_summaries()

    def _update_batch_label(self) -> None:
        if getattr(self, "lbl_batch", None) is not None:
            self.lbl_batch.setText("共 %d 张照片" % len(self.items))

    def _rebuild_photo_list(self) -> None:
        """按 self.items 重建左栏列表。

        换布局时左栏（含 lst_photos）是**新建的控件**，条目不跟着走；
        不重建的话界面会出现"预览里有图、列表却是空的"这种自相矛盾状态。
        """
        if getattr(self, "lst_photos", None) is None:
            return
        self.lst_photos.blockSignals(True)
        self.lst_photos.clear()
        for it in self.items:
            item = QListWidgetItem(os.path.basename(it.path), self.lst_photos)
            item.setToolTip(it.path)
        self.lst_photos.blockSignals(False)
        self._update_batch_label()
        self._refresh_card_summaries()          # 「照片列表」卡头要显示真实张数
        if self.items:
            row = 0
            for i, it in enumerate(self.items):
                if it is self.current:
                    row = i
                    break
            self.lst_photos.blockSignals(True)
            self.lst_photos.setCurrentRow(row)
            self.lst_photos.blockSignals(False)

    def on_photo_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            return
        self.current = self.items[row]
        self.manual_mode = False
        self.rb_auto.setChecked(True)
        self._reset_sliders()
        if self.current.result is not None:
            self.result = self.current.result
            self.refresh_preview()
        else:
            self.reprocess_current()

    def reprocess_current(self) -> None:
        if self.current is None:
            return
        if self._worker is not None and self._worker.isRunning():
            # 连续改规格时不能静默丢弃后一次请求，否则界面会停在上一个规格的结果上
            self._pending_reprocess = True
            self.status.showMessage("已排队，等当前处理完成后自动重算…")
            return
        spec = self.current_spec()
        self.status.showMessage("正在处理 %s …" % self.current.name)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self._set_busy(True)
        w = ProcessWorker(self.proc, self.current.path, spec, self._bg,
                          hollow_fix=self.cb_hollow.isChecked(), parent=self)
        w.ok.connect(self.on_process_ok)
        w.fail.connect(self.on_process_fail)
        w.finished.connect(self._on_worker_finished)
        self._worker = w
        w.start()

    def _on_worker_finished(self) -> None:
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self._set_busy(False)
        if self._pending_reprocess:
            self._pending_reprocess = False
            self.reprocess_current()

    def _set_busy(self, busy: bool) -> None:
        for w in (self.act_import, self.act_import_many,
                  self.btn_export_single, self.btn_export_layout, self.btn_export_all):
            w.setEnabled(not busy)

    def on_process_ok(self, res) -> None:
        self.result = res
        if self.current is not None:
            self.current.result = res
            self.current.spec_id = res.spec.id
            self.current.bg = res.bg
        fr = res.face_rect
        self.status.showMessage("完成　%s　%d×%d px　%s"
                                % (res.spec.name_zh, res.spec.px[0], res.spec.px[1],
                                   ("人脸 %d×%d" % (fr[2], fr[3])) if fr else "未检测到人脸"))
        self.refresh_preview()

    def on_process_fail(self, msg: str) -> None:
        if self.current is not None:
            self.current.error = msg
        self.result = None
        self.canvas.set_image(None, "")
        self.canvas.set_hint("处理失败：%s" % msg)
        self.status.showMessage("处理失败")
        show_message(self, "处理失败", msg, kind="error")

    def on_spec_selected(self, row: int) -> None:
        if row < 0:
            return
        self._update_spec_info()
        self._update_layout_info()
        self._refresh_card_summaries()
        self.reprocess_current()

    def on_bg_changed(self, bg_id: str) -> None:
        """换底色。

        关键顺序：必须先把新底色写到 result 上，再重裁/合成。
        之前写成「先重裁、后赋值」，导致手动微调模式下 recrop() 读到的还是旧底色，
        必须切换一次规格才生效（用户实测反馈的 bug）。
        """
        self._bg = bg_id
        c = self.lib.color(bg_id)
        self.lbl_bg.setText("当前：%s %s" % (c.name_zh, c.hex_code))
        self._sync_color_buttons()
        self._refresh_card_summaries()
        if self.result is None:
            return
        self.result.bg = bg_id                    # ← 先落盘，后面的重裁才会用新底色
        if self.current is not None:
            self.current.bg = bg_id
        try:
            if self.manual_mode:
                # 手动构图下换底色要按当前微调参数重裁，不能只换底色就丢了几何调整
                self.result.standard_bgr = self.proc.recrop(self.result, self.transform)
            else:
                self.result.standard_bgr = self.proc.recompose(self.result, bg_id)
        except Exception as e:                            # noqa: BLE001
            self.status.showMessage("换底色失败：%s" % e)
            return
        self.refresh_preview()

    def on_pick_custom_color(self) -> None:
        c = QColorDialog.getColor(QColor(255, 255, 255), self, "选择背景色")
        if not c.isValid():
            return
        self.lib.set_custom_color((c.red(), c.green(), c.blue()))
        btn = self._color_buttons.get("custom")
        if btn is None:
            btn = ColorSwatch(c.name(), "自定义")
            btn.clicked.connect(lambda _=False: self.on_bg_changed("custom"))
            self.color_group.addButton(btn)
            self._color_buttons["custom"] = btn
            g = self.btn_custom_color.parentWidget().layout()
            g.addWidget(btn, g.rowCount(), 0, 1, 4)
        btn.hex_code = c.name()
        btn._refresh()
        btn.setChecked(True)
        self.on_bg_changed("custom")

    def on_mode_changed(self) -> None:
        self.manual_mode = self.rb_manual.isChecked()
        # 自动构图下"复位"没有意义，置灰免得点了没反应还以为坏了
        self.btn_reset.setEnabled(self.manual_mode)
        self._refresh_card_summaries()
        if self.manual_mode:
            self.on_adjust_changed()
        else:
            self.refresh_preview()

    def _reset_sliders(self) -> None:
        for w, v in ((self.sl_zoom, 0), (self.sl_offset_y, 0), (self.sl_offset_x, 0),
                     (self.sl_rotate, 0), (self.sl_head, 55), (self.sl_center, 42)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
            # 滑块屏蔽了信号，配对数字框不会跟着走，必须手动同步
            box = getattr(w, "value_box", None)
            if box is not None:
                box.blockSignals(True)
                box.setValue(v)
                box.blockSignals(False)
        self.transform = ManualTransform()

    def _transform_from_sliders(self) -> ManualTransform:
        return ManualTransform(
            zoom=1.0 + self.sl_zoom.value() / 100.0,
            offset_x=self.sl_offset_x.value() / 100.0,
            offset_y=-self.sl_offset_y.value() / 100.0,
            rotate=self.sl_rotate.value() / 10.0,
            head_ratio=max(0.10, self.sl_head.value() / 100.0),
            center_y=max(0.05, self.sl_center.value() / 100.0),
        )

    def on_adjust_changed(self) -> None:
        if self.result is None:
            return
        if not self.manual_mode:
            self.rb_manual.setChecked(True)
            self.manual_mode = True
        self.transform = self._transform_from_sliders()
        try:
            self.result.standard_bgr = self.proc.recrop(self.result, self.transform)
        except Exception as e:                            # noqa: BLE001
            self.status.showMessage("微调失败：%s" % e)
            return
        if self.current is not None:
            self.current.transform = self.transform
        self.refresh_preview()

    def on_canvas_panned(self, dx: float, dy: float) -> None:
        if self.result is None:
            return
        self.rb_manual.setChecked(True)
        self.manual_mode = True
        for w in (self.sl_offset_x, self.sl_offset_y):
            w.blockSignals(True)
        self.sl_offset_x.setValue(int(max(-100, min(100, self.sl_offset_x.value() + dx * 100))))
        self.sl_offset_y.setValue(int(max(-100, min(100, self.sl_offset_y.value() + dy * 100))))
        for w in (self.sl_offset_x, self.sl_offset_y):
            w.blockSignals(False)
        self.on_adjust_changed()

    def on_canvas_zoomed(self, steps: float) -> None:
        if self.result is None:
            return
        self.rb_manual.setChecked(True)
        self.manual_mode = True
        self.sl_zoom.setValue(int(max(-100, min(100, self.sl_zoom.value() + steps * 4))))
        self.on_adjust_changed()

    def on_canvas_reset(self) -> None:
        self._reset_sliders()
        self.rb_auto.setChecked(True)
        self.manual_mode = False
        self.reprocess_current()

    def on_preview_mode_changed(self) -> None:
        self.preview_layout_mode = self.rb_layout.isChecked()
        self.refresh_preview()

    # ==================== 预览 ====================
    def refresh_preview(self) -> None:
        if self.result is None:
            self.canvas.set_image(None, "")
            self.canvas.set_hint("点左上角「导入照片」开始")
            return
        if self.preview_layout_mode:
            spec = self.current_spec()
            paper, plan, _dpi = self._layout_plan(spec)
            if plan.is_empty:
                self.canvas.set_image(None, "")
                self.canvas.set_hint("%s 上排不下 %s" % (paper.name_zh, spec.name_zh))
                return
            canvas = render_layout(self.result.standard_bgr, plan,
                                   crop_line=self.cmb_crop_line.currentData())
            self.canvas.set_image(canvas, "%s　共 %d 张" % (paper.name_zh, plan.count))
            self.canvas.set_frame_ratio(None)
            self.canvas.set_guides([])
            self.lbl_preview_info.setText("排版预览　%d 列 × %d 行 = %d 张"
                                          % (plan.cols, plan.rows, plan.count))
        else:
            img = self.result.standard_bgr
            spec = self.current_spec()
            self.canvas.set_image(img, "%s　%d×%d px" % (spec.name_zh, spec.px[0], spec.px[1]))
            self.canvas.set_frame_ratio(spec.px[0] / spec.px[1])
            fr = self.result.face_rect
            guides = []
            if fr:
                mh, mw = self.result.matting_bgra.shape[:2]
                guides.append((fr[0] / mw, fr[1] / mh, fr[2] / mw, fr[3] / mh, "人脸"))
            self.canvas.set_guides(guides)
            self.lbl_preview_info.setText("模式：%s" % ("手动微调" if self.manual_mode else "自动构图"))

    # ==================== 导出 ====================
    def on_pick_out_dir(self) -> None:
        """选输出目录 —— **选完就写进 settings.json，重启还是它**。"""
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self._out_dir)
        if not d:
            return
        d = os.path.abspath(d)
        try:
            from ..core import settings as _settings
            _settings.set_out_dir(d)
        except Exception as e:                            # noqa: BLE001
            self.status.showMessage("输出目录已切换，但保存失败：%r" % (e,))
        self._out_dir = d
        self._update_out_label()
        self.status.showMessage("输出目录已改为：%s（下次打开也是这里）" % d)
        self._refresh_card_summaries()

    def on_open_out_dir(self) -> None:
        os.makedirs(self._out_dir, exist_ok=True)
        try:
            os.startfile(self._out_dir)                  # noqa: S606  (Windows)
        except Exception:                                # noqa: BLE001
            subprocess.Popen(["explorer", self._out_dir])

    def _export_kwargs(self, spec) -> Dict:
        dpi = self.cmb_dpi.currentData() or spec.dpi
        return {"dpi": dpi, "target_kb": self.sp_kb.value() or None,
                "max_kb": spec.kb_limits[1], "min_kb": spec.kb_limits[0]}

    def _guard_export(self) -> bool:
        if self.result is None:
            show_message(self, "还没有可导出的照片", "请先点左上角「导入照片」。", kind="info")
            return False
        if self._worker is not None and self._worker.isRunning():
            show_message(self, "正在处理中", "照片还在处理，请稍候一两秒再导出。", kind="info")
            return False
        return True

    def _spec_for_export(self):
        """用「实际渲染所用的规格」导出，而不是下拉框当前选中的规格。

        用户改了规格但后台还没处理完时，两者会不一致，按后者命名会张冠李戴。
        """
        spec = self.result.spec
        cur = self.current_spec()
        if spec.id != cur.id:
            self.status.showMessage("提示：本次导出的是 %s（界面已切到 %s，处理完成后可再导出）"
                                    % (spec.name_zh, cur.name_zh))
        return spec

    def _do_export(self, want_single: bool, want_layout: bool) -> None:
        if not self._guard_export():
            return
        if not want_single and not want_layout:
            show_message(self, "没有选择导出内容",
                         "请在「5 · 输出设置」里勾选「导出证件照」或「导出排版照」。", kind="info")
            return
        os.makedirs(self._out_dir, exist_ok=True)
        spec = self._spec_for_export()
        stem = os.path.splitext(self.current.name)[0] if self.current else "photo"
        kw = self._export_kwargs(spec)
        lines, detail = [], []
        try:
            if want_single:
                p = os.path.join(self._out_dir, "%s_%s_%s.jpg" % (stem, spec.id, self._bg))
                # 用户可能在「输出设置」里选了别的分辨率：像素跟着缩放，
                # 保证打印出来的毫米尺寸永远是规格尺寸（见 exporter.resample_to_dpi）
                img = resample_to_dpi(self.result.standard_bgr, spec.mm_size, kw["dpi"])
                rep = save_image(img, p, **kw)
                lines.append("证件照：%s（%.1f KB，%d dpi）"
                             % (os.path.basename(p), rep.kb, rep.dpi_readback[0]))
                if not rep.ok():
                    lines.append("　注意：未满足大小或 dpi 约束，请检查「大小上限」设置")
                detail.extend(rep.messages)
                detail.append(p)
            if want_layout:
                paper, plan, layout_dpi = self._layout_plan(spec)
                if plan.is_empty:
                    lines.append("注意：%s 上排不下 %s，未导出排版照"
                                 % (paper.name_zh, spec.name_zh))
                else:
                    canvas = render_layout(self.result.standard_bgr, plan,
                                           crop_line=self.cmb_crop_line.currentData())
                    p = os.path.join(self._out_dir, "%s_%s排版.jpg" % (stem, paper.id))
                    # dpi 必须和排版时用的一致，否则打印出来的毫米尺寸会错
                    rep = save_image(canvas, p, dpi=layout_dpi, max_kb=kw["max_kb"])
                    lines.append("排版照：%s（%s 共 %d 张，%.1f KB）"
                                 % (os.path.basename(p), paper.name_zh, plan.count, rep.kb))
                    detail.append(p)
        except Exception as e:                            # noqa: BLE001
            show_message(self, "导出失败", str(e), kind="error")
            return
        self.status.showMessage("导出完成 → %s" % self._out_dir)
        show_message(self, "导出完成", "\n".join(lines), kind="info",
                     detail="\n".join(detail))

    def on_export_single_only(self) -> None:
        self._do_export(True, False)

    def on_export_layout_only(self) -> None:
        self._do_export(False, True)

    def on_export_current(self) -> None:
        """按勾选框导出（保留给测试与旧快捷键）。"""
        self._do_export(self.cb_single.isChecked(), self.cb_layout.isChecked())

    def on_export_all(self) -> None:
        if not self.items:
            show_message(self, "还没有导入照片", "请先点左上角「导入照片」。", kind="info")
            return
        if not (self.cb_single.isChecked() or self.cb_layout.isChecked()):
            show_message(self, "没有选择导出内容",
                         "请在「5 · 输出设置」里勾选要导出的内容。", kind="info")
            return
        if self._batch is not None and self._batch.isRunning():
            show_message(self, "批量导出进行中", "请等待当前批次完成。", kind="info")
            return
        os.makedirs(self._out_dir, exist_ok=True)
        spec = self.current_spec()
        pid = self.cmb_paper.currentData()
        jobs = []
        for it in self.items:
            jobs.append({
                "path": it.path, "spec": spec, "bg": self._bg,
                "transform": (self.transform if (it is self.current and self.manual_mode)
                              else (it.transform if it is not self.current else None)),
                "stem": os.path.splitext(it.name)[0],
            })
        dpi = self.cmb_dpi.currentData() or 0
        self.progress.setVisible(True)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        w = BatchExportWorker(self.proc, jobs, self._out_dir, self.lib.paper(pid),
                              self.sp_gap.value(), self.sp_margin.value(),
                              self.cmb_crop_line.currentData(),
                              target_kb=self.sp_kb.value() or 0, dpi_override=dpi,
                              export_single=self.cb_single.isChecked(),
                              export_layout=self.cb_layout.isChecked(), parent=self)
        w.progress.connect(lambda i, n, s: (self.progress.setValue(i),
                                            self.status.showMessage("%d/%d  %s" % (i, n, s))))
        w.itemDone.connect(lambda path, ok, msg:
                           self.status.showMessage("%s %s" % ("完成" if ok else "失败", msg)))
        w.allDone.connect(self.on_batch_done)
        self._batch = w
        w.start()

    def on_batch_done(self, ok: int, total: int) -> None:
        self.progress.setVisible(False)
        self.status.showMessage("批量导出完成：%d/%d 成功" % (ok, total))
        show_message(self, "批量导出完成",
                     "成功 %d / 共 %d 张。" % (ok, total),
                     kind="info" if ok == total else "warn",
                     detail="输出目录：\n" + self._out_dir)

    def on_about(self) -> None:
        from .. import APP_NAME, __version__
        from ..core.pipeline import Processor
        weights = Processor.weights_path()
        have = os.path.exists(weights)
        show_message(
            self, "关于 " + APP_NAME,
            "%s　v%s\n本地离线运行，照片不会上传到任何地方。" % (APP_NAME, __version__),
            kind="info",
            detail=(
                "抠图模型：%s\n%s\n\n"
                "—— 开源组件 ——\n"
                "HivisionIDPhotos   Apache-2.0   github.com/Zeyi-Lin/HivisionIDPhotos\n"
                "MODNet             Apache-2.0   人像抠图模型\n"
                "MTCNN              MIT          人脸检测\n"
                "ONNX Runtime       MIT\n"
                "OpenCV             Apache-2.0\n"
                "PySide6 / Qt       LGPL-3.0\n"
                "Pillow             MIT-CMU\n"
                "piexif             MIT\n\n"
                "本项目不含任何非商用授权的模型（不含 RMBG-1.4/2.0、insightface、\n"
                "CelebAMask-HQ 衍生的权重）。\n"
                "内核许可证原文：安装目录 app\\vendor\\LICENSE\n"
                "对内核的修改：docs\\vendor-patches.md"
                % ("已就位" if have else "缺失（请运行 scripts\\download_weights.ps1）", weights)))

    def closeEvent(self, e):  # noqa: N802
        for w in (self._worker, self._batch):
            if w is not None and w.isRunning():
                w.wait(3000)
        # 检查更新的线程可能还在跑：给一点时间收尾，别让 Qt 在销毁窗口时抱怨
        checker = getattr(self, "_update_checker", None)
        if checker is not None and checker.isRunning():
            checker.wait(2000)
            self._update_checker = None
        super().closeEvent(e)
