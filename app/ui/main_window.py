# -*- coding: utf-8 -*-
"""工作台主窗口：单张导入、可复现预览和快照式导出。

处理线程只使用照片路径、规格与空洞修补选项。界面丢弃过期请求，
并使用最新的底色和构图设置渲染可导出的成品。
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, replace
import re
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QRectF, QSignalBlocker, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup,
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
from .worker import PhotoRequest, ProcessWorker

IMAGE_FILTER = "图片 (*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff);;所有文件 (*.*)"
APP_TITLE = "证件照排版助手"

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def _is_image_path(path: str) -> bool:
    """拖进来的文件是不是图片（拖拽只看后缀，够用了）。"""
    return os.path.splitext(path or "")[1].lower() in IMAGE_EXTS


def _spec_display_order(spec):
    """寸数规格集中置顶，同寸按小/标准/大及实际尺寸排列，其余保持原顺序。"""
    match = re.match(r"^(小|大)?([一二三四五六七八九十]|\d+(?:\.\d+)?)寸", spec.name_zh)
    if match is None:
        return (1, 0, 0, 0, 0)
    variant, number = match.groups()
    chinese = dict(zip("一二三四五六七八九十", range(1, 11)))
    inches = chinese[number] if number in chinese else float(number)
    return (0, inches, {"小": -1, None: 0, "大": 1}[variant], *spec.mm)


def is_elevated() -> bool:
    """当前进程是不是**以管理员身份**在跑。

    这条直接影响拖放：Windows 的 UIPI 不允许普通权限的"资源管理器"把文件拖进
    提权进程 —— 所以管理员身份运行时拖拽会**整个失效**（按钮导入不受影响）。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:                                      # noqa: BLE001
        return False


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
    error: str = ""

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
        self._request_seq = 0
        self._request: Optional[PhotoRequest] = None
        self._processed = None
        self._process_error = ""
        self._selected_spec_id = "cn_yicun"
        self._close_pending = False
        self._preserve_original_bg = False
        try:
            from ..core.settings import load as load_settings
            self._preserve_original_bg = bool(load_settings().get("preserve_original_background", False))
        except Exception:  # noqa: BLE001
            pass
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
        style.install_continuous_style(QApplication.instance())
        self._build_ui()
        self._refresh_spec_list()
        self._update_layout_info()
        self._sync_color_buttons()
        self._update_bg_label()
        self._check_weights()
        # 让"窗口任意位置都能拖照片进来"真的成立（子控件不许自己吞掉拖放）
        try:
            self._block_child_drops()
        except Exception:                                  # noqa: BLE001
            pass
        if is_elevated():
            self.status.showMessage(
                "提示：程序是「以管理员身份」运行的，Windows 会拦住从资源管理器拖进来的文件；"
                "要拖拽请用「帮助 → 以普通权限重新打开」")

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
        for name in ("lst_photos", "lbl_batch", "glass_stage", "card_summaries",
                     "left_refit", "preview_toggle"):
            if hasattr(self, name):
                delattr(self, name)
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
            self._apply_round_region()
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
        """Use compositor corners for SCA; its acrylic ignores a Qt/native region."""
        if not self._frameless:
            return
        from .corners import continuous_region
        from . import acrylic
        hwnd = int(self.winId())
        if self.isMaximized():
            self.clearMask()
            acrylic.clear_round_region(hwnd)
            self._round_mode = "maximized"
        elif getattr(self, "glass_mode", "none").startswith("sca-"):
            self.clearMask()
            acrylic.clear_round_region(hwnd)
            if acrylic.set_round_corners(hwnd):
                self._round_mode = "dwm"
            else:
                # A clipped Qt surface cannot clip SCA. Disable the unsupported
                # material first, so the fallback really has transparent corners.
                acrylic.disable_glass(hwnd)
                self.glass_mode = "none"
                acrylic.disable_system_round_corners(hwnd)
                self.setMask(continuous_region(QRectF(self.rect()), chrome.WINDOW_RADIUS))
                self._round_mode = "continuous"
        else:
            acrylic.disable_system_round_corners(hwnd)
            self.setMask(continuous_region(QRectF(self.rect()), chrome.WINDOW_RADIUS))
            self._round_mode = "continuous"
        frame = self.centralWidget()
        if isinstance(frame, chrome.Frame):
            frame.outline_mode = self._round_mode
            frame.update()

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
        values = {name: getattr(self, name).value() for name in (
            "sl_zoom", "sl_offset_y", "sl_offset_x", "sl_rotate", "sl_head", "sl_center",
            "sp_gap", "sp_margin", "sp_kb")}
        choices = {name: getattr(self, name).currentData() for name in (
            "cmb_paper", "cmb_crop_line", "cmb_dpi")}
        checks = {name: getattr(self, name).isChecked() for name in (
            "rb_auto", "rb_manual", "rb_photo", "rb_layout", "cb_hollow", "cb_single", "cb_layout")}
        search = self.ed_search.text()
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
        # Restore controls without issuing inference requests or partial render updates.
        names = list(values) + list(choices) + list(checks) + ["ed_search"]
        blockers = [QSignalBlocker(getattr(self, name)) for name in names]
        for name, value in values.items():
            control = getattr(self, name)
            control.setValue(value)
            if hasattr(control, "value_box"):
                control.value_box.setValue(value)
        for name, value in choices.items():
            control = getattr(self, name)
            control.setCurrentIndex(control.findData(value))
        for name, value in checks.items():
            getattr(self, name).setChecked(value)
        self.ed_search.setText(search)
        del blockers
        self._rebuild_photo_list()
        self._refresh_spec_list()
        self._update_layout_info()
        self._sync_color_buttons()
        self._update_bg_label()
        self._block_child_drops()
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
        if getattr(self, "_glass_done", False):
            self._apply_round_region()
        # 用户没自己拖过分隔条时，跟着窗口宽度重新分配；拖过之后就不再动它
        if not getattr(self, "_user_split", True):
            self._apply_split_proportions()

    def _build_menu(self) -> None:
        m_file = self.menubar.addMenu("文件")
        # v1.6.6：不再有「批量导入」—— 一次只有一张照片，再导入就是替换掉它。
        a = QAction("导入照片（替换当前照片）", self)
        a.setShortcut("Ctrl+O")
        a.triggered.connect(self.on_import)
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

        # 以管理员身份运行时，Windows 会拦住从资源管理器拖进来的文件（UIPI），
        # 这里给一条"一键用普通权限重开"的出路 —— 不用重新安装、也不用去改快捷方式。
        if is_elevated():
            self.act_unelevate = QAction("以普通权限重新打开（恢复拖放文件）", self)
            self.act_unelevate.setToolTip(
                "管理员窗口收不到普通权限的拖放事件；用普通权限重开后就能直接把照片拖进来")
            self.act_unelevate.triggered.connect(self.relaunch_unelevated)
            m_help.addAction(self.act_unelevate)
            m_help.addSeparator()

        a = QAction("关于 / 开源许可", self)
        a.triggered.connect(self.on_about)
        m_help.addAction(a)

    def relaunch_unelevated(self) -> None:
        """用**普通权限**重新打开自己（拖放被 UIPI 拦住时的出路）。

        小技巧：让不比我们高的 `explorer.exe` 去启动 exe —— 资源管理器是普通权限，
        它拉起来的进程也是普通权限。这样不用重装、也不用去改快捷方式。
        """
        import sys

        exe = sys.executable
        try:
            subprocess.Popen(["explorer.exe", exe])
        except Exception as e:                            # noqa: BLE001
            show_message(self, "没法用普通权限重开",
                         "可以手动关掉程序，再直接双击程序图标重新打开"
                         "（不要右键选「以管理员身份运行」）。",
                         kind="warn", detail="%r" % (e,))
            return
        self.close()

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
        if self._close_pending or getattr(self, "_checking_update", False):
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
        if self._close_pending:
            return
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
        if self._close_pending:
            return
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

        if self._close_pending:
            return
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
        # 装在 Program Files 又没提权时，合并那一步要弹 UAC：先把话说在前面，
        # 别让用户下载完 130MB 才被一个弹窗吓一跳（或者更糟：什么都看不到）。
        try:
            if not updater.dir_writable(updater.app_dir()):
                win.set_note("程序装在需要管理员权限的目录，合并时会弹一次 UAC 授权，点「是」即可。")
        except Exception:                                 # noqa: BLE001
            pass
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
        if self._close_pending:
            win.set_error("已取消更新", "正在关闭程序。")
            win.close()
            return
        geom = (win.x(), win.y(), win.width(), win.height())
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

    def _active_qthreads(self):
        """Return live child QThreads so neither close nor updater teardown destroys one."""
        found = []
        for name in ("_worker", "_update_checker", "_update_downloader"):
            thread = getattr(self, name, None)
            if thread is not None and thread not in found and thread.isRunning():
                found.append(thread)
        return found

    def _quit_app(self) -> None:
        from PySide6.QtWidgets import QApplication
        if self._active_qthreads():
            QTimer.singleShot(50, self._quit_app)
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _finish_deferred_close(self) -> None:
        if self._active_qthreads():
            QTimer.singleShot(50, self._finish_deferred_close)
            return
        self._close_timer_armed = False
        self.close()

    def _update_failed(self, msg: str, win) -> None:
        if self._close_pending:
            win.set_error("更新已停止", "正在关闭程序。")
            win.close()
            return
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
        if self._close_pending:
            return
        self.show()
        self.raise_()
        self.status.showMessage("已取消更新，还是原来的 v%s" % __version__)

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        self.act_import = QAction("+  导入照片", self)
        self.act_import.setShortcut("Ctrl+O")
        self.act_import.setToolTip("选择一张照片（会替换掉当前这张）")
        self.act_import.triggered.connect(self.on_import)
        # v1.6.6：去掉「批量导入」（一次只处理一张，新照片直接替换旧的）
        self.act_open_out = QAction("打开输出目录", self)
        self.act_open_out.triggered.connect(self.on_open_out_dir)
        self.act_reset_layout = QAction("恢复默认布局", self)
        self.act_reset_layout.setToolTip("把卡片摆回默认位置和大小（Ctrl+0）")
        self.act_reset_layout.triggered.connect(self.reset_layout)
        tb.addAction(self.act_import)
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
        self.cb_keep_original_bg = CheckBox("保留原照片底色（不换底）")
        self.cb_keep_original_bg.setToolTip(
            "保留导入照片的背景纹理；照片仍会裁切和构图，超出原图范围时复制边缘像素。"
            "启用后颜色色块不参与成品背景。")
        self.cb_keep_original_bg.setChecked(self._preserve_original_bg)
        self.cb_keep_original_bg.toggled.connect(self.on_preserve_original_changed)
        g.addWidget(self.cb_keep_original_bg, rows + 1, 0, 1, cols)
        self.lbl_bg = QLabel("")
        self.lbl_bg.setStyleSheet("color:%s;" % style.MUTED)
        g.addWidget(self.lbl_bg, rows + 2, 0, 1, cols)
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
        self.cmb_dpi.currentIndexChanged.connect(self._on_output_dpi_changed)
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
        specs = sorted(specs, key=_spec_display_order)
        selected_id = self._selected_spec_id
        self.lst_specs.blockSignals(True)
        self.lst_specs.clear()
        selected_row = -1
        for s in specs:
            flag = "" if s.confidence in ("A", "B") else "  · %s级未核实" % s.confidence
            size_text = "%g×%gmm" % s.mm
            label = s.name_zh if size_text in s.name_zh else "%s　%s" % (s.name_zh, size_text)
            it = QListWidgetItem(label + flag)
            it.setData(Qt.UserRole, s.id)
            it.setToolTip("%s\n%d×%dpx @%ddpi\n来源：%s（%s 级）"
                          % (s.name_zh, s.px[0], s.px[1], s.dpi, s.source, s.confidence))
            self.lst_specs.addItem(it)
            if s.id == selected_id:
                selected_row = self.lst_specs.count() - 1
        self.lst_specs.setCurrentRow(selected_row)
        self.lst_specs.blockSignals(False)
        # 搜索过滤不悄悄改动规格；无匹配/被过滤时仍保留当前规格和已生成结果。
        self._update_spec_info()
        self._update_layout_info()

    def current_spec(self):
        it = self.lst_specs.currentItem()
        spec_id = it.data(Qt.UserRole) if it is not None else self._selected_spec_id
        try:
            return self.lib.photo(spec_id)
        except Exception:
            return self.lib.photo("cn_yicun")

    def _update_spec_info(self) -> None:
        s = self.current_spec()
        extra = []
        if s.note:
            extra.append(s.note)
        if s.mm_from_px:
            extra.append("毫米为数字像素反算的兼容打印尺寸，不是官方实体尺寸要求。")
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

    def _on_output_dpi_changed(self, _index: int) -> None:
        self._update_layout_info()
        if not self.preview_layout_mode:
            self.refresh_preview()

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
            "bg": "保留原底色" if self._preserve_original_bg else bg_name,
            "adjust": "手动微调" if self.manual_mode else "自动构图",
            "layout": layout_text,
            "output": "%d dpi" % (self.cmb_dpi.currentData() or spec.dpi),
        }
        for key, text in texts.items():
            card = cards.get(key)
            if card is not None:
                card.set_summary(text)
        # 别的（实验）布局还带「照片列表」卡片时才更新它
        photos_card = cards.get("photos")
        if photos_card is not None:
            photos_card.set_summary("%d 张" % len(self.items))

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

    def dragMoveEvent(self, e):                            # noqa: N802
        # **必须有**：Qt 的默认 dragMoveEvent 直接 ignore，drag 中途被 ignore 之后
        # 松手根本不会产生 drop 事件 —— 用户看到的就是"拖到窗口上完全没反应"。
        md = e.mimeData()
        if md.hasUrls() and any(_is_image_path(u.toLocalFile()) for u in md.urls()):
            e.acceptProposedAction()
            return
        super().dragMoveEvent(e)

    def dropEvent(self, e):                                # noqa: N802
        self._drop_hot = False
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if _is_image_path(u.toLocalFile())]
        if paths:
            e.acceptProposedAction()
            self.add_photos(paths)
            return
        super().dropEvent(e)

    def _block_child_drops(self) -> None:
        """把会"吃掉"文件拖放的子控件关掉，保证窗口任意位置都能接住照片。

        日志卡（QPlainTextEdit）、搜索框（QLineEdit）、规格列表（QListWidget）等
        **自己就 acceptDrops**，拖到它们上面时事件被它们吞了 ——
        表现就是"有些地方能拖、有些地方完全没反应"。
        预览区的 DropArea 例外（它就是专门接拖放的）。
        """
        keep = set()
        try:
            from .layouts.studio import DropArea
            keep = {id(w) for w in self.findChildren(DropArea)}
        except Exception:                                  # noqa: BLE001
            pass
        for w in self.findChildren(QWidget):
            if id(w) in keep:
                continue
            if w.acceptDrops():
                w.setAcceptDrops(False)

    def on_import_many(self) -> None:
        """保留接口（老布局/老快捷键可能还连着），但语义已经变成"换一张"。"""
        self.on_import()

    def add_photos(self, paths: List[str]) -> None:
        """导入/拖入照片 —— **一张就够：新的一张直接顶掉旧的那张**。

        用户 v1.6.6 明确要求："去掉照片列表那个功能，一张照片拖进去之后，
        你要再拖另一张，就把前一张覆盖了。"

        所以这里不再是"往列表里加"，而是：
        1. 只认**最后一张**（多选/多拖时以最后一张为准）；
        2. `self.items` 直接换成只有这一张（列表控件若存在，也只剩这一行）；
        3. 立刻选中并重新抠图。
        """
        usable = [os.path.normpath(str(p)) for p in paths if str(p or "").strip()]
        if not usable:
            return
        p = usable[-1]
        same = bool(self.items) and len(self.items) == 1 and \
            os.path.normpath(self.items[0].path) == p
        if same:
            # 拖/选的还是当前这张：重算一次就当"重试"，别什么都不做
            self.status.showMessage("重算这张：%s" % os.path.basename(p))
            self.on_photo_selected(0)
            return

        self.items = [PhotoItem(path=p)]
        self.current = None
        self.result = None
        if getattr(self, "lst_photos", None) is not None:     # 实验布局里还有列表
            self.lst_photos.blockSignals(True)
            self.lst_photos.clear()
            item = QListWidgetItem(os.path.basename(p), self.lst_photos)
            item.setToolTip(p)
            self.lst_photos.setCurrentRow(0)
            self.lst_photos.blockSignals(False)
        self._update_batch_label()
        self.on_photo_selected(0)
        self.status.showMessage("已换上新照片：%s" % os.path.basename(p))
        self._refresh_card_summaries()

    def _update_batch_label(self) -> None:
        if getattr(self, "lbl_batch", None) is not None:
            self.lbl_batch.setText("已导入 %s" % os.path.basename(self.items[0].path)
                                   if self.items else "还没有导入照片")

    def _rebuild_photo_list(self) -> None:
        """按 self.items 重建左栏列表（只有自带列表的实验布局才需要）。

        换布局时左栏是**新建的控件**，条目不跟着走；不重建会出现
        "预览里有图、列表却是空的"这种自相矛盾状态。工作台（默认布局）已经没有列表了，
        这里用 getattr 兜住。
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
        self._refresh_card_summaries()
        if self.items:
            self.lst_photos.blockSignals(True)
            self.lst_photos.setCurrentRow(0)
            self.lst_photos.blockSignals(False)

    def on_photo_selected(self, row: int) -> None:
        if self._close_pending or not 0 <= row < len(self.items):
            return
        self.current = self.items[row]
        self.manual_mode = False
        with QSignalBlocker(self.rb_auto):
            self.rb_auto.setChecked(True)
        self.btn_reset.setEnabled(False)
        self._reset_sliders()
        self.reprocess_current()

    def reprocess_current(self) -> None:
        if self.current is None or self._close_pending:
            return
        self._request_seq += 1
        self._request = PhotoRequest(self._request_seq, self.current.path,
                                     self.current_spec(), self.cb_hollow.isChecked())
        self._processed = self.result = None
        self._process_error = self.current.error = ""
        self._set_busy(True)
        self.refresh_preview()
        if self._worker is None:
            self._start_latest_process()
        else:
            self.status.showMessage("已排队，等当前处理完成后自动重算…")

    def _start_latest_process(self) -> None:
        req = self._request
        if req is None or self._worker is not None or self._close_pending:
            return
        self.status.showMessage("正在处理 %s …" % os.path.basename(req.path))
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        w = ProcessWorker(self.proc, req, parent=self)
        w.ok.connect(self.on_process_ok, Qt.ConnectionType.QueuedConnection)
        w.fail.connect(self.on_process_fail, Qt.ConnectionType.QueuedConnection)
        w.finished.connect(self._on_worker_finished, Qt.ConnectionType.QueuedConnection)
        self._worker = w
        w.start()

    def _request_is_current(self, request_id: int) -> bool:
        # 即使原地覆盖同一路径，每次导入也会分配新编号。
        req = self._request
        return (not self._close_pending and req is not None and req.id == request_id
                and self.current is not None and req.path == self.current.path
                and req.spec.id == self.current_spec().id
                and req.hollow_fix == self.cb_hollow.isChecked())

    @Slot()
    def _on_worker_finished(self) -> None:
        w = self.sender()
        if w is not self._worker:
            return
        self._worker = None
        w.deleteLater()
        if self._close_pending:
            return  # closeEvent 的定时器等其余线程收尾
        if self._request is not w.request:
            self._start_latest_process()
        else:
            self.progress.setVisible(False)
            self.progress.setRange(0, 100)
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        # 处理过程中仍可换图；菜单和快捷键也会经过导出检查。
        for w in (self.btn_export_single, self.btn_export_layout, self.btn_export_all):
            w.setEnabled(not busy)

    @Slot(int, object)
    def on_process_ok(self, request_id: int, res) -> None:
        if not self._request_is_current(request_id):
            return
        self._processed = res
        if self._render_cached_result():
            self.status.showMessage("完成　%s　%d×%d px" % (res.spec.name_zh, *res.size))

    @Slot(int, str)
    def on_process_fail(self, request_id: int, msg: str) -> None:
        if not self._request_is_current(request_id):
            return
        self._process_error = self.current.error = msg
        self.refresh_preview()
        self.status.showMessage("处理失败")
        show_message(self, "处理失败", msg, kind="error")

    def on_spec_selected(self, row: int) -> None:
        if row < 0:
            return
        self._selected_spec_id = self.lst_specs.item(row).data(Qt.UserRole)
        self._update_spec_info()
        self._update_layout_info()
        self._refresh_card_summaries()
        self.reprocess_current()

    def _update_bg_label(self) -> None:
        if self._preserve_original_bg:
            text = "当前：保留原底色"
        else:
            color = self.lib.color(self._bg)
            text = "当前：%s %s" % (color.name_zh, color.hex_code)
        self.lbl_bg.setText(text)
        for btn in [*self._color_buttons.values(), self.btn_custom_color]:
            btn.setEnabled(not self._preserve_original_bg)

    def _render_cached_result(self) -> bool:
        if self._processed is None or self._close_pending:
            return False
        self.result = None  # 渲染出错时也不能导出旧成品
        self._process_error = ""
        try:
            res = replace(self._processed, bg=self._bg,
                          preserve_original=self._preserve_original_bg)
            pixels = (self.proc.recrop(res, self.transform) if self.manual_mode
                      else self.proc.recompose(res, self._bg))
            self.result = replace(res, standard_bgr=pixels)
        except Exception as e:                         # noqa: BLE001
            self._process_error = "构图失败：%s" % e
            self.status.showMessage(self._process_error)
        self.refresh_preview()
        return self.result is not None

    @Slot(bool)
    def on_preserve_original_changed(self, checked: bool) -> None:
        self._preserve_original_bg = bool(checked)
        self._update_bg_label()
        self._refresh_card_summaries()
        self._render_cached_result()
        try:
            from ..core.settings import save as save_settings
            save_settings(preserve_original_background=self._preserve_original_bg)
        except OSError as e:
            self.status.showMessage("底色选项已切换，但无法保存到下次启动：%s" % e)

    def on_bg_changed(self, bg_id: str) -> None:
        self._bg = bg_id
        self._sync_color_buttons()
        self._update_bg_label()
        self._refresh_card_summaries()
        if not self._preserve_original_bg:
            self._render_cached_result()

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
        self.btn_reset.setEnabled(self.manual_mode)
        self.transform = self._transform_from_sliders() if self.manual_mode else ManualTransform()
        self._refresh_card_summaries()
        self._render_cached_result()

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
        if not self.manual_mode:
            self.rb_manual.setChecked(True)
        else:
            self.transform = self._transform_from_sliders()
            self._render_cached_result()

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
        with QSignalBlocker(self.rb_auto):
            self.rb_auto.setChecked(True)
        self.on_mode_changed()

    def on_preview_mode_changed(self) -> None:
        self.preview_layout_mode = self.rb_layout.isChecked()
        self.refresh_preview()

    # ==================== 预览 / 导出共用渲染 ====================
    def _output_dpi(self, spec) -> int:
        return self.cmb_dpi.currentData() or spec.dpi

    def _photo_for_output(self, result, dpi):
        if dpi == result.spec.dpi:
            return result.standard_bgr  # 保留办事规格定义的原生像素数
        return resample_to_dpi(result.standard_bgr, result.spec.mm_size, dpi)

    def _sheet_for_output(self, result, plan):
        return render_layout(self._photo_for_output(result, plan.dpi), plan,
                             crop_line=self.cmb_crop_line.currentData())

    def _clear_preview(self, hint: str) -> None:
        self.canvas.set_image(None)
        self.canvas.set_frame_ratio(None)
        self.canvas.set_hint(hint)
        self.lbl_preview_info.setText("")

    def refresh_preview(self) -> None:
        result = self.result
        if result is None:
            hint = ("正在处理当前照片…" if self.current else "点左上角「导入照片」开始")
            self._clear_preview(self._process_error or hint)
            return
        spec = result.spec
        bg_label = "原底色" if result.preserve_original else self.lib.color(result.bg).name_zh
        if self.preview_layout_mode:
            paper, plan, _ = self._layout_plan(spec)
            if plan.is_empty:
                self._clear_preview("%s 上排不下 %s" % (paper.name_zh, spec.name_zh))
                return
            self.canvas.set_image(self._sheet_for_output(result, plan),
                                  "%s　共 %d 张" % (paper.name_zh, plan.count))
            self.canvas.set_frame_ratio(None)
            self.lbl_preview_info.setText("%d 列 × %d 行 = %d 张　%s"
                                          % (plan.cols, plan.rows, plan.count, bg_label))
        else:
            dpi = self._output_dpi(spec)
            img = self._photo_for_output(result, dpi)
            h, w = img.shape[:2]
            self.canvas.set_image(img, "%s　%d×%d px @%d dpi" % (spec.name_zh, w, h, dpi))
            self.canvas.set_frame_ratio(w / h)
            self.lbl_preview_info.setText("%s　%s" % ("手动微调" if self.manual_mode else "自动构图",
                                                    bg_label))

    # ==================== 导出 ====================
    def on_pick_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self._out_dir)
        if not d:
            return
        self._out_dir = os.path.abspath(d)
        self._update_out_label()
        try:
            from ..core.settings import set_out_dir
            set_out_dir(self._out_dir)
        except OSError as e:
            self.status.showMessage("本次输出目录已切换，但无法保存到下次启动：%s" % e)
        else:
            self.status.showMessage("输出目录已保存：%s" % self._out_dir)

    @staticmethod
    def _open_output_folder(directory: str) -> None:
        try:
            os.startfile(directory)                       # noqa: S606  (Windows)
        except Exception:                                # noqa: BLE001
            subprocess.Popen(["explorer.exe", directory])

    def on_open_out_dir(self) -> None:
        directory = os.path.abspath(self._out_dir)
        try:
            os.makedirs(directory, exist_ok=True)
            self._open_output_folder(directory)
        except OSError as e:
            self.status.showMessage("无法打开输出文件夹：%s" % directory)
            show_message(self, "无法打开输出文件夹", directory, kind="warn", detail=str(e))

    def _export_kwargs(self, spec) -> Dict:
        dpi = self.cmb_dpi.currentData() or spec.dpi
        return {"dpi": dpi, "target_kb": self.sp_kb.value() or None,
                "max_kb": spec.kb_limits[1], "min_kb": spec.kb_limits[0]}

    def _can_export(self) -> bool:
        req = self._request
        return (self.result is not None and req is not None
                and self.result.spec.id == req.spec.id and self._request_is_current(req.id))

    def _do_export(self, want_single: bool, want_layout: bool) -> None:
        if not self._can_export():
            reason = self._process_error or ("请等待当前照片处理完成。" if self.current
                                              else "请先导入一张照片。")
            show_message(self, "还没有可导出的照片", reason, kind="info")
            return
        if not want_single and not want_layout:
            show_message(self, "没有选择导出内容", "请在「输出设置」勾选要导出的内容。", kind="info")
            return
        result = self.result
        spec = result.spec
        from ..core.export_paths import export_stem, reserve_export_path

        source_stem = os.path.splitext(self.current.name)[0]
        directory = os.path.abspath(self._out_dir)
        if result.preserve_original:
            background = "原底色(original)"
        else:
            color = self.lib.color(result.bg)
            background = color.name_zh + (color.hex_code if color.id == "custom" else "")
        lines, detail, written = [], [], []
        warning = False
        failed = False

        def write(image, paper=None, **kwargs):
            stem = export_stem(source_stem, spec, background, paper)
            with reserve_export_path(directory, stem) as path:
                report = save_image(image, path, **kwargs)
            written.append(path)
            detail.extend([path, *report.messages])
            return report
        if want_single:
            try:
                kw = self._export_kwargs(spec)
                rep = write(self._photo_for_output(result, kw["dpi"]), **kw)
                lines.append("证件照：%s（%.1f KB）" % (os.path.basename(written[-1]), rep.kb))
                if not rep.ok():
                    lines.append("单张文件未满足大小或 DPI 要求，请查看详情。")
                    warning = True
            except Exception as e:                        # noqa: BLE001
                failed = True
                lines.append("证件照导出失败：%s" % e)
        if want_layout:
            try:
                paper, plan, layout_dpi = self._layout_plan(spec)
                if plan.is_empty:
                    lines.append("%s 上排不下 %s，未导出排版照。" % (paper.name_zh, spec.name_zh))
                    warning = True
                else:
                    rep = write(self._sheet_for_output(result, plan), paper=paper, dpi=layout_dpi)
                    lines.append("排版照：%s（%d 张，%.1f KB）"
                                 % (os.path.basename(written[-1]), plan.count, rep.kb))
                    if not rep.ok():
                        lines.append("排版文件的 DPI 回读异常，请查看详情。")
                        warning = True
            except Exception as e:                        # noqa: BLE001
                failed = True
                lines.append("排版照导出失败：%s" % e)

        if written:
            # 先打开实际成品所在的目录，不让完成弹窗阻塞这一步。
            directory = os.path.dirname(written[0])
            try:
                self._open_output_folder(directory)
            except OSError as e:
                lines.append("文件已保存，但无法打开输出文件夹：%s" % directory)
                detail.append(str(e))
                warning = True
            title = ("部分导出成功" if failed else
                     "导出结果有提示" if warning else "导出完成")
            kind = "warn" if failed or warning else "info"
            self.status.showMessage("%s：%s" % (title, directory))
        else:
            title = "导出未完成" if failed else "没有导出排版照"
            kind = "error" if failed else "warn"
            self.status.showMessage(title)
        show_message(self, title, "\n".join(lines), kind=kind,
                     detail="\n".join(detail))

    def on_export_single_only(self) -> None:
        self._do_export(True, False)

    def on_export_layout_only(self) -> None:
        self._do_export(False, True)

    def on_export_current(self) -> None:
        """按勾选框导出（保留给测试与旧快捷键）。"""
        self._do_export(self.cb_single.isChecked(), self.cb_layout.isChecked())

    def on_export_all(self) -> None:
        # 单张工作流下「全部」就是基于同一预览同时导出单张与整版。
        self.on_export_current()

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
        live = self._active_qthreads()
        if live:
            # Never block the GUI thread or destroy a running QThread. Cancel a download
            # if the user explicitly closes the application, then close when all workers end.
            downloader = getattr(self, "_update_downloader", None)
            if downloader is not None and downloader.isRunning():
                downloader.cancel()
            self._close_pending = True
            e.ignore()
            if not getattr(self, "_close_timer_armed", False):
                self._close_timer_armed = True
                QTimer.singleShot(50, self._finish_deferred_close)
            return
        self._close_pending = True
        self._close_timer_armed = False
        super().closeEvent(e)
