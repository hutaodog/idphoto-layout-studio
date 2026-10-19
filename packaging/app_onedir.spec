# -*- mode: python ; coding: utf-8 -*-
"""安装版用的 onedir 打包配置。

为什么要单独出一份：单文件 exe 每次启动都要把 ~250MB 解压到临时目录，冷启动十几秒；
装到本机的版本用文件夹形式启动是秒开。便携版仍用 app.spec（单文件）。
"""
import os

from PyInstaller.utils.hooks import collect_data_files

_SPEC_DIR = SPECPATH                                        # noqa: F821
ROOT = os.path.dirname(os.path.abspath(_SPEC_DIR))
APP = os.path.join(ROOT, "app")
VENDOR = os.path.join(APP, "vendor")
HIV = os.path.join(VENDOR, "hivision")

datas = [
    (os.path.join(APP, "data"), "app/data"),
    (os.path.join(APP, "resources"), "app/resources"),
    (os.path.join(HIV, "creator", "weights", "hivision_modnet.onnx"),
     "hivision/creator/weights"),
    (os.path.join(HIV, "plugin", "beauty", "lut"), "hivision/plugin/beauty/lut"),
    (os.path.join(HIV, "plugin", "template", "assets"),
     "hivision/plugin/template/assets"),
]
# mtcnnruntime 的 pnet/onet/rnet.onnx 是包内数据文件，必须显式收集（见 app.spec 注释）。
datas += collect_data_files("mtcnnruntime")

hiddenimports = [
    # 布局模块由 app/ui/layouts/__init__.py 静态 import，正常能被收集；
    # 这里再显式列一遍做双保险（曾经因为动态导入导致打包版一个布局都没有）
    "app.ui.layouts.classic", "app.ui.layouts.rail_drawer",
    "app.ui.layouts.dashboard", "app.ui.layouts.inspector",
    "app.ui.layouts.canvas_first",
    "hivision", "mtcnnruntime", "piexif", "PIL.Image", "PIL.ImageDraw",
    "PIL.ImageFont", "onnxruntime", "cv2",
]

excludes = [
    "gradio", "torch", "torchvision", "MNN", "hivisionai", "matplotlib",
    "scipy", "pandas", "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql", "PySide6.QtTest",
    "pytest", "_pytest", "IPython", "notebook",
]

a = Analysis(                                               # noqa: F821
    [os.path.join(APP, "main.py")],
    pathex=[ROOT, VENDOR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)               # noqa: F821

exe = EXE(                                                  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="证件照排版助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(APP, "resources", "icon.ico"),
)

coll = COLLECT(                                             # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="证件照排版助手",
)
