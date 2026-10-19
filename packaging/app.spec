# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（自己写的，不参考上游那个引用不存在文件的 app.spec）。

产出：便携版单文件 exe，模型权重内置，双击即用。

关键点：
- pathex 里加上 app/vendor，这样 hivision 会被静态分析，它的依赖
  （mtcnnruntime / onnxruntime 等）才会被正确收进来。
- 权重与 LUT 是二进制资源，必须单独作为 datas 打进 hivision 包内对应路径，
  否则 human_matting.py 按 __file__ 拼出来的路径找不到文件。
- 不打包 watermark 用的那个 4MB 中文字体（我们不用水印功能，且字体有独立授权）。
"""
import os

from PyInstaller.utils.hooks import collect_data_files

_SPEC_DIR = SPECPATH                                        # noqa: F821  (PyInstaller 注入)
ROOT = os.path.dirname(os.path.abspath(_SPEC_DIR))
APP = os.path.join(ROOT, "app")
VENDOR = os.path.join(APP, "vendor")
HIV = os.path.join(VENDOR, "hivision")

datas = [
    (os.path.join(APP, "data"), "app/data"),
    (os.path.join(APP, "resources"), "app/resources"),
    # 内核二进制资源（放到 hivision 包内的原始相对路径）
    (os.path.join(HIV, "creator", "weights", "hivision_modnet.onnx"),
     "hivision/creator/weights"),
    (os.path.join(HIV, "plugin", "beauty", "lut"), "hivision/plugin/beauty/lut"),
    (os.path.join(HIV, "plugin", "template", "assets"),
     "hivision/plugin/template/assets"),
]
# mtcnnruntime 把 MTCNN 的 pnet/onet/rnet.onnx 作为包内数据文件发布，
# 只在 hiddenimports 里写它，PyInstaller 不会收集这些权重，运行时会报 NO_SUCHFILE。
datas += collect_data_files("mtcnnruntime")

hiddenimports = [
    # 布局模块由 app/ui/layouts/__init__.py 静态 import，正常能被收集；这里再显式列一遍做双保险
    "app.ui.layouts.classic", "app.ui.layouts.rail_drawer",
    "app.ui.layouts.dashboard", "app.ui.layouts.inspector",
    "app.ui.layouts.canvas_first",
    "hivision",
    "mtcnnruntime",
    "piexif",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "onnxruntime",
    "cv2",
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

# 这里**刻意不使用** PyInstaller 的 Splash 启动画面。
# 原因：splash 的显示/关闭要和引导程序做一次进程间握手（Windows 上是命名管道），
# 握手被环境挡住时 pyi_splash.close() 会永久阻塞——实测本机沙箱里就是这个结果：
# 解压 6 秒就完成了，但主窗口永远不出现，进程一直挂着。
# 用户反馈的"启动窗口一直搁那儿不消失"也出在同一个机制上。
# 单文件版的解压本身只要 3~4 秒，不值得为此冒程序起不来的风险；
# 想要"秒开"的用户用便携文件夹版或安装版即可。
exe = EXE(                                                  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="证件照排版助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX 压缩 onnxruntime 的 DLL 容易出问题，关掉
    # 关键：单文件模式默认把 ~300MB 内容解压到系统 %TEMP%。本机 %TEMP% 在 C 盘，
    # 实测直接把 C 盘撑爆（只剩 0.01GB）并导致启动卡死。
    # 设成 "." 后引导程序会解压到「exe 自己所在的目录」，也就是用户把 exe 放哪就写哪，
    # 不再碰系统盘。代价：该目录需要可写，且崩溃时可能留下 _MEIxxxx 文件夹。
    runtime_tmpdir=".",
    console=False,             # 窗口程序，不弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(APP, "resources", "icon.ico"),
    version=None,
)
